# Deriv Smart Trading Gateway

This project implements the Deriv Smart Trading Gateway as both an MCP server and a Streamlit web interface.

## Files

- `server.py` - FastMCP server with Deriv WebSocket tools.
- `web_app.py` - Streamlit web UI for Chinese natural-language trading commands.
- `requirements.txt` - Python runtime dependencies.
- `mcp_config.json` - MCP client configuration for Claude Desktop or Cursor.

## Install

```bash
cd /Users/wangkeyu/Documents/项目
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Run The Streamlit Web App

```bash
cd /Users/wangkeyu/Documents/项目
.venv/bin/streamlit run web_app.py --server.port 8501
```

Open:

```text
http://localhost:8501
```

## Multi-Symbol Chart Examples

The trading chart workbench is not limited to `R_100`. It accepts any Deriv symbol supported by the public WebSocket API, for example:

```text
画 R_75 最近 120 根 1分钟K线
画 frxEURUSD 最近 60 根 5分钟K线
Draw the latest 120 one-minute candles for R_100
Draw frxEURUSD 60 candles at 5m
```

The Chart Engineer agent also creates separate chart snapshots, so multiple symbols can be compared and reviewed through the snapshot tabs.

The web app stores Deriv and model-provider API keys only in Streamlit session state. They are not hardcoded in source files.

## Open As A Local Desktop Launcher

On macOS, double-click:

```text
/Users/wangkeyu/Documents/项目/Deriv Gateway.command
```

The launcher creates `.venv` if needed, installs `requirements.txt`, and opens the Streamlit app on:

```text
http://localhost:8501
```

## Local Data

The web app now stores team runs, role dialogue, execution logs, and trade receipts in a local SQLite database:

```text
/Users/wangkeyu/Documents/项目/local_data/gateway.sqlite3
```

The API keys are still session-only and are not written to this database.

The model selector supports:

- Local rule engine, no model API key required.
- OpenAI.
- DeepSeek, using the OpenAI-compatible base URL `https://api.deepseek.com`.
- Anthropic.
- OpenAI-Compatible custom providers with a configurable `Base URL`.

## Run The MCP Server

```bash
cd /Users/wangkeyu/Documents/项目
.venv/bin/python server.py
```

## MCP Tools

- `get_market_ticks`
- `get_historical_candles`
- `execute_simulated_trade`
- `check_account_status`

## Configuration

Use `mcp_config.json` in an MCP-compatible client. The default Deriv app id is `1089`.

The historical Deriv `v1` WebSocket endpoint currently returns HTTP 404 in live tests, so this implementation defaults to the compatible `v3` endpoint:

```text
wss://ws.derivws.com/websockets/v3?app_id={app_id}
```

Override it with `DERIV_WS_URL_TEMPLATE` if you need a different endpoint.
