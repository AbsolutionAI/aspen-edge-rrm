"""Append-only audit log with hash chain (BEL-191)."""
from __future__ import annotations
import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


@dataclass
class AuditLog:
    path: Path
    _lock: threading.Lock = None  # type: ignore
    _last_hash: str = "GENESIS"

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        object.__setattr__(self, "_lock", threading.Lock())
        if self.path.exists() and self.path.stat().st_size > 0:
            # recover last hash
            last = None
            with self.path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        last = json.loads(line)
            if last and "hash" in last:
                self._last_hash = last["hash"]

    def append(self, event: str, data: dict | None = None) -> dict:
        rec = {
            "ts": time.time(),
            "event": event,
            "data": data or {},
            "prev": self._last_hash,
        }
        body = _canon({k: rec[k] for k in ("ts", "event", "data", "prev")})
        rec["hash"] = hashlib.sha256(body.encode()).hexdigest()
        line = json.dumps(rec, sort_keys=True) + "\n"
        with self._lock:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
            self._last_hash = rec["hash"]
        return rec

    def verify(self) -> tuple[bool, str]:
        prev = "GENESIS"
        if not self.path.exists():
            return True, "empty"
        with self.path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if rec.get("prev") != prev:
                    return False, f"line {i} prev mismatch"
                body = _canon({k: rec[k] for k in ("ts", "event", "data", "prev")})
                expect = hashlib.sha256(body.encode()).hexdigest()
                if rec.get("hash") != expect:
                    return False, f"line {i} hash mismatch"
                prev = rec["hash"]
        return True, "ok"

    def tail(self, n: int = 20) -> list[dict]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").strip().splitlines()
        return [json.loads(x) for x in lines[-n:]]
