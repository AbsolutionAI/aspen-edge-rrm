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

agent.tick({"target": "pose_home"})
assert any(a.get("result") == "accepted_sim" for a in rrm.audit)

bus.publish("aspen.safety.estop", {"reason": "test", "source": "operator"}, source="safety")
assert rrm.estop is True
agent.tick({"target": "pose_a"})
assert any(a.get("result") == "refused_estop" for a in rrm.audit)

bus.publish("aspen.safety.clear", {"source": "operator"}, source="safety")
rrm.heartbeat()
status_events = [e for e in bus.history if e["subject"] == "aspen.fleet.ops.status"]
assert status_events, "ops.status not published"
print("fleet_e2e ok")
print("nodes", list(ops.nodes.keys()))
print("ops.status count", len(status_events))
print("audit", len(rrm.audit))
