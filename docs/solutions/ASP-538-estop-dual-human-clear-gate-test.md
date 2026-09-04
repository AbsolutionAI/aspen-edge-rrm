# ASP-538: Estop Dual-Human Clear Gate Integration Test

## Problem

The estop `clear` mechanism could be triggered by a single operator or by a bare
`clear` message without authorization, violating the H-007 dual-human safety
requirement. No integration test existed to verify the gating logic end-to-end
through the EdgeRRM bus.

## Solution

Added `test_estop_clear_requires_dual_human` to `tests/test_gate.py`. The test
exercises the full `DualHumanGate` integration via `EdgeRRM.bus`:

1. Publish `estop` → RRM enters estop-latched state
2. Publish bare `clear` → refused (`insufficient_principals` audit event)
3. Publish single `authorize_clear` + `clear` → still refused
4. Stop-causer attempts `authorize_clear` → refused (`self_approval` audit event)
5. Second distinct human `authorize_clear` + `clear` → estop unlatches

Also added `test_estop_still_blocks_before_gate` to verify that estop blocks
agent proposals before gate authorization.

## Verification

```bash
python3 -m pytest tests/test_gate.py -v
```

All 11 tests pass, including the two new estop dual-human clear gate tests.

## References

- H-007: Dual-human safety authorization requirement
- ADR-0003: Safety architecture decisions
- SECURITY_THREAT_MODEL v2.2 §4.2: Estop clear gate threat analysis
- Commit `32bfbce`: DualHumanGate + RRM wiring implementation