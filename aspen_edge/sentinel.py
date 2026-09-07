"""Read-only Sentinel consumer for fleet audit events and overview.

Subscribes to:
  aspen.sentinel.audit.event  — hash-chained audit records from edge RRM nodes
  aspen.sentinel.fleet.overview — aggregated fleet health (planned)

Pure observer: no publish side effects.  Flash-only; gatekeeper-aware;
local-first with optional JSONL persistence.

Usage (in-process FleetBus):
  bus = FleetBus()
  sentinel = SentinelConsumer(bus)
  sentinel.start()
  # ... fleet runs ...
  for event in sentinel.tail(10):
      print(event)

Usage (NATS):
  sentinel = SentinelConsumer(bus, persist_path="/var/log/aspen/sentinel.jsonl")
  # ... start with asyncio run loop ...
"""

from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .audit import _canon

Handler = Callable[[dict], None]

# Sentinel NATS subjects
AUDIT_EVENT = "aspen.sentinel.audit.event"
FLEET_OVERVIEW = "aspen.sentinel.fleet.overview"


@dataclass
class SentinelConsumer:
    """Read-only observer that collects sentinel events from the fleet bus.

    Subscribes to audit.event and (when available) fleet.overview.
    Maintains an in-memory ring buffer and optional durable JSONL log.

    Thread-safe via bus serialisation; no lock needed for in-memory reads
    because all mutation happens on the bus callback thread.
    """

    bus: Any  # FleetBus or NatsFleetBus
    max_events: int = 10_000
    persist_path: str | None = None
    node_id: str = "sentinel-1"

    # in-memory ring buffer
    events: list[dict] = field(default_factory=list)
    # indexed by event type
    _by_type: dict[str, list[dict]] = field(
        default_factory=lambda: defaultdict(list)
    )
    _started: bool = False
    _subjects: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.persist_path:
            path = Path(self.persist_path)
            path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Subscribe to all sentinel subjects on the bus."""
        if self._started:
            return
        self._started = True
        self._subscribe(AUDIT_EVENT, self._on_audit_event)
        self._subscribe(FLEET_OVERVIEW, self._on_fleet_overview)
        self._subjects = [AUDIT_EVENT, FLEET_OVERVIEW]

    def stop(self) -> None:
        self._started = False

    @property
    def subjects(self) -> list[str]:
        return list(self._subjects)

    def tail(self, n: int = 20) -> list[dict]:
        """Return the last *n* events (newest first)."""
        return list(reversed(self.events[-n:]))

    def by_type(self, event_type: str, limit: int = 50) -> list[dict]:
        """Return events matching *event_type* (e.g. ``"propose_act"``)."""
        return list(self._by_type.get(event_type, []))[-limit:]

    def search(self, query: str, limit: int = 50) -> list[dict]:
        """Simple substring search across event data (last *limit* events)."""
        q = query.lower()
        matched = []
        for e in reversed(self.events):
            if len(matched) >= limit:
                break
            haystack = json.dumps(e, sort_keys=True, default=str).lower()
            if q in haystack:
                matched.append(e)
        return matched

    def by_time(self, start: float, end: float | None = None) -> list[dict]:
        """Return events whose ``ts`` falls in [*start*, *end*)."""
        end = end or time.time()
        return [e for e in self.events if start <= e.get("ts", 0) < end]

    def count(self) -> int:
        return len(self.events)

    def clear(self) -> None:
        self.events.clear()
        self._by_type.clear()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _subscribe(self, subject: str, handler: Handler) -> None:
        """Subscribe to *subject* using the bus's subscribe API."""
        sub = getattr(self.bus, "subscribe", None)
        if sub:
            # in-process FleetBus
            sub(subject, handler)
        else:
            # NATS — subscribe via bus._nc (async)
            # Caller must run the event loop; we register a wrapper.
            nsub = getattr(self.bus, "_nc", None)
            if nsub is not None:
                import asyncio

                async def _cb(msg):
                    env = json.loads(msg.data.decode())
                    handler(env)

                asyncio.ensure_future(self._nats_sub(subject, _cb))
            else:
                self._log(f"sentinel: no subscribe method on {type(self.bus).__name__}")

    async def _nats_sub(self, subject: str, cb) -> None:
        """NATS async subscribe wrapper."""
        sub = await self.bus._nc.subscribe(subject, cb=cb)
        self._subs_nats = getattr(self, "_subs_nats", []) + [sub]

    def _on_audit_event(self, env: dict) -> None:
        """Callback for ``aspen.sentinel.audit.event``."""
        data = env.get("data", {})
        event = {
            "ts": time.time(),
            "source": env.get("source", "unknown"),
            "subject": AUDIT_EVENT,
            "event": data.get("event", "unknown"),
            "data": data,
            "envelope": env,
        }
        self._store(event)

    def _on_fleet_overview(self, env: dict) -> None:
        """Callback for ``aspen.sentinel.fleet.overview``."""
        event = {
            "ts": time.time(),
            "source": env.get("source", "unknown"),
            "subject": FLEET_OVERVIEW,
            "event": "fleet_overview",
            "data": env.get("data", {}),
            "envelope": env,
        }
        self._store(event)

    def _store(self, event: dict) -> None:
        """Append to ring buffer, trim, optionally persist."""
        self.events.append(event)
        self._by_type[event.get("event", "unknown")].append(event)

        # ring-buffer trim
        if len(self.events) > self.max_events:
            drop = self.events[:-self.max_events]
            self.events = self.events[-self.max_events:]
            for de in drop:
                t = de.get("event", "unknown")
                lst = self._by_type.get(t, [])
                if lst and lst[0] is de:
                    lst.pop(0)

        # durable JSONL
        if self.persist_path:
            try:
                with open(self.persist_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event, sort_keys=True, default=str) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
            except OSError:
                pass  # flash-only; swallow write errors

    def _log(self, msg: str) -> None:
        """Debug helper (avoids import-level logger config)."""
        print(msg)


# ------------------------------------------------------------------
# Convenience: bridge existing audit events to sentinel subject
# ------------------------------------------------------------------

def bridge_audit_to_sentinel(
    bus: Any,
    node_id: str = "edge-sim-1",
) -> Callable[[dict], None]:
    """Return a callback that publishes local audit records on
    ``aspen.sentinel.audit.event``.

    Hook this into EdgeRRM's ``_record`` or subscribe to a local subject::

        rrm = EdgeRRM(...)
        bridge = bridge_audit_to_sentinel(rrm.bus)
        rrm.bus.subscribe(\"aspen.edge.sentinel.audit\", bridge)
    """

    def publish_audit(record: dict) -> None:
        bus.publish(
            AUDIT_EVENT,
            {
                "event": record.get("event", "unknown"),
                "node_id": node_id,
                "severity": record.get("severity", "info"),
                "payload": {k: v for k, v in record.items() if k not in ("event", "severity")},
            },
            source=f"sentinel-bridge/{node_id}",
        )

    return publish_audit
