from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Any

from .fleet_bus import FleetBus
from .micro import MicroAgent, ProposeAct

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

    def start(self) -> None:
        self.bus.publish(
            "aspen.fleet.node.register",
            {"node_id": self.node_id, "plant": self.plant, "roles": ["edge-rrm"], "caps": self.caps, "version": "0.1.0"},
            source=f"rrm/{self.node_id}",
        )
        self.bus.subscribe("aspen.safety.estop", self._on_estop)
        self.bus.subscribe("aspen.safety.clear", self._on_clear)

    def _on_estop(self, env: dict) -> None:
        self.estop = True
        self.audit.append({"ts": time.time(), "event": "estop", "data": env.get("data")})

    def _on_clear(self, env: dict) -> None:
        self.estop = False
        self.audit.append({"ts": time.time(), "event": "clear", "data": env.get("data")})

    def add_agent(self, agent_id: str) -> MicroAgent:
        if len(self.agents) >= self.max_agents:
            raise RuntimeError("max_agents")
        agent = MicroAgent(agent_id, propose=self.handle_propose)
        self.agents[agent_id] = agent
        return agent

    def handle_propose(self, p: ProposeAct) -> dict[str, Any]:
        rec = {"ts": time.time(), "event": "propose_act", "skill": p.skill, "args": p.args, "agent": p.agent_id}
        if self.estop:
            rec["result"] = "refused_estop"
            self.audit.append(rec)
            return rec
        if not self.bus_up:
            self.offline_queue.append(p)
            rec["result"] = "queued_offline"
            self.audit.append(rec)
            return rec
        # mediate: publish proposal; driver would execute — lab records only
        self.bus.publish(
            f"aspen.edge.{self.node_id}.propose_act",
            {"skill": p.skill, "args": p.args, "agent_id": p.agent_id},
            source=f"rrm/{self.node_id}",
        )
        rec["result"] = "accepted_sim"
        self.audit.append(rec)
        return rec

    def heartbeat(self) -> dict:
        payload = {
            "node_id": self.node_id,
            "plant": self.plant,
            "status": "estop" if self.estop else "online",
            "resource": {"agents": len(self.agents), "queue": len(self.offline_queue)},
            "agents": list(self.agents.keys()),
            "caps": self.caps,
        }
        return self.bus.publish("aspen.fleet.node.heartbeat", payload, source=f"rrm/{self.node_id}")
