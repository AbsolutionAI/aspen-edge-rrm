"""H-016 / BEL-192 G8: dual-human authorize gate + RRM wiring tests."""
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aspen_edge import DualHumanGate, EdgeRRM, FleetBus, GateRefused, ProposeAct


def _rrm(**kw):
    bus = FleetBus()
    rrm = EdgeRRM(kw.pop("node_id", "n1"), bus,
                  audit_path=tempfile.mktemp(suffix="-gate-test.jsonl"), **kw)
    rrm.start()
    return rrm


def _last_pid(rrm):
    recs = [r for r in rrm.audit if r.get("proposal_id")]
    return recs[-1]["proposal_id"]


class TestGate(unittest.TestCase):
    def setUp(self):
        clock = {"t": 1000.0}
        self.clock = clock

    def test_refuse_single_principal(self):
        g = DualHumanGate(now=lambda: 1000.0)
        pid = g.propose("cell", "jog", "safety_adjacent", "op-alice")
        g.authorize(pid, "bob")
        with self.assertRaises(GateRefused) as cm:
            g.execute(pid, "runtime")
        self.assertEqual(cm.exception.reason, "insufficient_principals")

    def test_refuse_duplicate_principal(self):
        g = DualHumanGate(now=lambda: 1000.0)
        pid = g.propose("cell", "jog", "safety_adjacent", "op-alice")
        g.authorize(pid, "bob")
        with self.assertRaises(GateRefused) as cm:
            g.authorize(pid, "bob")
        self.assertEqual(cm.exception.reason, "duplicate_principal")

    def test_refuse_self_approval(self):
        g = DualHumanGate(now=lambda: 1000.0)
        pid = g.propose("cell", "jog", "safety_adjacent", "op-alice")
        with self.assertRaises(GateRefused) as cm:
            g.authorize(pid, "op-alice")
        self.assertEqual(cm.exception.reason, "self_approval")

    def test_refuse_expired(self):
        clock = {"t": 1000.0}
        g = DualHumanGate(now=lambda: clock["t"], window_s=600)
        pid = g.propose("cell", "jog", "safety_adjacent", "op-alice")
        g.authorize(pid, "bob")
        g.authorize(pid, "carol")
        clock["t"] += 601
        with self.assertRaises(GateRefused) as cm:
            g.execute(pid, "runtime")
        self.assertEqual(cm.exception.reason, "expired")

    def test_refuse_unknown_proposal_audited(self):
        events = []
        g = DualHumanGate(now=lambda: 1000.0, audit=lambda e, d: events.append((e, d)))
        with self.assertRaises(GateRefused):
            g.execute("nope", "runtime")
        self.assertIn(("refuse", {"proposal_id": "nope", "executor": "runtime",
                                  "reason": "unknown_proposal"}), events)

    def test_happy_path_two_distinct_principals(self):
        g = DualHumanGate(now=lambda: 1000.0)
        pid = g.propose("cell", "jog", "safety_adjacent", "op-alice")
        g.authorize(pid, "bob")
        g.authorize(pid, "carol")
        proof = g.execute(pid, "runtime")
        self.assertEqual(sorted(proof["principals_seen"]), ["bob", "carol"])

    def test_unknown_risk_class_fails_safe(self):
        g = DualHumanGate(now=lambda: 1000.0)
        self.assertEqual(g.normalize_risk(None), "safety_adjacent")
        self.assertEqual(g.normalize_risk("weird"), "safety_adjacent")
        self.assertEqual(g.normalize_risk("safe"), "safe")


class TestRRMGateWiring(unittest.TestCase):
    def test_safety_adjacent_holds_until_dual_auth(self):
        rrm = _rrm(operator_of_record="op-alice")
        a = rrm.add_agent("a1")
        a.tick({"target": "p"})  # move_to defaults to safety_adjacent
        pid = _last_pid(rrm)
        # act before authorizations must refuse
        r = rrm.request_act(pid)
        self.assertEqual(r["result"], "refused_insufficient_principals")
        # same human twice -> duplicate refused, still only 1 principal
        rrm.authorize(pid, "bob")
        with self.assertRaises(GateRefused):
            rrm.authorize(pid, "bob")
        # proposer operator cannot approve own proposal
        with self.assertRaises(GateRefused) as cm:
            rrm.authorize(pid, "op-alice")
        self.assertEqual(cm.exception.reason, "self_approval")
        # second distinct human -> enabled -> act executes
        rrm.authorize(pid, "carol")
        r = rrm.request_act(pid)
        self.assertEqual(r["result"], "executed_sim")

    def test_authorize_via_bus_subject(self):
        rrm = _rrm()
        a = rrm.add_agent("a1")
        p = ProposeAct(skill="jog_arm", args={}, agent_id="a1")
        rrm.handle_propose(p)
        pid = _last_pid(rrm)
        rrm.bus.publish(f"aspen.edge.{rrm.node_id}.authorize",
                        {"proposal_id": pid, "human_id": "bob"}, source="human/bob")
        rrm.bus.publish(f"aspen.edge.{rrm.node_id}.authorize",
                        {"proposal_id": pid, "human_id": "carol"}, source="human/carol")
        r = rrm.request_act(pid, executor="sim-runtime")
        self.assertEqual(r["result"], "executed_sim")
        ok, msg = rrm.verify_audit()
        self.assertTrue(ok, msg)

    def test_estop_still_blocks_before_gate(self):
        rrm = _rrm()
        a = rrm.add_agent("a1")
        rrm.bus.publish("aspen.safety.estop", {"reason": "x", "actor": "op-alice"}, source="t")
        a.tick({"target": "p"})
        self.assertTrue(any(x.get("result") == "refused_estop" for x in rrm.audit))

    def test_estop_clear_requires_dual_human(self):
        rrm = _rrm()
        rrm.add_agent("a1")
        rrm.bus.publish("aspen.safety.estop", {"reason": "x", "actor": "op-dave"}, source="t")
        self.assertTrue(rrm.estop)

        # bare clear message cannot unlatch
        rrm.bus.publish("aspen.safety.clear", {}, source="t")
        self.assertTrue(rrm.estop)
        self.assertTrue(any(x.get("event") == "clear_refused"
                            and x.get("reason") == "insufficient_principals"
                            for x in rrm.audit))

        # single authorization is not enough
        rrm.bus.publish("aspen.safety.authorize_clear", {"human_id": "bob"}, source="human/bob")
        rrm.bus.publish("aspen.safety.clear", {}, source="t")
        self.assertTrue(rrm.estop)

        # the stop-causer cannot authorize the clear
        rrm.bus.publish("aspen.safety.authorize_clear", {"human_id": "op-dave"},
                        source="human/op-dave")
        self.assertTrue(any(x.get("event") == "authorize_clear_refused"
                            and x.get("reason") == "self_approval" for x in rrm.audit))
        rrm.bus.publish("aspen.safety.clear", {}, source="t")
        self.assertTrue(rrm.estop)

        # second distinct human -> clear arms the cell
        rrm.bus.publish("aspen.safety.authorize_clear", {"human_id": "carol"},
                        source="human/carol")
        rrm.bus.publish("aspen.safety.clear", {}, source="t")
        self.assertFalse(rrm.estop)
        ok, msg = rrm.verify_audit()
        self.assertTrue(ok, msg)


if __name__ == "__main__":
    unittest.main()
