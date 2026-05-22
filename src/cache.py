"""
Session cache — skip redundant proxy/sync steps when inputs are unchanged.

Persists to `<output_dir>/.session.json`:
- Input fingerprints (filename + size + mtime)
- Proxy paths (if those files still exist)
- Sync alignment result

On the next run, if every input matches its stored fingerprint AND every
proxy file still exists on disk, the cached values are reused. Otherwise
the cache is invalidated and the affected steps re-run.

Pass `--no-cache` to bypass entirely.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


CACHE_FILENAME = ".session.json"
CACHE_VERSION = 1


@dataclass
class InputFingerprint:
    """Cheap, deterministic identity check for one input file."""
    name: str
    size: int
    mtime: float

    @classmethod
    def from_path(cls, path: str) -> "InputFingerprint":
        p = Path(path)
        st = p.stat()
        return cls(name=p.name, size=st.st_size, mtime=round(st.st_mtime, 3))


@dataclass
class CachedAlignment:
    """Serializable form of sync.audio_sync.AlignmentResult."""
    offsets: dict
    confidence: float
    reference_id: str


@dataclass
class SessionCache:
    """
    All cacheable artifacts for one pipeline run.

    Lives at `<output_dir>/.session.json`. Schema is versioned; mismatches
    trigger a rebuild.
    """
    version: int = CACHE_VERSION
    created_at: float = field(default_factory=time.time)
    fingerprints: dict = field(default_factory=dict)   # {input_name: InputFingerprint}
    proxies: dict = field(default_factory=dict)        # {input_name: proxy_path}
    alignment: Optional[CachedAlignment] = None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    @classmethod
    def path_for(cls, output_path: str) -> Path:
        return Path(output_path).parent / CACHE_FILENAME

    @classmethod
    def load(cls, output_path: str) -> Optional["SessionCache"]:
        p = cls.path_for(output_path)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if data.get("version") != CACHE_VERSION:
            return None
        try:
            return cls(
                version=data["version"],
                created_at=data.get("created_at", 0.0),
                fingerprints={
                    k: InputFingerprint(**v) for k, v in data.get("fingerprints", {}).items()
                },
                proxies=dict(data.get("proxies", {})),
                alignment=(
                    CachedAlignment(**data["alignment"])
                    if data.get("alignment") else None
                ),
            )
        except (KeyError, TypeError):
            return None

    def save(self, output_path: str) -> None:
        p = self.path_for(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self.version,
            "created_at": self.created_at,
            "fingerprints": {k: asdict(v) for k, v in self.fingerprints.items()},
            "proxies": self.proxies,
            "alignment": asdict(self.alignment) if self.alignment else None,
        }
        p.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------
    # Validity checks
    # ------------------------------------------------------------------

    def fingerprints_match(self, input_paths: list[str]) -> bool:
        """True iff every input has the same fingerprint as cached."""
        if len(input_paths) != len(self.fingerprints):
            return False
        for path in input_paths:
            try:
                current = InputFingerprint.from_path(path)
            except OSError:
                return False
            cached = self.fingerprints.get(current.name)
            if cached is None:
                return False
            if (cached.size != current.size or
                    abs(cached.mtime - current.mtime) > 0.001):
                return False
        return True

    def proxies_intact(self) -> bool:
        """True iff every cached proxy path still exists on disk."""
        return all(
            Path(p).exists() and Path(p).stat().st_size > 1024
            for p in self.proxies.values()
        )

    def has_valid_alignment(self) -> bool:
        return (
            self.alignment is not None
            and isinstance(self.alignment.offsets, dict)
            and len(self.alignment.offsets) > 0
        )

    # ------------------------------------------------------------------
    # Update helpers (used by Pipeline)
    # ------------------------------------------------------------------

    def update_fingerprints(self, input_paths: list[str]) -> None:
        self.fingerprints = {}
        for path in input_paths:
            try:
                fp = InputFingerprint.from_path(path)
                self.fingerprints[fp.name] = fp
            except OSError:
                pass

    def update_proxies(self, proxies: list[tuple[str, str]]) -> None:
        """proxies is the list of (source_path, proxy_path) tuples."""
        self.proxies = {Path(src).name: proxy for src, proxy in proxies}

    def update_alignment(self, alignment) -> None:
        """alignment is sync.audio_sync.AlignmentResult."""
        self.alignment = CachedAlignment(
            offsets=dict(alignment.offsets),
            confidence=float(alignment.confidence),
            reference_id=str(alignment.reference_id),
        )

    def get_proxies_in_order(self, input_paths: list[str]) -> list[tuple[str, str]]:
        """Return cached proxies as (src, proxy) pairs in the input order."""
        result: list[tuple[str, str]] = []
        for path in input_paths:
            name = Path(path).name
            proxy = self.proxies.get(name)
            if proxy:
                result.append((path, proxy))
        return result
