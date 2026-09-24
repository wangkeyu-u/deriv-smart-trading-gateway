# Deriv Smart Trading Gateway

An agent orchestration prototype that turns a request into bounded tools, checks account authorization and human confirmation, and records execution outcomes.

## Problem

A model can produce an invalid call, a read can fail, and a timed-out write may already have succeeded. The engineering question is how to keep those failures from becoming unintended trades or misleading success reports.

## System

```mermaid
flowchart LR
  A[User request] --> B[Manager tool dispatch]
  B --> C[Read-only analysis]
  B --> D[Execution request]
  D --> E[UI confirmation and account checks]
  E --> F[Typed MCP tool]
  F --> G[Deriv authorization and proposal]
  G --> H[Buy with zero automatic retries]
  H --> I[Receipt or unresolved error]
  C --> J[Audited advisory output]
```

## Engineering decisions

- **Authorization before effects:** reject failed or unrecognized account checks; live-account writes require explicit opt-in. Invalid proposals must stop before buy.
- **Human-in-the-loop:** the Streamlit execution path stages a request for confirmation by default. This is a UI policy, configurable by the operator; direct MCP clients must enforce their own approval boundary. The backend does not cryptographically prove human consent.
- **Write timeout behavior:** buy requests use zero automatic retries. An ambiguous outcome requires account/contract reconciliation before another write.
- **Advisory isolation:** advisor output does not itself execute trades. A transient graph-node failure can fall back to the local advisory flow; persistent component failure is not guaranteed to recover.
- **Inspectable orchestration:** prompt registry, dispatch names, API traces and receipts are available for review. Advisor count is not a quality metric.

## Optional Jev thinking router

The Streamlit sidebar can enable a bounded Jev decision before two read-only steps: a plain market/chart request in the manager console, and the advisor council's final synthesis. Jev chooses `fast` (existing local analysis) or `deep` (existing language-model path). The app accepts `fast` only when Jev returns a valid Choice with at least 0.8 probability and 0.7 confidence. An uncertain or failed response keeps the existing deeper path; an advisor run near its deadline uses the local result. Each run exposes the chosen route, source and routing latency in the UI and JSON result.

Set a normal model provider and API key, then enable **Jev fast/deep routing** and enter a separate TypeSafe API key in the sidebar. The key stays in the current Streamlit session. Jev uses TypeSafe's documented [`/v1/systemone` Choice API](https://docs.typesafe.ai/api) with a 1.2-second maximum request timeout and no automatic retry. Jev is a structured decision model; it does not generate the final analysis or change an in-progress model call. The feature routes at decision checkpoints, so any end-to-end speed improvement must be measured with a real key and representative requests.

Trading requests never enter the manager fast path. Jev output never supplies order parameters, approves a trade, or bypasses account checks and confirmation. The advisor council remains read-only.

## Failure evidence and tests

The audit found the UI recorded an unsuccessful account lookup without returning before execution. This revision blocks that path and unknown account types. The dispatcher also rejects non-object/missing-required-field model calls before invoking a worker.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest tests -q
```

The new [failure-boundary tests](tests/test_failure_boundaries.py) inject failed authorization, invalid symbol/proposal responses, buy timeouts, malformed manager arguments and a transient advisor-node error. Existing [safety tests](tests/test_safety_gates.py) cover missing token, confirmation and blocked live accounts. These tests use fake transport and do not place external trades.

2026-09-16 validation: **23 tests passed**, including 10 added failure cases. The [failure and validation record](docs/failures/account-and-dependency-boundaries.md) also preserves the clean-install MCP 2.x collection failure and compatible dependency constraint.

## Trade-offs and limitations

The manager still relies on backend schemas for full argument validation. Unknown/non-object calls are rejected, but this is not a complete adversarial model-output evaluation. A JSON parsing failure may trigger the existing deterministic manager fallback. Human approval is not bound to an immutable, signed order at the MCP boundary.

A no-retry write avoids automatic duplication but leaves ambiguous outcomes unresolved; there is no durable reconciliation queue. Local traces are inspectable records, not externally attested immutable logs. No trading profitability, model-selection advantage, production availability or real-account test result is claimed.

## Run and inspect

```bash
streamlit run web_app.py
```

Use [configuration and operation details](OPERATIONS.md) for providers and tool examples. [server.py](server.py) owns typed transport tools; [web_app.py](web_app.py) owns orchestration and UI confirmation; [agent_prompts.json](agent_prompts.json) records prompts. The expanded feature catalog remains in the operation guide.

AI tools assisted implementation and this audit's tests/documentation. Passing tests verifies these controls under the recorded cases; developer review owns acceptance of the execution policy and remaining boundaries.
