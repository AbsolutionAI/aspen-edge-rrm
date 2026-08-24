"""Ops-manager + fake edge RRM + micro-agent + estop — in-process E2E (BEL-182)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aspen_edge import FleetBus, OpsManager, EdgeRRM

bus = FleetBus()
ops = OpsManager(bus)
rrm = EdgeRRM(node_id="edge-sim-1", bus=bus, plant="plant-edge", caps=["mock_cobot"])
rrm.start()
agent = rrm.add_agent("micro-1")
rrm.heartbeat()
assert "edge-sim-1" in ops.nodes
assert ops.nodes["edge-sim-1"].get("status") in ("online", "registered", "ok")

# H-016: default risk_class is safety_adjacent -> holds until dual human authz
p1 = agent.tick({"target": "pose_home"})
held = next(a for a in rrm.audit if a.get("result") == "held_dual_auth")
bus.publish(f"aspen.edge.{rrm.node_id}.authorize",
            {"proposal_id": held["proposal_id"], "human_id": "op-b"}, source="human/op-b")
bus.publish(f"aspen.edge.{rrm.node_id}.authorize",
            {"proposal_id": held["proposal_id"], "human_id": "op-c"}, source="human/op-c")
assert rrm.request_act(held["proposal_id"])["result"] == "executed_sim"
# explicit safe proposals bypass the gate
agent.tick({"target": "pose_home", "note": "mock"}, risk_class="safe")
assert any(a.get("result") == "accepted_sim" for a in rrm.audit)

bus.publish("aspen.safety.estop", {"reason": "test", "source": "operator", "actor": "op-a"},
            source="safety")
assert rrm.estop is True
agent.tick({"target": "pose_a"})
assert any(a.get("result") == "refused_estop" for a in rrm.audit)

# estop clear requires two distinct humans; bare clear cannot unlatch
bus.publish("aspen.safety.clear", {"source": "operator"}, source="safety")
assert rrm.estop is True
bus.publish("aspen.safety.authorize_clear", {"human_id": "op-b"}, source="human/op-b")
bus.publish("aspen.safety.authorize_clear", {"human_id": "op-c"}, source="human/op-c")
bus.publish("aspen.safety.clear", {"source": "operator"}, source="safety")
assert rrm.estop is False
rrm.heartbeat()
status_events = [e for e in bus.history if e["subject"] == "aspen.fleet.ops.status"]
assert status_events, "ops.status not published"
print("fleet_e2e ok")
print("nodes", list(ops.nodes.keys()))
print("ops.status count", len(status_events))
print("audit", len(rrm.audit))
