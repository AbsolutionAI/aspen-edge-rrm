from __future__ import annotations
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

Handler = Callable[[dict], None]

@dataclass
class FleetBus:
    """In-process stand-in for NATS subjects (ADR-0003)."""
    _subs: dict[str, list[Handler]] = field(default_factory=lambda: defaultdict(list))
    history: list[dict] = field(default_factory=list)

    def publish(self, subject: str, data: dict, source: str = "edge") -> dict:
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
        for h in list(self._subs.get(subject, [])):
            h(env)
        return env

    def subscribe(self, subject: str, handler: Handler) -> None:
        self._subs[subject].append(handler)


@dataclass
class OpsManager:
    bus: FleetBus
    nodes: dict[str, dict] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.bus.subscribe("aspen.fleet.node.register", self._on_register)
        self.bus.subscribe("aspen.fleet.node.heartbeat", self._on_hb)

    def _on_register(self, env: dict) -> None:
        d = env["data"]
        self.nodes[d["node_id"]] = {**d, "last_hb": None, "status": "registered"}

    def _on_hb(self, env: dict) -> None:
        d = env["data"]
        nid = d["node_id"]
        if nid not in self.nodes:
            self.nodes[nid] = {"node_id": nid}
        self.nodes[nid].update(d)
        self.nodes[nid]["last_hb"] = env["time"]
        self.nodes[nid]["status"] = d.get("status", "online")
        self.publish_status()

    def publish_status(self) -> dict:
        degraded = [n for n, v in self.nodes.items() if v.get("status") not in ("online", "registered", "ok")]
        return self.bus.publish(
            "aspen.fleet.ops.status",
            {"nodes": list(self.nodes.values()), "degraded": degraded, "count": len(self.nodes)},
            source="ops-manager",
        )
