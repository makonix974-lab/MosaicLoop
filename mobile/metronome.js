/* Metronome — Web Audio click with lookahead scheduling.
 *
 * Why lookahead instead of setInterval?
 *   setInterval drifts and jitters by 10-100 ms on mobile when the
 *   browser is busy. We instead schedule click sources slightly in the
 *   future against AudioContext.currentTime (sample-accurate clock),
 *   then wake every 25 ms to push the next batch. Pattern from
 *   https://www.html5rocks.com/en/tutorials/audio/scheduling/
 *
 * Each click is an OscillatorNode + GainNode envelope (no buffers, no
 * fetches, instant). Accent on beat 1 = higher pitch.
 */

const LOOKAHEAD_MS = 25;        // how often we top up the schedule
const SCHEDULE_AHEAD_S = 0.10;  // how far ahead we keep clicks queued

export class Metronome {
  constructor() {
    this._ctx = null;
    this._master = null;        // master GainNode (volume)
    this._timerId = 0;
    this._nextClickTime = 0;    // in AudioContext seconds
    this._beatInBar = 0;        // 0-based, wraps at beatsPerBar
    this._running = false;

    this.bpm = 100;
    this.beatsPerBar = 4;
    this.volume = 0.5;
    this.accentFirst = true;

    // Optional callback fired when a click *plays*, with
    // { beat: 1-based, isAccent, audioTime }.
    this.onTick = null;
  }

  // ----- public API -----

  get isRunning() { return this._running; }

  setBpm(v)         { this.bpm = clamp(Number(v) || 100, 30, 300); }
  setBeatsPerBar(v) { this.beatsPerBar = clamp(Number(v) || 4, 1, 16); }
  setVolume(v) {
    this.volume = clamp(Number(v), 0, 1);
    if (this._master) {
      this._master.gain.setTargetAtTime(this.volume, this._now(), 0.01);
    }
  }
  setAccentFirst(v) { this.accentFirst = !!v; }

  /** Idempotent: ensures the AudioContext exists and is running.
   *  Must be called from a user gesture the first time around. */
  async ensureAudio() {
    if (!this._ctx) {
      const Ctor = window.AudioContext || window.webkitAudioContext;
      this._ctx = new Ctor({ latencyHint: "interactive" });
      this._master = this._ctx.createGain();
      this._master.gain.value = this.volume;
      this._master.connect(this._ctx.destination);
    }
    if (this._ctx.state === "suspended") {
      await this._ctx.resume();
    }
  }

  async start() {
    if (this._running) return;
    await this.ensureAudio();
    this._running = true;
    this._beatInBar = 0;
    this._nextClickTime = this._now() + 0.05;  // tiny offset, avoids glitch
    this._tick();
  }

  stop() {
    this._running = false;
    if (this._timerId) {
      clearTimeout(this._timerId);
      this._timerId = 0;
    }
  }

  /** Returns the wall-clock time (audio time) at which `beat`
   *  (1-based) of the *next* bar will play. Used by the looper to
   *  align recording start with the next downbeat. */
  audioTimeOfNextDownbeat() {
    if (!this._ctx) return 0;
    const beatsLeft = this.beatsPerBar - this._beatInBar;
    const period = 60 / this.bpm;
    return this._nextClickTime + (beatsLeft - 1) * period;
  }

  // ----- private -----

  _now() { return this._ctx ? this._ctx.currentTime : 0; }

  _tick() {
    if (!this._running) return;
    const period = 60 / this.bpm;

    // Push as many clicks as fit in the lookahead window.
    while (this._nextClickTime < this._now() + SCHEDULE_AHEAD_S) {
      const isAccent = this.accentFirst && this._beatInBar === 0;
      this._scheduleClick(this._nextClickTime, isAccent);

      if (typeof this.onTick === "function") {
        // Fire the visual callback at click time so the LED pulses
        // exactly when the click plays. We use a setTimeout because
        // AudioContext doesn't expose 'when this scheduled event fires'.
        const delayMs = (this._nextClickTime - this._now()) * 1000;
        const beatNumber = this._beatInBar + 1;
        const at = this._nextClickTime;
        setTimeout(() => {
          if (this._running) this.onTick({ beat: beatNumber, isAccent, audioTime: at });
        }, Math.max(0, delayMs));
      }

      this._nextClickTime += period;
      this._beatInBar = (this._beatInBar + 1) % this.beatsPerBar;
    }

    this._timerId = setTimeout(() => this._tick(), LOOKAHEAD_MS);
  }

  _scheduleClick(when, isAccent) {
    const ctx = this._ctx;
    const osc = ctx.createOscillator();
    const env = ctx.createGain();

    osc.type = "triangle";
    osc.frequency.value = isAccent ? 1500 : 880;

    // Sharp percussive envelope: fast attack, fast decay.
    const peak = isAccent ? 1.0 : 0.7;
    env.gain.setValueAtTime(0, when);
    env.gain.linearRampToValueAtTime(peak, when + 0.001);
    env.gain.exponentialRampToValueAtTime(0.0001, when + 0.05);

    osc.connect(env);
    env.connect(this._master);
    osc.start(when);
    osc.stop(when + 0.06);
  }
}

function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
