# aspen-edge-rrm

**License:** Apache-2.0  
**Linear:** BEL-188 · Epic BEL-179  
**ADR:** ADR-0002 / ADR-0003

**Runtime Resource Manager** for edge devices: supervises micro-agents, budgets, offline queue, fleet heartbeats, e-stop latch.

## Standalone
```bash
export PYTHONPATH=.
make smoke
python3 examples/fleet_e2e.py
```

## Micro-agents
Must only `propose_act` — RRM mediates and refuses when e-stop latched.

## Audit log
Set `ASPEN_AUDIT_PATH=/var/lib/aspen/audit.jsonl` for durable hash-chained JSONL (default `/tmp/aspen-audit-<node>.jsonl`).

## Optional deps
```bash
pip install nats-py paho-mqtt
export ASPEN_NATS_URL=nats://127.0.0.1:4222
export ASPEN_MQTT_HOST=127.0.0.1
```
