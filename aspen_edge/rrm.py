from __future__ import annotations
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from .audit import AuditLog
from .fleet_bus import FleetBus
from .micro import MicroAgent, ProposeAct

CLEAR_AUTH_WINDOW = 300  # 5-minute window for authorize_clear


@dataclass
class EdgeRRM:
    node_id: str
    bus: FleetBus
    plant: str = "plant-edge"
    caps: list[str] = field(default_factory=lambda: ["mock_cobot"])
    max_agents: int = 4
    estop: bool = False
    audit: list[dict] = field(default_factory=list)
    agents: dict[str, MicroAgent] = field(default_factory=dict)
    offline_queue: list[ProposeAct] = field(default_factory=list)
    bus_up: bool = True
    audit_path: str | None = None
    _alog: AuditLog | None = None
    _clear_auths: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        path = self.audit_path or os.environ.get(
            "ASPEN_AUDIT_PATH", f"/tmp/aspen-audit-{self.node_id}.jsonl"
        )
        self._alog = AuditLog(Path(path))

    def _record(self, event: str, **data: Any) -> dict:
        rec = {"ts": time.time(), "event": event, **data}
        self.audit.append(rec)
        if self._alog:
            chained = self._alog.append(event, {k: v for k, v in data.items()})
            rec["hash"] = chained.get("hash")
        return rec

    def start(self) -> None:
        self.bus.publish(
            "aspen.fleet.node.register",
            {
                "node_id": self.node_id,
                "plant": self.plant,
                "roles": ["edge-rrm"],
                "caps": self.caps,
                "version": "0.2.0",
            },
            source=f"rrm/{self.node_id}",
        )
        self.bus.subscribe("aspen.safety.estop", self._on_estop)
        self.bus.subscribe("aspen.safety.authorize_clear", self._on_authorize_clear)
        self.bus.subscribe("aspen.safety.clear", self._on_clear)
        self._record("rrm_start", node_id=self.node_id, plant=self.plant)

    def _on_estop(self, env: dict) -> None:
        self.estop = True
        self._clear_auths.clear()
        self._record("estop", data=env.get("data"))

    def _prune_clear_auths(self) -> None:
        now = time.time()
        self._clear_auths = {h: t for h, t in self._clear_auths.items() if now - t <= CLEAR_AUTH_WINDOW}

    def _on_authorize_clear(self, env: dict) -> None:
        data = env.get("data", {})
        human_id = data.get("human_id")
        if not human_id:
            return
        self._prune_clear_auths()
        self._clear_auths[human_id] = time.time()
        self._record("authorize_clear", human_id=human_id, auth_count=len(self._clear_auths))

    def _on_clear(self, env: dict) -> None:
        self._prune_clear_auths()
        if len(self._clear_auths) < 2:
            self._record("clear_refused_insufficient_auths", auth_count=len(self._clear_auths))
            return
        self.estop = False
        self._clear_auths.clear()
        self._record("clear", data=env.get("data"))

    def add_agent(self, agent_id: str) -> MicroAgent:
        if len(self.agents) >= self.max_agents:
            raise RuntimeError("max_agents")
        agent = MicroAgent(agent_id, propose=self.handle_propose)
        self.agents[agent_id] = agent
        self._record("agent_add", agent_id=agent_id)
        return agent

    def handle_propose(self, p: ProposeAct) -> dict[str, Any]:
        base = {"skill": p.skill, "args": p.args, "agent": p.agent_id}
        if self.estop:
            return self._record("propose_act", result="refused_estop", **base)
        if not self.bus_up:
            self.offline_queue.append(p)
            return self._record("propose_act", result="queued_offline", **base)
        self.bus.publish(
            f"aspen.edge.{self.node_id}.propose_act",
            {"skill": p.skill, "args": p.args, "agent_id": p.agent_id},
            source=f"rrm/{self.node_id}",
        )
        return self._record("propose_act", result="accepted_sim", **base)

    def heartbeat(self) -> dict:
        payload = {
            "node_id": self.node_id,
            "plant": self.plant,
            "status": "estop" if self.estop else "online",
            "resource": {"agents": len(self.agents), "queue": len(self.offline_queue)},
            "agents": list(self.agents.keys()),
            "caps": self.caps,
        }
        return self.bus.publish(
            "aspen.fleet.node.heartbeat", payload, source=f"rrm/{self.node_id}"
        )

    def verify_audit(self) -> tuple[bool, str]:
        if not self._alog:
            return True, "no-log"
        return self._alog.verify()
