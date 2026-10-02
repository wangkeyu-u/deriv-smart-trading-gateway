# Deriv Gateway 操作指南

更新：2026-10-02。当前架构见 [项目说明](docs/project-architecture.md)，实现与故障记录见 [阶段记录](docs/execution-refactor.md)。

## 运行和配置

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/streamlit run web_app.py --server.port 8511
```

工作台不需要另启动 MCP 服务。外部客户端可以启动 `.venv/bin/python server.py`，使用 stdio；生成本机路径配置：

```bash
.venv/bin/python scripts/print_mcp_config.py
```

| 配置 | 用途 |
| --- | --- |
| TYPESAFE_API_KEY | 启动时提供 Jev 密钥，也可在工作台设置中填写 |
| DERIV_DB_PATH | Streamlit/MCP 共用的 SQLite 路径；默认 local_data/gateway.sqlite3 |
| DERIV_APP_ID / DERIV_WS_URL_TEMPLATE | 现有 Legacy WebSocket 接入 |
| DERIV_RISK_POLICY | 风控 JSON 配置文件的路径 |
| DERIV_LIVE_WRITES_ENABLED=1 | 主机显式开放 live 写能力，仍需确认和风控 |
| DERIV_MCP_LIVE_WRITES_ENABLED=1 | 外部 MCP 的额外 live 能力开关 |

Deriv Token 和解释模型密钥在工作台设置或工具参数中提供，不保存到订单库。代码不自动加载 `.env`。分享 MCP 配置时不填写完整密钥。

## 四个工作区

### 分析

选择快速看盘、复核想法或深入研究，填写问题和品种。复核方向是 UP/DOWN。可调 4–25 秒预算和外汇近期新闻。Jev 决定 finish/deep/wait，解释模型按需补充文字，分析不会提交订单。

输入草稿跨页面保留。记录页可查看历史证据、下载 JSON 和复用参数；复用后需要用户再次提交才会读取行情。价格为带时间的快照。

### 行情

读取 Tick、60/300/3600 秒 K 线、保存图表快照，并保留对比、测量与下载数据功能。品种支持原来的自定义输入；能查看某品种不等于该品种被风控允许交易。

### 交易

示例：“买入 R_100，10 USD CALL，5 Tick”；“平仓合同 123456”。Manager 只理解意图并产生草稿。核对账户、金额、方向、期限后勾选确认，点击“确认并提交”。实际授权、风险、proposal、buy/sell 都由固定程序执行。

重复指令和页面 rerun 沿用原逻辑意图。“新建另一笔订单”用于明确启动新的订单。修改金额、期限或 Token 会重新要求确认。

执行状态可选择 ENABLED/REDUCE_ONLY/HALTED。“停止所有新买入”保存全局 HALTED。它不会关闭账户查询和已批准平仓。

重启后或 MCP 创建的草稿可在“恢复订单 / MCP 草稿”中载入。UNKNOWN 使用“只读对账”；不能唯一匹配时保留状态。用户核对经纪商账单后可显式填写对应 contract_id，再核对该合约；这不会重新 buy。已确认或绑定的合约 ID 不能改为另一合约。卖出请求结果未知时，合约自然到期不作为请求卖出成功的证明。

### 记录

原分析、团队记录和回执保留。新增领域订单在交易页查看状态，详细事件、风险和恢复队列保存于 SQLite。旧历史 CALL/PUT 只在读取边界映射到窗口趋势，不修改原记录。

## MCP 工具迁移

| 工具 | 用途 |
| --- | --- |
| get_market_ticks / get_historical_candles | 公开行情 |
| check_account_status | 账户余额及持仓 |
| get_open_contract_status | 指定合约，或开放持仓列表 |
| create_trade_intent | 创建严格意图并验证账户，返回待确认订单 |
| get_trade_intent / get_order_status | 查询意图/订单；订单 refresh=true 可只读核对 |
| place_contract | 提交已有本地批准的 BUY 意图 |
| close_open_contract | 提交已有本地批准的 SELL 意图，当前只支持 market price=0 |

旧 execute_simulated_trade 已迁移为 place_contract，旧接口不再注册。所有写入口必须传 intent_id，不能靠 Token 和 allow_live 直接买入。

创建草稿的 payload 是 JSON 字符串。例如：

```json
{
  "intent_id": "user-request-unique-001",
  "source": "mcp",
  "action": "BUY",
  "symbol": "R_100",
  "direction": "CALL",
  "amount": "10.00",
  "duration": 5,
  "duration_unit": "t",
  "account_mode": "demo"
}
```

相同请求重发时沿用这个 ID，新订单使用新 ID。之后在工作台载入并确认；MCP 没有 approve 工具。已批准意图的提交参数必须完全匹配，数值等值的 10/10.0/10.00 视为相同金额。

默认 MCP 不能直接 live execution；即使同时启用两个主机开关，也不能绕过持久 Approval、账户匹配、全局状态或 RiskEngine。

## 风控配置

配置文件可只写需要覆盖的字段；其余使用默认值。以下是默认配置，金额为账户币种：

```json
{
  "max_stake_per_trade": "50",
  "max_total_open_stake": "200",
  "max_open_contracts": 5,
  "max_symbol_exposure": "100",
  "max_daily_loss": "50",
  "max_consecutive_losses": 3,
  "cooldown_after_loss": 60,
  "min_available_balance": "10",
  "allowed_symbols": ["R_100", "R_75", "R_50", "R_25", "R_10", "frxEURUSD", "frxGBPUSD"],
  "allowed_contract_types": ["CALL", "PUT"],
  "max_duration": 3600,
  "max_tick_duration": 10,
  "max_orders_per_minute": 5
}
```

通过 `DERIV_RISK_POLICY` 指向文件。严格校验拒绝额外字段和非法类型。日亏损为 UTC 当日已结算净损益的负数部分；连亏来自最近结算记录。损益按合约去重，读取覆盖当日与完整的尾部亏损序列；非有限值、负金额、记录冲突、超过 2000 条读取边界或读取失败时不提交。未知订单计入预留并阻止新 BUY。

## 数据升级与恢复

保留原 SQLite 文件，启动会执行增量 migration；本轮 v3 仅增加对账 lease_token。订单意图、状态、事件、确认、风险、回执和对账任务均持久化。不要删除数据库来“清除”未知订单；这样会失去幂等与恢复依据。

运行实例需要共享同一数据库路径。进程退出可由 owner_pid 检测；无法证明退出时租约到期再恢复。MCP 无账户密钥启动仅排队；显式带账户调用 `get_order_status(refresh=true)` 可以恢复。没有常驻后台对账服务。

## 测试与 Jev 评估

```bash
.venv/bin/python -m pytest -q --disable-warnings --tb=short --show-capture=no
.venv/bin/python scripts/evaluate_jev.py --output local_data/jev-offline-replay.json
# 显式真实模型调用，仅发送人工场景
.venv/bin/python scripts/evaluate_jev.py --live --output local_data/jev-live-eval.json
```

离线结果中的 Jev 答案为模拟，真实 latency/token/cost 为 null。`--live` 使用 TYPESAFE_API_KEY；可用 `--input-price-per-million` 和 `--output-price-per-million` 提供明确报价进行估算，不作为经核实账单。

`smoke_test.py` 包含真实行情请求并可能写本地分析记录。它不是离线测试，也不证明真实交易通过。
