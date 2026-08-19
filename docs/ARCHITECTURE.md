# Architecture and Terminology

## Verified graph boundaries

The runtime has one LangGraph parent `StateGraph` with two mutually exclusive
branches:

```text
parent
├── execution_subgraph
│   manager -> strategy -> market -> compliance -> risk -> chart
│                                                    |
│                                              safety_gate
│                                                /       \
│                                       execution       report
│                                             |
│                                           report
└── advisor_subgraph
    web_research -> market_snapshot -> news_signal
                                      ├── advisor_macro ──────┐
                                      ├── advisor_quant ──────┤
                                      ├── advisor_flow ───────┼─> synthesize (Chief)
                                      ├── advisor_risk ───────┤
                                      └── advisor_contrarian ─┘
```

The parent router chooses exactly one subgraph per invocation. There is no edge
from the advisor branch to the execution branch. Advisor output therefore
cannot become an order without a new user command entering the execution graph.

## Counts: nodes, agents, roles, and model calls

These terms are deliberately not interchangeable:

- The execution subgraph has **8 role nodes**: one Manager and seven Workers
  (`strategy`, `market`, `risk`, `compliance`, `chart`, `execution`, `report`).
- It also has one `safety_gate` node. That node is deterministic control logic,
  not a role, Agent persona, or model call.
- The advisor subgraph has **5 parallel Advisor role nodes** and one Chief
  synthesis role, plus three data/control nodes.
- A graph node is a unit of orchestration. A role is the responsibility and
  prompt identity represented by a node. In this repository “Agent” is the UI
  and product label for those roles; it does not imply a separate process.
- A role-node execution is **not necessarily an LLM call**. The local-rule
  provider uses zero LLM calls. Advisor Chief synthesis makes at most one LLM
  call when a supported provider/key is configured and the time budget remains;
  otherwise it uses deterministic local consensus.

The older provider-specific manager tool-calling functions remain in the source
for compatibility, but the main `run_hierarchical_trading_team` entry point now
runs the execution branch of the parent LangGraph and falls back to the existing
deterministic Python state machine only if graph construction or invocation
raises.

## Execution safety boundary

Only `execution_agent` can call the MCP write tools
`execute_simulated_trade` and `close_open_contract`. Before that node is routed:

1. Manager parses the command into a deterministic plan.
2. Market, Compliance, and Risk roles produce reports in that order.
3. The deterministic `safety_gate` checks required parameters, compliance,
   hard risk blockers, and market conditions.
4. The Execution role preserves the existing token, HITL confirmation, account
   check, and live-account gates.
5. `server.py` independently enforces demo-or-explicit-live before sending a
   Deriv WebSocket write request.

This is defense in depth: neither a Manager prompt nor Advisor recommendation
can bypass the deterministic graph router, execution-role checks, and backend
account-mode check.

## State and reducers

The execution graph uses append reducers for `events` and `graph_trace`, and a
key-merging reducer for `agent_reports`. The advisor graph uses append reducers
for `opinions` and `logs`; the five Advisor nodes may run in parallel, and the
Chief sees every merged opinion.

## Async I/O and fallback

The Deriv client remains an asynchronous WebSocket client with request IDs,
timeouts, retries, a receiver task, and subscription queues. Streamlit bridges
async tools through `run_async` without changing their protocol behavior.

Fallbacks are explicit:

- Execution graph failure -> deterministic Python manager state machine.
- Advisor graph failure -> local advisor council.
- Advisor LLM synthesis failure/unavailability -> deterministic local consensus.
- OpenAI, Anthropic, or DeepSeek Manager tool-calling failure -> the same
  deterministic execution StateGraph; provider output never directly dispatches
  a Deriv write tool.

Fallback does not relax the Execution role's HITL or live-account gates.

Every decision budget is clamped to 4–25 seconds. State carries an absolute
deadline plus per-node elapsed and remaining time. Exhaustion routes through a
deterministic safety/report path and cannot enter the Execution role.

## What is not claimed

- The eight execution roles are not eight OS processes or eight independently
  hosted services.
- A role activation is not proof of an LLM invocation.
- Tests mock Deriv-facing calls for deterministic routing assertions; they do
  not prove broker availability, profitable strategies, or live trading.
- Advisor web context is lightweight research input, not a verified real-time
  news feed.
