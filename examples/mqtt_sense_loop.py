"""MQTT-first sense → micro-agent propose (in-memory broker)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aspen_edge import FleetBus, EdgeRRM, MQTTEdgeAdapter

bus = FleetBus()
rrm = EdgeRRM(node_id="edge-mqtt-1", bus=bus, caps=["mock_cobot", "mqtt_sensor"])
rrm.start()
mqtt = MQTTEdgeAdapter(node_id="edge-mqtt-1")
agent = rrm.add_agent("micro-mqtt")

mqtt.publish_sensor("target", "pose_home")
sense = mqtt.sense()
assert sense.get("target") == "pose_home"
agent.tick(sense)
assert any(a.get("result") == "accepted_sim" for a in rrm.audit)
# driver side would listen command topic
mqtt.publish_command("move_to", {"target": "pose_home"})
assert any(t.endswith("/command") for t, _ in mqtt.client.messages)
print("mqtt_sense_loop ok")
