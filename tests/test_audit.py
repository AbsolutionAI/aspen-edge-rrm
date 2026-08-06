import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aspen_edge.audit import AuditLog
from aspen_edge import FleetBus, EdgeRRM

class TestAudit(unittest.TestCase):
    def test_chain(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.jsonl"
            log = AuditLog(p)
            log.append("a", {"x": 1})
            log.append("b", {"y": 2})
            ok, msg = log.verify()
            self.assertTrue(ok, msg)
            # tamper
            text = p.read_text()
            p.write_text(text.replace('"x": 1', '"x": 99'))
            ok2, _ = log.verify()
            self.assertFalse(ok2)

    def test_rrm_persists(self):
        with tempfile.TemporaryDirectory() as d:
            bus = FleetBus()
            rrm = EdgeRRM("n1", bus, audit_path=str(Path(d)/"r.jsonl"))
            rrm.start()
            a = rrm.add_agent("m1")
            a.tick({"target": "p"})
            ok, msg = rrm.verify_audit()
            self.assertTrue(ok, msg)
            self.assertGreater(len(rrm._alog.tail()), 2)

if __name__ == "__main__":
    unittest.main()
