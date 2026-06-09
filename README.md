# Deriv Smart Trading Gateway

An AI-native trading gateway for Deriv that combines a native desktop shell, a FastMCP tool server, a LangGraph-powered advisor council, and a fast micro-strategy engine for short-horizon decision support.

![Deriv Smart Trading Gateway operator workspace](docs/assets/operator-workspace-preview.png)

## What It Is

Deriv Smart Trading Gateway turns natural-language trading intent into a coordinated multi-agent workflow. It can read live Deriv market data, build candle snapshots, simulate trades, review risk, and prepare execution through a human-confirmed safety gate.

The newest layer is the **Boss Advisor Room**: a LangGraph council where multiple advisor agents read market context, optional web research, and short-horizon signals before producing one clear `CALL`, `PUT`, or `WAIT` recommendation.

The project is moving toward a **native desktop operator app** with background runtime support. Streamlit remains available as an operator console, while LangGraph handles agent orchestration and FastMCP exposes the Deriv tool layer for MCP-compatible clients.

## Technology Stack

| Layer | Technology | Why It Is Used |
| --- | --- | --- |
| Agent orchestration | LangGraph | Models trading work as an explicit state graph instead of a single prompt. This makes routing, guardrails, memory, and tests easier to control. |
| Tool server | FastMCP | Exposes Deriv market and execution tools to MCP-compatible clients while keeping tool boundaries explicit. |
| Market data | Deriv WebSocket API | Provides live ticks, candle history, account checks, proposals, buys, open-contract status, and close-contract flows. |
| Strategy engine | Python + pandas | Keeps numerical work deterministic: EMA, momentum, volatility, cost edge, confidence, paper PnL, and circuit breakers. |
| AI providers | OpenAI-compatible chat API, DeepSeek, Anthropic, local rules | Lets every agent run with configurable prompts and provider choice instead of being locked to one model. |
| Persistence | SQLite | Stores local run history, advisor results, micro-strategy runs, trade receipts, audit logs, and agent memory without requiring a remote database. |
| Charts | Plotly | Renders candlesticks, moving averages, advisor overlays, zoom, measurement, and exportable chart views. |
| Operator UI | Streamlit | Provides a fast multi-page control console for advisor, trading desk, charts, micro strategy, and monitoring. |
| Desktop shell | PySide6 | Provides a native app surface, background behavior, and tray-style operator workflow. |
| Validation | pytest, smoke tests, browser checks | Covers parsing, prompts, LangGraph compilation, safety gates, persistence, market tools, and UI rendering. |

## Design Philosophy

The system is intentionally not an "AI says buy, then buys" demo. The architecture separates reasoning, calculation, safety, and execution:

- LLM agents reason, debate, summarize, and coordinate work.
- Deterministic Python code calculates prices, indicators, budgets, and circuit breakers.
- LangGraph controls which agent can run next and blocks execution before unsafe nodes are called.
- SQLite keeps a local audit trail so the operator can reopen the app and continue from recent context.
- Human confirmation remains the final write gate before any Deriv order submission.

This makes the project closer to a controlled AI operations system than a single chatbot.

## Highlights

- **LangGraph trading team runtime** with supervisor routing, graph nodes, handoff-style routing, guardrails, shared state, and per-agent memory.
- **LangGraph advisor council** with independent advisor nodes, merged graph state, and a chief synthesizer.
- **Extensible agent prompts** through `agent_prompts.json`, including manager, execution workers, and advisor personas.
- **Deriv WebSocket tools** for ticks, historical candles, account checks, simulated trades, open-contract status, and close-contract flows.
- **Natural-language command center** for Chinese and English trading prompts.
- **Human-in-the-loop execution gates** so write actions require explicit confirmation before Deriv order submission.
- **Live-account protection** that blocks live trading unless both UI and backend explicitly allow it.
- **Multi-symbol charting** for synthetic indices, jump indices, boom/crash, and forex symbols such as `R_100`, `R_75`, `BOOM1000`, and `frxEURUSD`.
- **Advisor evaluation loop** that marks recent advisor calls against latest price and 1m/5m/10m candle horizons for paper accuracy and return tracking.
- **Multi-page operator workspace** that separates the advisor room, trading desk, charts, and system monitor.
- **Global status strip** for symbol, latest advisor stance, entry reference, API calls, sync version, and pending-trade state.
- **Chart-linked advisor overlays** that draw the latest matching advisor entry reference directly on candlestick charts.
- **Trading-desk safety panel** that makes token, human-confirmation, live-execution, and pending-order state visible before execution.
- **Native desktop shell** through PySide6 with system health, background tray behavior, and micro-strategy analysis.
- **Micro trading strategy engine** for small, frequent paper-trade decisions using momentum, EMA separation, volatility, cost edge, and risk limits.
- **Paper trading workbench** for the micro strategy module with persisted strategy runs, budget checks, trade logs, win rate, PnL, equity, and circuit-breaker halts.
- **Advisor-to-trade draft bridge** that can turn a `CALL` or `PUT` advisor result into a pending trade draft without submitting an order.
- **Audit export** for the current decision chain, excluding API tokens.
- **Local audit trail** for team runs, advisor decisions, role dialogue, API traces, and trade receipts.
- **Smoke and pytest coverage** for agent configuration, symbol parsing, LangGraph compilation, advisor runtime, and safety gates.

## Architecture

```text
User / Boss
  |
  v
Native Desktop Operator App / Streamlit Console
  |
  +--> LangGraph Advisor Council
  |      web_research -> market_snapshot -> news_signal -> advisor_* -> synthesize
  |
  +--> Micro Strategy Engine
  |      recent prices -> momentum/EMA/volatility/cost checks -> CALL/PUT/WAIT or BUY/SELL/HOLD
  |
  +--> LangGraph Trading Team
  |      supervisor -> routed worker nodes -> guardrails -> report
  |
  v
FastMCP Deriv Tool Server
  |
  v
Deriv WebSocket API
```

## Repository Layout

```text
.
├── agent_prompts.json              # Editable prompt registry for manager, workers, and advisors
├── advisor_evaluation.py           # Paper evaluation logic for advisor outcomes and horizons
├── desktop_app.py                  # Native PySide6 desktop shell
├── desktop_packaging_requirements.txt # Optional PyInstaller dependency set
├── desktop_requirements.txt        # Optional desktop UI dependency set
├── docs/assets/                    # README and project media
├── mcp_config.json                 # MCP client configuration
├── micro_trading.py                # Small-trade strategy analysis engine
├── packaging/pyinstaller/          # Desktop app packaging spec
├── paper_trading.py                # Paper-trading backtest and circuit-breaker utilities
├── requirements.txt                # Python dependencies
├── scripts/build_desktop_app.sh     # macOS desktop build helper
├── server.py                       # FastMCP server with Deriv WebSocket tools
├── smoke_test.py                   # End-to-end runtime smoke checks
├── tests/                          # Pytest coverage for parsing, safety, prompts, and LangGraph
└── web_app.py                      # Streamlit operator UI and multi-agent runtime
```

## Native Desktop App

The native desktop app is the intended long-term operator surface. It does not require opening a browser and can keep running in the background through the system tray when the platform supports it.

Run it directly:

```bash
cd deriv-smart-trading-gateway
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -r desktop_requirements.txt
.venv/bin/python desktop_app.py
```

On macOS you can double-click:

```text
Deriv Desktop.command
```

Current desktop modules:

- **Monitor**: local DB, LangGraph, token, pending-trade, and freshness health checks.
- **Micro Strategy**: quick small-trade analysis from recent closes for Deriv, funds, equities, crypto, or forex-style instruments. This module has its own small-budget guard and does not change the general trading desk behavior.
- **Background**: close-to-tray behavior where supported.

Build a macOS desktop app bundle:

```bash
cd deriv-smart-trading-gateway
scripts/build_desktop_app.sh
open "dist/Deriv Smart Trading Gateway.app"
```

The build script installs the regular runtime, desktop UI dependencies, and PyInstaller packaging dependencies into `.venv`, then creates a local app bundle under `dist/`.

## Streamlit Operator Console

The Streamlit UI remains available as a full operator console and is organized into focused pages:

- **Advisor Room**: advisor council, source review, transcripts, and paper evaluation.
- **Micro Strategy**: standalone small-budget strategy lab with budget checks, paper trading, and circuit breakers.
- **Trading Desk**: natural-language trading manager, direct agent dispatch, and execution log.
- **Charts**: candle snapshots, comparison overlays, measurement, data export, and latest ticks.
- **Monitor**: live agent graph, agent roster, sync bus, and API trace.

The console uses a terminal-style module navigator with clear route cards for each page. The active module is highlighted, while the global status strip stays visible above every workspace so critical state is not hidden during page switches.

Every page shares one global status strip so the operator can see current symbol, latest advisor stance, entry reference, API call count, sync version, and pending-trade state without switching context.

The Trading Desk also surfaces the execution safety gate as a compact panel, while Charts can overlay the latest matching advisor reference price on the active candlestick view.

## Micro Strategy And Paper Trading

The micro strategy module is separate from the main trading desk. It can analyze recent closes, apply a small-budget guard, run paper-trading backtests, persist recent strategy runs, and halt simulations through circuit breakers such as consecutive losses, total loss, drawdown, or trade-count limits.

This module is intentionally non-executing by default. It produces analysis, paper results, and risk context; it does not bypass the trading desk, human confirmation, or MCP execution safety model.

## Streamlit Quick Start

```bash
cd deriv-smart-trading-gateway
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run web_app.py --server.port 8501
```

Open the app:

```text
http://localhost:8501
```

On macOS you can also double-click:

```text
Deriv Gateway.command
```

The launcher creates `.venv` if needed, installs dependencies, and opens the Streamlit app.

## Run The MCP Server

```bash
cd deriv-smart-trading-gateway
.venv/bin/python server.py
```

Available MCP tools:

- `get_market_ticks`
- `get_historical_candles`
- `execute_simulated_trade`
- `check_account_status`
- `get_open_contract_status`
- `close_open_contract`

## Agent System

The app uses two complementary agent systems.

**Execution Team**

- A LangGraph supervisor builds a route for each user request instead of blindly running every worker.
- Strategy, Market, Risk, Compliance, Chart, Execution, and Report are separate graph nodes with their own prompts and memory.
- Every node writes to shared graph state, the UI timeline, and its own short-term session memory.
- Guardrails keep incomplete or unsafe trade requests away from the Execution Trader.
- Execution Trader is still the only worker allowed to submit Deriv write operations, and it remains blocked by token, demo/live, and human-confirmation gates.

**Advisor Council**

- Macro Advisor reads external catalysts and broad risk tone.
- Quant Advisor focuses on short-window momentum and moving averages.
- Flow Advisor watches rhythm, volatility, and execution windows.
- Risk Advisor challenges overconfident trades.
- Contrarian Advisor attacks the consensus before the chief advisor synthesizes the final view.

When `langgraph` is installed, both the trading team and advisor council run as graphs. If LangGraph is unavailable, the app falls back to local runners so the UI remains usable.

The current architecture follows the same broad patterns used by strong open-source multi-agent projects:

- **LangGraph Swarm / Supervisor style**: route control through graph state and handoff-like node transitions.
- **OpenAI Agents SDK style**: agents have instructions, tools, guardrails, human-in-the-loop boundaries, and traceable runs.
- **CrewAI style**: agents have roles, goals, tools, process, and memory.
- **AutoGen style**: worker agents can collaborate through shared conversation context rather than one monolithic prompt.

The practical result is that a vague request such as `帮我买r100` is routed to Strategy, Risk, Compliance, and Report, then asks for missing amount/direction. A complete request such as `用 1 美金买 R_100 看涨 5 ticks` enters the full Strategy -> Market -> Risk -> Compliance -> Execution -> Report chain.

## Extend Agents

All core prompts live in:

```text
agent_prompts.json
```

Add a new advisor by creating an `advisor.<id>` entry:

```json
{
  "advisor.breakout": {
    "name": "Breakout Advisor",
    "prompt": "Only evaluate breakout and failed-breakout setups. Always include confirmation price, invalidation level, and whether to wait."
  }
}
```

The UI automatically creates a matching LangGraph advisor node for custom advisor prompts. The reserved `advisor.chief` prompt controls the final synthesizer.

To add a new execution worker, add its prompt first, then register the corresponding tool or node in `web_app.py`.

## Advisor Evaluation

The advisor council now records an entry reference price with each recommendation. From the UI, the operator can mark recent advisor decisions against the latest available price and recent one-minute candle horizons, then inspect:

- direction accuracy for `CALL` and `PUT` recommendations
- paper return percentage for directional calls
- `WAIT` quality when the market remains inside a small movement threshold
- 1m, 5m, and 10m horizon scores after the advisor decision
- per-run outcome, confidence, entry price, mark price, and question

This is intentionally paper evaluation only. It does not place trades or imply real execution quality, but it creates the feedback loop needed before trusting advisor behavior.

## Safety Model

The gateway is designed to keep execution explicit:

- API keys are stored only in Streamlit session state, not hardcoded in source files.
- Missing token, missing amount, missing direction, or unclear trade intent blocks execution.
- Deriv write actions require human confirmation from the UI.
- Demo accounts are supported by default.
- Live-account execution is blocked unless `allow_live=true` is explicitly provided by both UI and backend paths.
- Advisor recommendations never bypass the execution safety gate.

## Local Data

The app stores run history and audit records in a local SQLite database:

```text
local_data/gateway.sqlite3
```

The database is created automatically on first run. You do not need a remote account or cloud database for local persistence.

Stored records include:

- `team_runs`: user prompt, final manager answer, agent event timeline, market report, execution report, and execution log.
- `advisor_runs`: advisor question, symbol, consensus, confidence, full result JSON, and paper-evaluation context.
- `micro_strategy_runs`: small-trade strategy goal, symbol, action, confidence, budget result, paper PnL, trade count, and circuit-breaker state.
- `trade_receipts`: Deriv demo/live receipt metadata when an order is actually submitted.
- `agent_memory_items`: short memory summaries for manager, market, strategy, risk, compliance, chart, execution, report, and advisor agents.

On app startup, the workspace hydrates from SQLite:

- the latest trading-desk prompt and answer are restored into the chat area;
- the latest execution log and agent timeline are restored;
- the latest advisor result is restored as the active advisor context;
- recent advisor, team, and micro-strategy runs appear in the sidebar and page tables;
- per-agent memory is restored so agents do not start from a completely blank context.

For safety, some values are intentionally not persisted:

- Deriv API tokens;
- model API keys;
- browser session state;
- pending trade confirmations.

Pending trade confirmations are not restored because an old pending order could become stale or unsafe. After reopening the app, the operator must re-check data freshness and confirm a new trade attempt.

If you want the app to prefill secrets without storing them in SQLite, configure local environment variables before launch:

```bash
export DERIV_API_TOKEN="your-demo-token"
export OPENAI_API_KEY="your-openai-key"
# or:
export DEEPSEEK_API_KEY="your-deepseek-key"
export ANTHROPIC_API_KEY="your-anthropic-key"
export OPENAI_COMPATIBLE_API_KEY="your-compatible-key"
export OPENAI_COMPATIBLE_BASE_URL="https://api.your-provider.com/v1"
```

The UI masks these values, and audit export still excludes them.

To reset local history, stop the app and remove the SQLite file:

```bash
rm local_data/gateway.sqlite3
```

API keys are not written to the database. They live only in the current UI session and are masked in the interface.

## Model Providers

The model selector supports:

- Local rule engine with no model API key.
- OpenAI.
- DeepSeek through the OpenAI-compatible base URL `https://api.deepseek.com`.
- Anthropic.
- Custom OpenAI-compatible providers with a configurable base URL.

## Symbol Examples

The chart and advisor workflows accept many Deriv symbols:

```text
Draw the latest 120 one-minute candles for R_100
Draw frxEURUSD 60 candles at 5m
Analyze R_75 for the next 5 minutes
Check BOOM1000 momentum before execution
```

Common symbols include:

```text
R_10, R_25, R_50, R_75, R_100
1HZ10V, 1HZ25V, 1HZ50V, 1HZ75V, 1HZ100V
BOOM500, BOOM1000, CRASH500, CRASH1000
JD10, JD25, JD50, JD75, JD100
frxEURUSD, frxGBPUSD, frxUSDJPY
```

## Validation

Run the checks:

```bash
.venv/bin/python -m py_compile web_app.py server.py smoke_test.py
.venv/bin/python -m pytest -q
.venv/bin/python smoke_test.py
```

Recent validation:

```text
77 passed
dependencies: OK
prompts_and_symbols: OK
advisor_evaluation: OK
langgraph_compile: OK
micro_trading_engine: OK
budget_guard: OK
paper_trading: OK
deriv_market_tools: OK
advisor_runtime: OK
```

## Deriv Endpoint

The implementation defaults to the compatible Deriv v3 WebSocket endpoint:

```text
wss://ws.derivws.com/websockets/v3?app_id={app_id}
```

Override it with `DERIV_WS_URL_TEMPLATE` if you need a different endpoint.

## Disclaimer

This project is a local trading assistant and research gateway. It is not financial advice. Always review advisor output, risk gates, account mode, and order parameters before placing trades.
