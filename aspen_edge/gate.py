"""Dual-human authorize gate for propose_act -> act (H-016 / BEL-192 G8).

Safety-adjacent proposals hold at propose_act until two distinct human
principals authorize. The act transition verifies the two-principal record
and the enable window immediately before execution.

Spec: aspen-os docs/plans/ASP-364-dual-human-wire.md and
docs/plans/BEL-192-phase-d-physical-cell-gate.md.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Callable

ENABLE_WINDOW_S = 600.0

RISK_SAFE = "safe"
RISK_SAFETY_ADJACENT = "safety_adjacent"


class GateRefused(Exception):
    """Refusal with a stable contract reason string."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


class DualHumanGate:
    """Two-principal hold-to-enable state machine.

    Audit events emitted via ``audit(event, data)`` callback:
        propose_act   — proposal recorded (held if safety_adjacent)
        refuse        — must-fail case hit (carries reason)
        authorize     — one human authorization recorded (n/2)
        enable_act    — two distinct principals present; window open
        execute_act   — act allowed after immediate re-verification
    """

    def __init__(
        self,
        now: Callable[[], float] | None = None,
        window_s: float = ENABLE_WINDOW_S,
        audit: Callable[[str, dict], None] | None = None,
    ) -> None:
        self.now = now or time.time
        self.window_s = window_s
        self._audit_sink = audit
        self.proposals: dict[str, dict[str, Any]] = {}
        self.approvals: dict[str, dict[str, float]] = {}
        self.enabled_until: dict[str, float] = {}

    def _audit(self, event: str, data: dict[str, Any]) -> None:
        if self._audit_sink:
            self._audit_sink(event, data)

    def _principals(self, proposal_id: str) -> list[str]:
        return sorted(self.approvals.get(proposal_id, {}))

    @staticmethod
    def normalize_risk(risk_class: str | None) -> str:
        """Unknown/missing risk classes fail safe to safety_adjacent."""
        return RISK_SAFETY_ADJACENT if risk_class != RISK_SAFE else RISK_SAFE

    def propose(
        self,
        subject: str,
        action: str,
        risk_class: str | None,
        proposer_operator: str,
    ) -> str:
        risk = self.normalize_risk(risk_class)
        pid = str(uuid.uuid4())
        self.proposals[pid] = {
            "subject": subject,
            "action": action,
            "risk_class": risk,
            "proposer_operator": proposer_operator,
            "expires_at": self.now() + self.window_s,
        }
        self.approvals[pid] = {}
        self._audit("propose_act", {
            "proposal_id": pid,
            "subject": subject,
            "action": action,
            "risk_class": risk,
            "proposer_operator": proposer_operator,
            "decision": "held" if risk == RISK_SAFETY_ADJACENT else "auto_safe",
        })
        return pid

    def held(self, proposal_id: str) -> bool:
        p = self.proposals.get(proposal_id)
        return bool(p and p["risk_class"] == RISK_SAFETY_ADJACENT)

    def enabled(self, proposal_id: str) -> bool:
        until = self.enabled_until.get(proposal_id)
        return until is not None and self.now() <= until

    def authorize(self, proposal_id: str, human_id: str, note: str = "") -> dict:
        p = self.proposals.get(proposal_id)
        if p is None:
            data = {"proposal_id": proposal_id, "human_id": human_id, "reason": "unknown_proposal"}
            self._audit("refuse", data)
            raise GateRefused("unknown_proposal", f"no such proposal {proposal_id}")
        approvals = self.approvals[proposal_id]
        if human_id == p["proposer_operator"]:
            data = {"proposal_id": proposal_id, "human_id": human_id, "reason": "self_approval"}
            self._audit("refuse", data)
            raise GateRefused("self_approval", f"human {human_id} is proposer operator-of-record")
        if human_id in approvals:
            data = {"proposal_id": proposal_id, "human_id": human_id, "reason": "duplicate_principal"}
            self._audit("refuse", data)
            raise GateRefused("duplicate_principal", f"human {human_id} already authorized")
        approvals[human_id] = self.now()
        count = len(approvals)
        data = {
            "proposal_id": proposal_id,
            "human_id": human_id,
            "count": count,
            "note": note,
            "principals_seen": self._principals(proposal_id),
        }
        self._audit("authorize", data)
        if count >= 2:
            self.enabled_until[proposal_id] = self.now() + self.window_s
            self._audit("enable_act", {
                "proposal_id": proposal_id,
                "principals_seen": self._principals(proposal_id),
                "window_s": self.window_s,
            })
        return data

    def execute(self, proposal_id: str, executor: str) -> dict:
        """Verify dual authorization immediately before act. Raises GateRefused."""
        p = self.proposals.get(proposal_id)
        if p is None:
            data = {"proposal_id": proposal_id, "executor": executor, "reason": "unknown_proposal"}
            self._audit("refuse", data)
            raise GateRefused("unknown_proposal", f"no such proposal {proposal_id}")
        principals = self._principals(proposal_id)
        if len(principals) < 2:
            data = {"proposal_id": proposal_id, "executor": executor,
                    "reason": "insufficient_principals", "principals_seen": principals}
            self._audit("refuse", data)
            raise GateRefused("insufficient_principals", f"got {len(principals)}/2 principals")
        if not self.enabled(proposal_id):
            data = {"proposal_id": proposal_id, "executor": executor,
                    "reason": "expired", "principals_seen": principals}
            self._audit("refuse", data)
            raise GateRefused("expired", "enablement window closed")
        data = {
            "proposal_id": proposal_id,
            "executor": executor,
            "subject": p["subject"],
            "action": p["action"],
            "principals_seen": principals,
        }
        self._audit("execute_act", data)
        return data
