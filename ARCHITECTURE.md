# Architecture
See ADR-0002. RRM is the on-box babysitter between swarm assignments and drivers.

**Single-plant-scheduler invariant (H-018 / ASP-366):** Edge RRM does **not**
schedule missions or assign plant work — it only relays `propose_act` payloads
from micro-agents. Mission scheduling and plant orchestration belong to
Paperclip (aspen-dev SoR). See aspen-langgraph-worker `guard.py` for the
LangGraph-side equivalent.
