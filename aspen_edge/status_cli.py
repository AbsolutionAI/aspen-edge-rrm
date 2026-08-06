"""BEL-184/116 — five-minute plant status from ops snapshots."""
from __future__ import annotations
import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any


@dataclass
class PlantStatus:
    node_count: int
    online: list[str]
    degraded: list[str]
    estop: list[str]
    summary: str

    def to_dict(self) -> dict:
        return {
            "node_count": self.node_count,
            "online": self.online,
            "degraded": self.degraded,
            "estop": self.estop,
            "summary": self.summary,
            "safe": len(self.estop) == 0 and len(self.degraded) == 0,
        }


def evaluate_ops_status(payload: dict) -> PlantStatus:
    nodes = payload.get("nodes") or []
    degraded = list(payload.get("degraded") or [])
    online, estop = [], []
    for n in nodes:
        if isinstance(n, dict):
            nid = n.get("node_id", "?")
            st = (n.get("status") or "").lower()
            if st == "estop":
                estop.append(nid)
            elif st in ("online", "ok", "registered"):
                online.append(nid)
            elif nid not in degraded:
                degraded.append(nid)
        else:
            online.append(str(n))
    if estop:
        summary = f"UNSAFE: estop on {', '.join(estop)}"
    elif degraded:
        summary = f"DEGRADED: {', '.join(degraded)}"
    elif online:
        summary = f"OK: {len(online)} node(s) online"
    else:
        summary = "UNKNOWN: no nodes reporting"
    return PlantStatus(len(nodes), online, degraded, estop, summary)


def format_report(st: PlantStatus, who: str | None = None) -> str:
    lines = [
        "=== Aspen plant status (<5 min) ===",
        st.summary,
        f"nodes: {st.node_count}",
        f"online: {', '.join(st.online) or '-'}",
        f"degraded: {', '.join(st.degraded) or '-'}",
        f"estop: {', '.join(st.estop) or '-'}",
        f"safe: {st.to_dict()['safe']}",
    ]
    if who:
        lines.append(f"on_it: {who}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Five-minute plant status")
    p.add_argument("--from-json", help="ops.status data JSON file or - for stdin")
    p.add_argument("--who", help="optional human/agent on incident")
    p.add_argument("--demo", action="store_true", help="run built-in demo snapshot")
    args = p.parse_args(argv)

    if args.demo:
        payload = {
            "nodes": [
                {"node_id": "edge-1", "status": "online"},
                {"node_id": "edge-2", "status": "estop"},
            ],
            "degraded": [],
        }
    elif args.from_json:
        raw = sys.stdin.read() if args.from_json == "-" else open(args.from_json).read()
        doc = json.loads(raw)
        payload = doc.get("data", doc)
    else:
        p.print_help()
        return 2

    st = evaluate_ops_status(payload)
    print(format_report(st, who=args.who))
    return 0 if st.to_dict()["safe"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
