# Fleet & Sentinel

Fleet telemetry surface for AspenOS. See [ADR-0007](ADR-0007.md) for the
accepted architecture decision.

## Subjects

| Subject | Producer | Consumer | Status |
|---|---|---|---|
| `aspen.fleet.node.register` | edge RRM | OpsManager | live (BEL-182) |
| `aspen.fleet.node.heartbeat` | edge RRM | OpsManager | live (BEL-182) |
| `aspen.fleet.ops.status` | OpsManager | dashboard | live (BEL-182) |
| `aspen.sentinel.audit.event` | sentinel bridge (edge RRM) | Sentinel consumer | live (ASP-566) |
| `aspen.sentinel.fleet.overview` | ops-manager (planned) | Sentinel consumer | stub (ASP-566) |

## Sentinel consumer

`aspen_edge.sentinel.SentinelConsumer` is a **read-only** observer:

- Subscribes to `aspen.sentinel.audit.event` and `aspen.sentinel.fleet.overview`
- No publish side effects (gatekeeper-aware, flash-only safe)
- In-memory ring buffer (default 10k events) + optional durable JSONL
  (`persist_path`); offline-capable stub under freeze
- Query API: `tail(n)`, `by_type(event)`, `search(query)`, `by_time(a, b)`, `count()`

### Wiring

```python
from aspen_edge import FleetBus, SentinelConsumer, bridge_audit_to_sentinel

bus = FleetBus()
sentinel = SentinelConsumer(bus, persist_path="/var/log/aspen/sentinel.jsonl")
sentinel.start()

# bridge edge audit records onto the sentinel subject
rrm = EdgeRRM(node_id="edge-sim-1", bus=bus)
bridge = bridge_audit_to_sentinel(bus, node_id=rrm.node_id)
rrm.bus.subscribe("aspen.edge.sentinel.audit", bridge)
```

The overview subject (`aspen.sentinel.fleet.overview`) is a planned
ops-manager publish; the consumer already subscribes so the dashboard
surface is producer-ready. See [ADR-0007](ADR-0007.md).

## Contracts

- `aspen.fleet.node.register` / `aspen.fleet.node.heartbeat`
- `aspen.edge.<node>.propose_act`
- `aspen.safety.estop` / `aspen.safety.clear` / `aspen.safety.authorize_clear`
- `aspen.sentinel.audit.event`
- `aspen.sentinel.fleet.overview` (planned)

See [CONTRACTS.md](../CONTRACTS.md).