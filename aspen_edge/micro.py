from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable

from .gate import RISK_SAFETY_ADJACENT

@dataclass
class ProposeAct:
    skill: str
    args: dict
    agent_id: str
    risk_class: str = RISK_SAFETY_ADJACENT  # fail-safe: unknown -> safety_adjacent

class MicroAgent:
    """Sense → decide → propose_act only."""

    def __init__(self, agent_id: str, propose: Callable[[ProposeAct], Any]):
        self.agent_id = agent_id
        self._propose = propose
        self.alive = True

    def tick(self, sense: dict, risk_class: str = RISK_SAFETY_ADJACENT) -> ProposeAct | None:
        if not self.alive:
            return None
        # trivial policy: if target present, propose move
        if sense.get("target"):
            p = ProposeAct(skill="move_to", args={"target": sense["target"]},
                           agent_id=self.agent_id, risk_class=risk_class)
            self._propose(p)
            return p
        return None
