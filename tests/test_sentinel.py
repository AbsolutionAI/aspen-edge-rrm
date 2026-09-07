"""Tests for the Sentinel consumer (ASP-566)."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aspen_edge import FleetBus
from aspen_edge.sentinel import (
    AUDIT_EVENT,
    FLEET_OVERVIEW,
    SentinelConsumer,
    bridge_audit_to_sentinel,
)


class TestSentinelConsumer(unittest.TestCase):
    def _make(self, **kw):
        bus = FleetBus()
        sentinel = SentinelConsumer(bus, **kw)
        sentinel.start()
        return bus, sentinel

    def test_subscribes_to_sentinel_subjects(self):
        _, sentinel = self._make()
        self.assertIn(AUDIT_EVENT, sentinel.subjects)
        self.assertIn(FLEET_OVERVIEW, sentinel.subjects)

    def test_collects_audit_events(self):
        bus, sentinel = self._make()
        bus.publish(
            AUDIT_EVENT,
            {"event": "propose_act", "node_id": "edge-sim-1", "payload": {"skill": "move_to"}},
            source="rrm/edge-sim-1",
        )
        bus.publish(
            AUDIT_EVENT,
            {"event": "estop", "node_id": "edge-sim-1", "payload": {"reason": "test"}},
            source="safety",
        )
        self.assertEqual(sentinel.count(), 2)
        self.assertEqual(sentinel.tail(1)[0]["event"], "estop")

    def test_by_type_filter(self):
        bus, sentinel = self._make()
        for _ in range(3):
            bus.publish(AUDIT_EVENT, {"event": "heartbeat"}, source="rrm/n1")
        bus.publish(AUDIT_EVENT, {"event": "estop"}, source="safety")
        hb = sentinel.by_type("heartbeat")
        self.assertEqual(len(hb), 3)
        self.assertEqual(len(sentinel.by_type("estop")), 1)

    def test_search_substring(self):
        bus, sentinel = self._make()
        bus.publish(AUDIT_EVENT, {"event": "clear", "payload": {"human_id": "alice"}}, source="safety")
        bus.publish(AUDIT_EVENT, {"event": "agent_add", "payload": {"agent_id": "micro-7"}}, source="rrm/n1")
        found = sentinel.search("micro-7")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["event"], "agent_add")
        self.assertEqual(len(sentinel.search("nobody")), 0)

    def test_by_time_range(self):
        bus, sentinel = self._make()
        t0 = time.time()
        bus.publish(AUDIT_EVENT, {"event": "a"}, source="rrm/n1")
        time.sleep(0.01)
        bus.publish(AUDIT_EVENT, {"event": "b"}, source="rrm/n1")
        t1 = time.time()
        got = sentinel.by_time(t0, t1)
        self.assertGreaterEqual(len(got), 2)

    def test_ring_buffer_trims(self):
        bus, sentinel = self._make(max_events=5)
        for i in range(10):
            bus.publish(AUDIT_EVENT, {"event": f"evt{i}"}, source="rrm/n1")
        self.assertEqual(sentinel.count(), 5)
        self.assertEqual(sentinel.tail(1)[0]["event"], "evt9")

    def test_persist_path_writes_jsonl(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sentinel.jsonl"
            bus, sentinel = self._make(persist_path=str(p))
            bus.publish(AUDIT_EVENT, {"event": "estop", "payload": {"reason": "x"}}, source="safety")
            self.assertTrue(p.exists())
            lines = p.read_text().strip().splitlines()
            self.assertEqual(len(lines), 1)
            rec = json.loads(lines[0])
            self.assertEqual(rec["event"], "estop")
            self.assertEqual(rec["subject"], AUDIT_EVENT)

    def test_fleet_overview_collected(self):
        bus, sentinel = self._make()
        bus.publish(FLEET_OVERVIEW, {"nodes": 2, "degraded": []}, source="ops-manager")
        self.assertEqual(sentinel.count(), 1)
        self.assertEqual(sentinel.tail(1)[0]["event"], "fleet_overview")

    def test_bridge_publishes_on_sentinel_subject(self):
        bus, sentinel = self._make()
        bridge = bridge_audit_to_sentinel(bus, node_id="edge-sim-1")
        bridge({"event": "estop", "severity": "critical", "reason": "test"})
        events = sentinel.by_type("estop")
        self.assertEqual(len(events), 1)
        payload = events[0]["data"]["payload"]
        self.assertEqual(payload["reason"], "test")
        self.assertEqual(events[0]["data"]["node_id"], "edge-sim-1")


if __name__ == "__main__":
    unittest.main()
