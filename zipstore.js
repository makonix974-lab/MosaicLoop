/* zipstore.js — minimal STORE-only ZIP encoder.
 *
 * Why custom instead of JSZip:
 *   - we already store video files compressed (webm/mp4) — STORE adds
 *     nothing on top of that, so we don't need a deflate library
 *   - keeps the bundle dep-free; the whole encoder is ~120 LOC
 *
 * Format spec: APPNOTE.TXT v6.3.10, sections 4.3 (local headers),
 * 4.3.12 (central directory), 4.3.16 (end-of-CD record). The narrow
 * implementation here only emits records the spec marks as required;
 * Zip64 and ZipCrypto are not supported — files must be < 4 GB each
 * and total CD < 4 GB. That is fine for our use case (a session is
 * maybe 100-200 MB tops).
 */

const SIG_LOCAL = 0x04034b50;
const SIG_CENTRAL = 0x02014b50;
const SIG_EOCD = 0x06054b50;
const VERSION = 20;

// CRC32 lookup table, computed once at module load.
const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) {
      c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
    }
    t[n] = c >>> 0;
  }
  return t;
})();

function crc32(bytes) {
  let crc = 0xFFFFFFFF;
  for (let i = 0; i < bytes.length; i++) {
    crc = (CRC_TABLE[(crc ^ bytes[i]) & 0xFF] ^ (crc >>> 8)) >>> 0;
  }
  return (crc ^ 0xFFFFFFFF) >>> 0;
}

/** Convert a JS Date to MS-DOS time/date (the format ZIP requires). */
function dosDateTime(d) {
  const time = ((d.getHours() & 0x1F) << 11)
             | ((d.getMinutes() & 0x3F) << 5)
             | ((d.getSeconds() >> 1) & 0x1F);
  const date = (((d.getFullYear() - 1980) & 0x7F) << 9)
             | (((d.getMonth() + 1) & 0x0F) << 5)
             | (d.getDate() & 0x1F);
  return { time, date };
}

/** Build a STORE-only ZIP from an array of { name, blob } entries.
 *  Returns a Blob you can wrap in a download link. */
export async function buildZip(entries) {
  const now = new Date();
  const { time, date } = dosDateTime(now);
  const enc = new TextEncoder();

  // First pass: read every blob into a Uint8Array, compute CRC, build
  // the local-file-header + filename + data record. Track offsets so
  // we can fill the central directory afterwards.
  const localChunks = [];
  const records = [];   // { name, crc, size, offset }
  let offset = 0;

  for (const { name, blob } of entries) {
    const data = new Uint8Array(await blob.arrayBuffer());
    const nameBytes = enc.encode(name);
    const crc = crc32(data);

    // Local file header (30 bytes, then filename, then data).
    const header = new ArrayBuffer(30);
    const dv = new DataView(header);
    dv.setUint32(0, SIG_LOCAL, true);
    dv.setUint16(4, VERSION, true);
    dv.setUint16(6, 0, true);              // flags
    dv.setUint16(8, 0, true);              // method = STORE
    dv.setUint16(10, time, true);
    dv.setUint16(12, date, true);
    dv.setUint32(14, crc, true);
    dv.setUint32(18, data.length, true);   // compressed size = uncompressed
    dv.setUint32(22, data.length, true);
    dv.setUint16(26, nameBytes.length, true);
    dv.setUint16(28, 0, true);             // extra length

    localChunks.push(new Uint8Array(header), nameBytes, data);
    records.push({ name, nameBytes, crc, size: data.length, offset });
    offset += 30 + nameBytes.length + data.length;
  }

  // Central directory: one entry per file, then the end-of-CD record.
  const cdStart = offset;
  const cdChunks = [];

  for (const r of records) {
    const cd = new ArrayBuffer(46);
    const dv = new DataView(cd);
    dv.setUint32(0, SIG_CENTRAL, true);
    dv.setUint16(4, VERSION, true);        // version made by
    dv.setUint16(6, VERSION, true);        // version needed
    dv.setUint16(8, 0, true);              // flags
    dv.setUint16(10, 0, true);             // method
    dv.setUint16(12, time, true);
    dv.setUint16(14, date, true);
    dv.setUint32(16, r.crc, true);
    dv.setUint32(20, r.size, true);
    dv.setUint32(24, r.size, true);
    dv.setUint16(28, r.nameBytes.length, true);
    dv.setUint16(30, 0, true);             // extra
    dv.setUint16(32, 0, true);             // comment
    dv.setUint16(34, 0, true);             // disk number start
    dv.setUint16(36, 0, true);             // internal attrs
    dv.setUint32(38, 0, true);             // external attrs
    dv.setUint32(42, r.offset, true);

    cdChunks.push(new Uint8Array(cd), r.nameBytes);
  }

  const cdSize = cdChunks.reduce((s, c) => s + c.length, 0);

  const eocd = new ArrayBuffer(22);
  const evd = new DataView(eocd);
  evd.setUint32(0, SIG_EOCD, true);
  evd.setUint16(4, 0, true);               // disk number
  evd.setUint16(6, 0, true);               // disk where CD starts
  evd.setUint16(8, records.length, true);  // entries on this disk
  evd.setUint16(10, records.length, true); // total entries
  evd.setUint32(12, cdSize, true);
  evd.setUint32(16, cdStart, true);
  evd.setUint16(20, 0, true);              // comment length

  return new Blob(
    [...localChunks, ...cdChunks, new Uint8Array(eocd)],
    { type: "application/zip" }
  );
}
