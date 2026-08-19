# Deriv Resume Evidence

Source resume: `/Users/wangkeyu/Downloads/123简历.pdf`

SHA-256: `dc82b04dd8ca3d628c9b5c1b2cc17ed079c1b8356ea2079b7c44870be29ca4cb`

The machine-readable source of truth is `docs/resume-evidence.json`. Runtime
counts, versions, schemas, hashes, and offline observations are recomputed into
`docs/evidence/runtime-evidence.json`; the read-only Deriv result is kept
separately in `docs/evidence/network-smoke.json`.

Statuses are restricted to `verified`, `implemented_unverified`, and
`unsupported`.

## 1. StateGraph roles and 4–25 second budget — verified

Resume text:

> 采用LangGraph架构设计多智能体AI交易网关，通过StateGraph模式协调8个执行代理和5个并行顾问，在4–25秒延迟预算内完成交易决策。

Runtime enumeration finds eight execution role nodes, five parallel Advisor
nodes, and one Chief node. Both execution and Advisor state carry a clamped
4–25 second budget, absolute deadline, per-node elapsed time, and remaining
budget. Deadline exhaustion fails closed before the write-capable role.

“4–25 秒”在这里表示可配置且强制执行的决策预算范围，不表示系统故意等待
4 秒，也不表示所有观测耗时都落在 4–25 秒。离线 benchmark 明确标记为
fixture；真实网络观测单列且不支持预算结论。

Recompute:

```bash
.venv/bin/python scripts/generate_runtime_evidence.py
.venv/bin/python -m pytest tests/test_decision_budget.py tests/test_execution_graph.py -q
```

## 2. Async WebSocket resilience — verified

Resume text:

> 为Deriv API构建弹性异步WebSocket客户端，实现请求多路复用、基于asyncio的路由、订阅队列调度及指数退避重连机制。

The client correlates concurrent responses through `req_id -> Future`, keeps
socket sending separate from response waiting, routes subscriptions through
bounded queues, applies drop-oldest backpressure, buffers early subscription
messages in a bounded backlog, and retries with capped exponential backoff plus
jitter. Async tests resolve requests out of order and run retry timing without
real sleep.

The read-only network smoke currently reports historical candles as successful
and live tick lookup as `InvalidSymbol` on the current Deriv route. It makes no
authenticated or write call.

```bash
.venv/bin/python -m pytest tests/test_websocket_resilience.py -q
.venv/bin/python scripts/run_network_smoke.py
```

## 3. Three-layer safety — verified

Resume text:

> 实施三层安全防护流水线（合规→风控→执行），集成人工复核验证、默认禁用实盘账户及令牌掩码机制，防止误操作交易。

The graph order is Compliance → Risk → deterministic safety gate → Execution.
HITL blocks before account or write calls. Live execution defaults to false in
the UI state and is independently rejected by the backend. Tokens are masked in
receipts, nested traces, provider failures, and gateway exception messages.
Capability-deletion checks fail if the required gate source disappears.

```bash
.venv/bin/python -m pytest tests/test_security_evidence.py tests/test_safety_gates.py -q
```

## 4. Provider tool-calling fallback — implemented_unverified

Resume text:

> 设计双运行时代理系统，实现从LLM工具调用（OpenAI/Anthropic/DeepSeek）到本地确定性Python状态机的无缝降级，确保离线场景可靠性。

All three providers use the same seven Manager tool schemas. Provider output is
validated but never directly dispatched to Deriv; the business request always
enters the deterministic LangGraph/Python runtime. Provider exceptions enter
that same graph and have API keys redacted.

The contract tests use mock-provider fixtures. No real OpenAI, Anthropic, or
DeepSeek request was run, so end-to-end provider integration is not verified.

```bash
.venv/bin/python -m pytest tests/test_provider_contract.py -q
```

## 5. Six FastMCP tools — implemented_unverified

Resume text:

> 通过FastMCP实现6个标准化MCP工具（市场数据、交易执行、账户管理），支持与任何MCP兼容客户端无缝集成。

Runtime enumeration verifies exactly six tools:

- Market data: `get_market_ticks`, `get_historical_candles`
- Trade execution: `execute_simulated_trade`, `close_open_contract`
- Account management: `check_account_status`, `get_open_contract_status`

Their generated schema SHA-256 is
`b573b60e83670173195d07216c15b30b3fec679c8f0657b1b0c846feed0f8f5f`.
The complete generated inventory is `docs/evidence/mcp-tools.json`.
The validator fails if a tool is removed, added, renamed, or its schema hash is
tampered with. “任何 MCP 兼容客户端” remains unverified because exhaustive
client interoperability was not tested.

```bash
.venv/bin/python scripts/generate_runtime_evidence.py
.venv/bin/python scripts/validate_resume_evidence.py
.venv/bin/python -m pytest tests/test_evidence_gate.py -q
```

## Evidence integrity

The negative tests tamper with exact counts, schema hashes, fixture labels,
safety ordering, provider tool names, HITL/live behavior, and secret-bearing
errors. The gates are designed to fail when a capability is deleted or a
machine-readable claim is altered without recomputation.
