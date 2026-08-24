from __future__ import annotations
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .audit import AuditLog
from .fleet_bus import FleetBus
from .gate import (
    DualHumanGate,
    GateRefused,
    ENABLE_WINDOW_S,
    RISK_SAFE,
    RISK_SAFETY_ADJACENT,
)
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
    audit_path: str | None = None
    _alog: AuditLog | None = None
    # H-016 dual-human authorize gate
    operator_of_record: str = ""
    gate_window_s: float = field(
        default_factory=lambda: float(os.environ.get("ASPEN_GATE_WINDOW_S", ENABLE_WINDOW_S))
    )
    _gate: DualHumanGate | None = None
    _clear_authorizations: dict[str, float] = field(default_factory=dict)
    _estop_actor: str | None = None

    def __post_init__(self) -> None:
        path = self.audit_path or os.environ.get(
            "ASPEN_AUDIT_PATH", f"/tmp/aspen-audit-{self.node_id}.jsonl"
        )
        self._alog = AuditLog(Path(path))
        self._gate = DualHumanGate(
            window_s=self.gate_window_s,
            audit=self._gate_audit,
        )

    def _gate_audit(self, event: str, data: dict[str, Any]) -> None:
        self._record(f"gate.{event}", **data)

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
                "version": "0.3.0",
            },
            source=f"rrm/{self.node_id}",
        )
        self.bus.subscribe("aspen.safety.estop", self._on_estop)
        self.bus.subscribe("aspen.safety.authorize_clear", self._on_authorize_clear)
        self.bus.subscribe("aspen.safety.clear", self._on_clear)
        self.bus.subscribe(f"aspen.edge.{self.node_id}.authorize", self._on_authorize)
        self._record("rrm_start", node_id=self.node_id, plant=self.plant)

    def _on_estop(self, env: dict) -> None:
        self.estop = True
        d = env.get("data") or {}
        self._estop_actor = d.get("actor")
        self._clear_authorizations.clear()
        self._record("estop", data=d)

    def _on_authorize_clear(self, env: dict) -> None:
        """One distinct human principal authorizes the estop clear."""
        d = env.get("data") or {}
        human_id = d.get("human_id", "")
        if not self.estop:
            self._record("authorize_clear_refused",
                         human_id=human_id, reason="not_latched")
            return
        if self._estop_actor and human_id == self._estop_actor:
            self._record("authorize_clear_refused",
                         human_id=human_id, reason="self_approval")
            return
        if human_id in self._clear_authorizations:
            self._record("authorize_clear_refused",
                         human_id=human_id, reason="duplicate_principal")
            return
        self._clear_authorizations[human_id] = time.time()
        self._record("authorize_clear", human_id=human_id,
                     count=f"{len(self._clear_authorizations)}/2")

    def _on_clear(self, env: dict) -> None:
        """Execute the estop clear. Requires two distinct human principals;
        a bare clear message can never unlatch the cell."""
        d = env.get("data") or {}
        if not self.estop:
            self._record("clear_refused", reason="not_latched", **d)
            return
        authorizers = sorted(self._clear_authorizations)
        if len(authorizers) < 2:
            self._record("clear_refused", reason="insufficient_principals",
                         authorizers=authorizers, **d)
            return
        self.estop = False
        self._record("clear", authorizers=authorizers, decision="armed", **d)
        self._clear_authorizations.clear()
        self._estop_actor = None

    def _on_authorize(self, env: dict) -> None:
        d = env.get("data") or {}
        try:
            self.authorize(d.get("proposal_id", ""), d.get("human_id", ""),
                           note=d.get("note", ""))
        except GateRefused:
            pass  # refusal already audited by the gate

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
        risk = self._gate.normalize_risk(p.risk_class)  # type: ignore[union-attr]
        if risk == RISK_SAFETY_ADJACENT:
            pid = self._gate.propose(  # type: ignore[union-attr]
                subject=self.node_id, action=p.skill, risk_class=risk,
                proposer_operator=self.operator_of_record or f"agent:{p.agent_id}",
            )
            return self._record("propose_act", result="held_dual_auth",
                                proposal_id=pid, risk_class=risk, **base)
        self.bus.publish(
            f"aspen.edge.{self.node_id}.propose_act",
            {"skill": p.skill, "args": p.args, "agent_id": p.agent_id},
            source=f"rrm/{self.node_id}",
        )
        return self._record("propose_act", result="accepted_sim", **base)

    def authorize(self, proposal_id: str, human_id: str, note: str = "") -> dict:
        """Record one human authorization for a held safety_adjacent proposal."""
        assert self._gate is not None
        return self._gate.authorize(proposal_id, human_id, note=note)

    def request_act(self, proposal_id: str, executor: str = "runtime") -> dict:
        """propose_act -> act transition. Verifies the two-principal record
        immediately before act; every refusal is audited."""
        assert self._gate is not None
        base = {"proposal_id": proposal_id, "executor": executor}
        try:
            proof = self._gate.execute(proposal_id, executor)
        except GateRefused as e:
            return self._record("act", result=f"refused_{e.reason}", **base)
        return self._record("act", result="executed_sim", **proof)

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
