import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aspen_edge import FleetBus, OpsManager, EdgeRRM

class TestRRM(unittest.TestCase):
    def test_register_and_hb(self):
        bus = FleetBus()
        ops = OpsManager(bus)
        rrm = EdgeRRM("n1", bus)
        rrm.start()
        rrm.heartbeat()
        self.assertIn("n1", ops.nodes)

    def test_estop_blocks(self):
        bus = FleetBus()
        rrm = EdgeRRM("n1", bus)
        rrm.start()
        a = rrm.add_agent("a1")
        bus.publish("aspen.safety.estop", {"reason": "x"}, source="t")
        r = a.tick({"target": "p"})
        self.assertTrue(any(x.get("result") == "refused_estop" for x in rrm.audit))

if __name__ == "__main__":
    unittest.main()
