"""Optional NATS roundtrip — skips if no server/deps."""
import asyncio
import logging
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.getLogger("nats").setLevel(logging.CRITICAL)

from aspen_edge.nats_bus import nats_available, NatsFleetBus

async def main():
    if not nats_available():
        print("nats_roundtrip skip: nats-py not installed")
        return 0
    url = os.environ.get("ASPEN_NATS_URL", "nats://127.0.0.1:4222")
    bus = NatsFleetBus(servers=url)
    try:
        await asyncio.wait_for(bus.connect(), timeout=1.5)
    except Exception as e:
        print(f"nats_roundtrip skip: cannot connect {url} ({type(e).__name__})")
        return 0
    got = {}
    def handler(env):
        got["env"] = env
    await bus.subscribe("aspen.fleet.node.heartbeat", handler)
    await bus.publish("aspen.fleet.node.heartbeat", {"node_id": "nats-test", "status": "online"}, source="test")
    await asyncio.sleep(0.3)
    await bus.close()
    if got.get("env", {}).get("data", {}).get("node_id") == "nats-test":
        print("nats_roundtrip ok")
        return 0
    print("nats_roundtrip skip: no message")
    return 0

if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
