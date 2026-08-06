from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable

@dataclass
class ProposeAct:
    skill: str
    args: dict
    agent_id: str

class MicroAgent:
    """Sense → decide → propose_act only."""

    def __init__(self, agent_id: str, propose: Callable[[ProposeAct], Any]):
        self.agent_id = agent_id
        self._propose = propose
        self.alive = True

    def tick(self, sense: dict) -> ProposeAct | None:
        if not self.alive:
            return None
        # trivial policy: if target present, propose move
        if sense.get("target"):
            p = ProposeAct(skill="move_to", args={"target": sense["target"]}, agent_id=self.agent_id)
            self._propose(p)
            return p
        return None
