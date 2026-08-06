import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aspen_edge import FleetBus, OpsManager, EdgeRRM
from aspen_edge.status_cli import evaluate_ops_status, format_report

bus = FleetBus()
ops = OpsManager(bus)
rrm = EdgeRRM("edge-1", bus)
rrm.start()
rrm.heartbeat()
# second node estop
rrm2 = EdgeRRM("edge-2", bus)
rrm2.start()
bus.publish("aspen.safety.estop", {"reason": "demo"}, source="t")
# estop is per-rrm subscription — rrm2 needs to be subscribed via start
rrm2.heartbeat()  # may still say online until it received estop — ensure both got it
# republish estop after both started
bus.publish("aspen.safety.estop", {"reason": "demo"}, source="t")
rrm.heartbeat()
rrm2.heartbeat()

# latest ops.status
ops_events = [e for e in bus.history if e["subject"] == "aspen.fleet.ops.status"]
payload = ops_events[-1]["data"]
st = evaluate_ops_status(payload)
print(format_report(st, who="robotics@lab"))
print("plant_status_demo ok safe=", st.to_dict()["safe"])
