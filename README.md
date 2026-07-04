# Deriv Smart Trading Gateway

![Deriv Smart Trading Gateway hero](docs/assets/readme-hero.png)

AI trading control room for Deriv. It turns natural-language trading intent into market snapshots, multi-agent advice, risk checks, and human-confirmed execution.

**Built for:** Deriv market data, LangGraph advisor teams, FastMCP tools, Streamlit operations, safer trade review.

## What It Is

Deriv Smart Trading Gateway turns natural-language trading intent into a coordinated multi-agent workflow. It can read live Deriv market data, build candle snapshots, simulate trades, review risk, and prepare execution through a human-confirmed safety gate.

The newest layer is the **Boss Advisor Room**: a LangGraph council where multiple advisor agents read market context, optional web research, and short-horizon signals before producing one clear `CALL`, `PUT`, or `WAIT` recommendation.

Streamlit is the operator UI. LangGraph is the agent orchestration engine. FastMCP exposes the Deriv tool layer for MCP-compatible clients.

## Highlights

- **LangGraph advisor council** with independent advisor nodes, merged graph state, and a chief synthesizer.
- **Extensible agent prompts** through `agent_prompts.json`, including manager, execution workers, and advisor personas.
- **Deriv WebSocket tools** for ticks, historical candles, account checks, simulated trades, open-contract status, and close-contract flows.
- **Natural-language command center** for Chinese and English trading prompts.
- **Human-in-the-loop execution gates** so write actions require explicit confirmation before Deriv order submission.
- **Live-account protection** that blocks live trading unless both UI and backend explicitly allow it.
- **Multi-symbol charting** for synthetic indices, jump indices, boom/crash, and forex symbols such as `R_100`, `R_75`, `BOOM1000`, and `frxEURUSD`.
- **Local audit trail** for team runs, advisor decisions, role dialogue, API traces, and trade receipts.
- **Smoke and pytest coverage** for agent configuration, symbol parsing, LangGraph compilation, advisor runtime, and safety gates.

## Architecture

```text
User / Boss
  |
  v
Streamlit Command Center
  |
  +--> LangGraph Advisor Council
  |      web_research -> market_snapshot -> news_signal -> advisor_* -> synthesize
  |
  +--> Hierarchical Execution Team
  |      manager -> market / strategy / chart / risk / compliance / execution / report
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
├── docs/assets/                    # README and project media
├── mcp_config.json                 # MCP client configuration
├── requirements.txt                # Python dependencies
├── server.py                       # FastMCP server with Deriv WebSocket tools
├── smoke_test.py                   # End-to-end runtime smoke checks
├── tests/                          # Pytest coverage for parsing, safety, prompts, and LangGraph
└── web_app.py                      # Streamlit operator UI and multi-agent runtime
```

## Quick Start

```bash
cd /Users/wangkeyu/Documents/项目
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
/Users/wangkeyu/Documents/项目/Deriv Gateway.command
```

The launcher creates `.venv` if needed, installs dependencies, and opens the Streamlit app.

## Run The MCP Server

```bash
cd /Users/wangkeyu/Documents/项目
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

- Trading Manager decomposes the boss request and dispatches work.
- Market Analyst, Strategy Researcher, Chart Engineer, and Report Agent gather context and produce artifacts.
- Risk Sentinel and Compliance Reviewer block unsafe or incomplete trade requests.
- Execution Trader is the only worker allowed to submit Deriv write operations.

**Advisor Council**

- Macro Advisor reads external catalysts and broad risk tone.
- Quant Advisor focuses on short-window momentum and moving averages.
- Flow Advisor watches rhythm, volatility, and execution windows.
- Risk Advisor challenges overconfident trades.
- Contrarian Advisor attacks the consensus before the chief advisor synthesizes the final view.

When `langgraph` is installed, each advisor runs as a graph node. If LangGraph is unavailable, the app falls back to a local council runner so the UI remains usable.

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

Stored records include team runs, advisor runs, role dialogue, API traces, execution logs, and trade receipts. API keys are not written to this database.

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
13 passed
dependencies: OK
prompts_and_symbols: OK
langgraph_compile: OK
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
