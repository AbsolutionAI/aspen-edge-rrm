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

class TestEstopDualHumanClear(unittest.TestCase):
    """Integration tests for estop dual-human clear gate (H-007, ADR-0003)."""

    def test_clear_alone_never_unlatches(self):
        """bare `aspen.safety.clear` with zero authorize_clear must not unlatch."""
        bus = FleetBus()
        rrm = EdgeRRM("n1", bus)
        rrm.start()
        bus.publish("aspen.safety.estop", {"reason": "test", "source": "h-001"}, source="safety")
        self.assertTrue(rrm.estop)
        bus.publish("aspen.safety.clear", {"source": "operator"}, source="safety")
        self.assertTrue(rrm.estop, "clear alone must not unlatch estop")
        refused = [e for e in rrm.audit if e["event"] == "clear_refused_insufficient_auths"]
        self.assertEqual(len(refused), 1)

    def test_single_auth_never_unlatches(self):
        """one authorize_clear + clear must not unlatch estop."""
        bus = FleetBus()
        rrm = EdgeRRM("n1", bus)
        rrm.start()
        bus.publish("aspen.safety.estop", {"reason": "test", "source": "h-001"}, source="safety")
        bus.publish("aspen.safety.authorize_clear", {"human_id": "h-001"}, source="safety")
        bus.publish("aspen.safety.clear", {"source": "operator"}, source="safety")
        self.assertTrue(rrm.estop, "single auth must not unlatch estop")
        refused = [e for e in rrm.audit if e["event"] == "clear_refused_insufficient_auths"]
        self.assertEqual(len(refused), 1)

    def test_dual_auth_then_clear_unlatches(self):
        """two distinct authorize_clear + clear must unlatch estop."""
        bus = FleetBus()
        rrm = EdgeRRM("n1", bus)
        rrm.start()
        bus.publish("aspen.safety.estop", {"reason": "test", "source": "h-001"}, source="safety")
        bus.publish("aspen.safety.authorize_clear", {"human_id": "h-001"}, source="safety")
        bus.publish("aspen.safety.authorize_clear", {"human_id": "h-002"}, source="safety")
        bus.publish("aspen.safety.clear", {"source": "operator"}, source="safety")
        self.assertFalse(rrm.estop, "dual auth + clear must unlatch estop")
        events = [e["event"] for e in rrm.audit]
        self.assertIn("clear", events)
        self.assertNotIn("clear_refused_insufficient_auths", events)

    def test_same_human_twice_equals_one(self):
        """same human_id authorizing twice must count as one distinct auth."""
        bus = FleetBus()
        rrm = EdgeRRM("n1", bus)
        rrm.start()
        bus.publish("aspen.safety.estop", {"reason": "test", "source": "h-001"}, source="safety")
        bus.publish("aspen.safety.authorize_clear", {"human_id": "h-001"}, source="safety")
        bus.publish("aspen.safety.authorize_clear", {"human_id": "h-001"}, source="safety")
        bus.publish("aspen.safety.clear", {"source": "operator"}, source="safety")
        self.assertTrue(rrm.estop, "same human twice must not count as two distinct auths")
        refused = [e for e in rrm.audit if e["event"] == "clear_refused_insufficient_auths"]
        self.assertEqual(len(refused), 1)

    def test_estop_resets_clear_auths(self):
        """a new estop must clear the authorize_clear set."""
        bus = FleetBus()
        rrm = EdgeRRM("n1", bus)
        rrm.start()
        bus.publish("aspen.safety.estop", {"reason": "test", "source": "h-001"}, source="safety")
        bus.publish("aspen.safety.authorize_clear", {"human_id": "h-001"}, source="safety")
        bus.publish("aspen.safety.authorize_clear", {"human_id": "h-002"}, source="safety")
        bus.publish("aspen.safety.clear", {"source": "operator"}, source="safety")
        self.assertFalse(rrm.estop)
        # Another estop
        bus.publish("aspen.safety.estop", {"reason": "new", "source": "h-001"}, source="safety")
        self.assertTrue(rrm.estop)
        # Authorize set was cleared by the estop
        bus.publish("aspen.safety.clear", {"source": "operator"}, source="safety")
        self.assertTrue(rrm.estop, "estop must reset auth set; clear alone must not unlatch")
        refused = [e for e in rrm.audit if e["event"] == "clear_refused_insufficient_auths"]
        self.assertEqual(len(refused), 1)

    def test_audit_records_authorize_clear(self):
        """each authorize_clear must produce an audit record with human_id."""
        bus = FleetBus()
        rrm = EdgeRRM("n1", bus)
        rrm.start()
        bus.publish("aspen.safety.estop", {"reason": "test", "source": "h-001"}, source="safety")
        bus.publish("aspen.safety.authorize_clear", {"human_id": "h-001"}, source="safety")
        auths = [e for e in rrm.audit if e["event"] == "authorize_clear"]
        self.assertEqual(len(auths), 1)
        self.assertEqual(auths[0]["human_id"], "h-001")
        self.assertEqual(auths[0]["auth_count"], 1)
        bus.publish("aspen.safety.authorize_clear", {"human_id": "h-002"}, source="safety")
        auths = [e for e in rrm.audit if e["event"] == "authorize_clear"]
        self.assertEqual(len(auths), 2)
        self.assertEqual(auths[1]["human_id"], "h-002")
        self.assertEqual(auths[1]["auth_count"], 2)


if __name__ == "__main__":
    unittest.main()
