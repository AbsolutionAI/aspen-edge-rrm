"""Optional NATS backend with same publish/subscribe surface as FleetBus."""
from __future__ import annotations
import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

Handler = Callable[[dict], None]


@dataclass
class NatsFleetBus:
    """Async NATS bus; use run() helpers from sync code."""

    servers: str = field(default_factory=lambda: os.environ.get("ASPEN_NATS_URL", "nats://127.0.0.1:4222"))
    history: list[dict] = field(default_factory=list)
    _nc: Any = None
    _subs: list = field(default_factory=list)
    _handlers: dict = field(default_factory=dict)

    async def connect(self) -> None:
        import nats
        self._nc = await nats.connect(self.servers)

    async def close(self) -> None:
        if self._nc:
            await self._nc.drain()
            self._nc = None

    async def publish(self, subject: str, data: dict, source: str = "edge") -> dict:
        env = {
            "id": str(uuid.uuid4()),
            "source": source,
            "type": subject,
            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "specversion": "1.0",
            "data": data,
            "subject": subject,
        }
        self.history.append(env)
        assert self._nc is not None
        await self._nc.publish(subject, json.dumps(env).encode())
        return env

    async def subscribe(self, subject: str, handler: Handler) -> None:
        assert self._nc is not None

        async def _cb(msg):
            env = json.loads(msg.data.decode())
            handler(env)

        sub = await self._nc.subscribe(subject, cb=_cb)
        self._subs.append(sub)


def nats_available() -> bool:
    try:
        import nats  # noqa: F401
        return True
    except ImportError:
        return False
