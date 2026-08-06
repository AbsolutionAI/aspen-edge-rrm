import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aspen_edge.mqtt_adapter import MQTTEdgeAdapter
from aspen_edge.status_cli import evaluate_ops_status

class TestMqttStatus(unittest.TestCase):
    def test_sensor(self):
        m = MQTTEdgeAdapter("n1")
        m.publish_sensor("temp", 21.5)
        self.assertEqual(m.sense()["temp"], 21.5)

    def test_status_estop(self):
        st = evaluate_ops_status({
            "nodes": [{"node_id": "a", "status": "online"}, {"node_id": "b", "status": "estop"}],
            "degraded": [],
        })
        self.assertIn("b", st.estop)
        self.assertFalse(st.to_dict()["safe"])

if __name__ == "__main__":
    unittest.main()
