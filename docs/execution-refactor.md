# 交易执行核心改造记录

以 `30f34bd` 为起点，保留 Streamlit、LangGraph、FastMCP 和现有 SQLite 历史。

## Phase 1

新增 domain/trade.py、order.py、market.py。交易方向与窗口观察分开：观察为 UP/DOWN/FLAT/UNKNOWN，顶层兼容 stance 保持 WAIT；Jev Choice 的结构不变，观察选项改为趋势枚举。旧历史在读取边界转换，原始 SQLite 不删除。买入入口更名 place_contract，显式校验 demo/live 与授权账户一致。

领域迁移已完成。

Phase 1 完整测试：100 passed。新增测试验证严格字段、SELL 参数和 demo/live 模式绑定。

## Phase 2

最小方案：新增 SQLite additive migrations、订单仓储和 OrderEngine，依赖注入 broker 接口。订单和事件同时提交；条件更新认领 SUBMITTING，重复请求返回原订单；已发送不确定结果记录 UNKNOWN，并排队对账。

Phase 2 完整测试：105 passed。并发重复提交、发送前/发送后错误、重复回执、乱序确认、旧库保留与 append-only 事件均通过。

## Phase 3

新增只读 Reconciler 和 recover_incomplete_orders。未完成写操作使用持久租约，启动不会抢占另一进程正在发送的订单；过期 SUBMITTING/RECONCILING 转 UNKNOWN 并排队。对账失败或证据不足保留 UNKNOWN。金额/品种/时间相似和空 portfolio 均不能证明成交或拒绝。

Phase 3 完整测试：109 passed。已成交后超时、重启恢复、不抢占活跃提交、对账无证据均通过；BUY 调用次数不增加。

## Phase 4

新增 TradingService 与持久 Approval。Streamlit/旧兼容执行入口/MCP 共享服务；MCP 必须提供 intent_id，不能自己批准。确认绑定完整参数与授权账户，十分钟有效。live 还需要主机 DERIV_LIVE_WRITES_ENABLED=1；MCP 另外需要 DERIV_MCP_LIVE_WRITES_ENABLED=1。UI 不再提供跳过确认开关。历史回执新增 order_id 唯一索引，原记录保留。

Phase 4 完整测试：111 passed。持久确认、金额变更、跨进程复用和 MCP live capability 均通过。

## Phase 5

RiskEngine 是纯函数。配置覆盖单笔/总额/数量/品种/日亏损/连亏/冷却/余额/期限/速率；SQLite 全局状态支持 ENABLED/REDUCE_ONLY/HALTED。风险判断与 SUBMITTING 认领在同一个 SQLite 写事务中，计入其他进程已预留及未知订单。risk_events 保存结构化允许/拒绝原因。买入必须读取完整的当日已结算损益；不可用时不提交。HALTED 不阻止已批准的平仓。

Phase 5 完整测试：124 passed。已覆盖持久 HALTED 和各风险限额，所有买入经过同一 RiskEngine。

## Phase 6

LLM 的唯一写相关工具改为 propose_trade_intent，输出严格 TradeIntentDraft 后立即结束。旧模型执行调度工具被移除；确定性 fallback 也只产生草稿。工作台确认按钮提交持久参数，模型不再参与批准后的流程。Manager 的 Jev/读取/模型调用共享 ExecutionContext；写入开始后独立等待结果，不因读取预算耗尽重试。

Phase 6 完整测试：128 passed。Manager 在首个草稿后停止，重复草稿沿用 intent_id；旧 write tool 不再可被模型调用；monotonic deadline 测试通过。

## Phase 7

DerivAdapter Protocol 与 AccountSnapshot/Proposal/ContractSnapshot/ClosedContract 已独立，WebSocket JSON、req_id、错误和订阅归入 adapters/deriv/client.py。Strategy 仅提供协议与有时效的 TradeSignal，无自动策略。Jev 评估增加四种路由对照和要求的指标，阈值标记 UNCALIBRATED_THRESHOLD；离线不声称测得模型速度、token 或成本。主协议结构保持 Choice，语义选项迁移的版本为 scenario-v3/advisory-v3。

Phase 7 最终完整测试：153 passed（2026-10-01）。离线场景回放 12/12。

收尾兼容性检查：旧只读规划器不能规划底层写操作；仅说“买入”时不再默认生成 CALL。Streamlit 与 MCP 通过 DERIV_DB_PATH 共用数据库，相对路径固定按项目目录解析，不随进程工作目录改变。真实评估缺失 token usage 时保留 null，不记为零。

## 故障验收矩阵

| 要求 | 验证位置 | 已验证行为 |
| --- | --- | --- |
| 成交后客户端超时 | test_execution_faults.py / test_reconciliation.py | UNKNOWN → 只读核对 → OPEN，BUY 仅一次 |
| 发送前失败 | test_adapter_transport.py / test_execution_faults.py | 明确 NotSent，零 BUY |
| 重复/并发请求 | test_order_engine.py / test_execution_faults.py | 单订单原子认领，唯一回执 |
| 真实进程退出 | test_reconciliation.py | 子进程 SUBMITTING 后退出，重启即时只读恢复 |
| 重复 WebSocket message | test_adapter_transport.py | future 仅完成一次，不重复派发 |
| 乱序 OPEN → ACK | test_order_engine.py | 状态不倒退 |
| 审批后金额变更 | test_execution_faults.py / test_trading_service.py | 服务/MCP 均拒绝 |
| HALTED | test_risk_engine.py / test_execution_faults.py | BUY 被拒；已批准 SELL 可关闭持仓 |
| MCP live 绕过 | test_execution_faults.py | 主机能力及持久审批缺一不可 |
| Manager 重复调用 | test_manager_drafts.py | 只生成一次逻辑意图，不参与提交 |
| 并发资金预留 | test_risk_engine.py | 不同订单在同一事务内检查总敞口 |
| UI 确认与 rerun | test_execution_faults.py | 真正走服务，只提交一次，HALTED 不被覆盖 |
| 审批在预检期间失效 | test_trading_service.py | 提交认领时拒绝 |
| 风险数据缺失 | test_execution_faults.py | RISK_DATA_UNAVAILABLE 落盘，不提交 |
| 旧规划器与缺失方向 | test_manager_drafts.py | 只读规划不能写；未指定方向时不生成 CALL |
| 跨工作目录共享数据库 | test_trading_service.py | 相同配置解析为同一 SQLite 路径 |
| 评估 usage 缺失 | test_evaluation_and_strategy.py | 保留未知值，不把缺失统计当作零消耗 |

## 经纪商对账边界

[Deriv portfolio](https://developers.deriv.com/docs/account/portfolio/) 只提供开放合约，[statement](https://developers.deriv.com/docs/account/statement/) 用于历史交易。适配器读取这些接口与指定合约；不会将 req_id/passthrough 当作服务端幂等支持。若 Legacy 记录无法提供唯一关联，保持 UNKNOWN，由用户核对后显式绑定 contract_id。所有新测试使用假传输，没有外部订单。

## 保留与迁移

- 四个工作区、旧记录、LangGraph、Jev 场景、解释模型、行情图表、MCP 继续保留。
- 旧 simulated 名称已迁移；旧 Manager 执行工具被拒绝，迁移为 propose_trade_intent。
- 旧观察 CALL/PUT 在历史读取边界转换；旧记录不删除。
- Approval 不再允许 UI 配置跳过，跨进程通过 SQLite 共享。
- 启动扫描无密钥时只排队，不偷偷读取环境 Token 或重新 buy。

## 2026-10-02 执行核心复审

以 `5859e5b` 为起点，先加入故障用例复现问题，再修复服务、仓储、对账和适配器边界。保留现有工作台和 Jev 路由。本轮新增 28 项用例，完整 pytest **181 passed**，Python compile 与 diff whitespace 检查通过。

| 发现的问题 | 修复结果 |
| --- | --- |
| 已有有效审批时，确认入口跳过参数比较 | 每次确认都与不可变意图比较，金额等参数变化立即拒绝 |
| VALIDATED 中断后无法继续；并发验证可能读到旧状态 | 在同一事务中读取当前状态并推进，恢复到待确认，不倒退 |
| 已完成订单的重复提交先返回回执，跳过账户认证 | 重复提交也认证并绑定实际账户，其他账户不能读取回执 |
| 空卖出响应或错误合约 ID 被补成成功 | 完整合约/交易标识和目标一致性检查，缺失或冲突进入 UNKNOWN |
| 回执交易标识冲突被 INSERT OR IGNORE 静默跳过 | 检查标识冲突；不产生“已成交但无回执”的假状态 |
| 经纪商响应之后落盘失败未立即转 UNKNOWN | 纳入发送后不确定结果处理，不自动重复提交 |
| 自然到期被当作未知 SELL 成功；对账卖出未更新买入订单 | 到期不能单独证明请求卖出；唯一关联的卖出账单可确认结果，卖出回执和买入状态在同一事务提交 |
| 不同 SELL 意图可同时关闭同一合约 | 提交认领事务检查已提交平仓，第二笔不发送 |
| 人工绑定可改变确认的 SELL 目标 | 已知合约 ID 不可改到另一合约，事务内再次检查 |
| 取消或迟到对账可能留下租约、覆盖新结果 | v3 migration 增加 lease_token；取消释放认领，旧任务不能更新新任务 |
| 迟到异常与刷新可能覆盖并发确认或平仓 | 状态更新检查预期状态，保留已经确认的结果 |
| 合约标志字符串被 bool() 解释为真；认证失败漏关连接 | 严格检查合约标志，连接初始化失败也完成关闭 |
| 损益第一页截断连续亏损，重复记录被重复统计 | 覆盖完整尾部亏损序列并按合约去重，冲突或超过读取边界时不提交 |
| 损益记录的 NaN 时间或负金额干扰统计 | 在风险计算前拒绝非有限值与负金额 |
| 替换 Adapter 可能绕过报价金额限制 | TradingService 也检查报价不超过确认金额，提交事务内复核 deadline |

复现与回归位于 `tests/test_execution_review.py`。全部使用本地 SQLite 与假传输；没有真实账户订单或 Jev 调用。[Deriv sell 文档](https://developers.deriv.com/docs/trading/sell/)描述的是提前卖出开放合约，复审保留了“自然到期不能证明某次卖出请求成功”的保守判断。

## 2026-10-07 执行与对账补充审计

在 `427c29b` 的既有执行核心上补充修复，未重写交易流程。新增故障回归先在未修实现上运行：即时回执组出现 4 个失败，账户快照组 34 个失败，对账证据组 26 个失败，随后修复对应边界。

| 问题 | 当前行为 |
| --- | --- |
| 替换 Adapter 的即时回执仅有合约 ID 就被确认 | BUY/SELL 的即时回执同时要求正整数合约和交易 ID；缺失、布尔、字符串、非整数或非正标识保留 UNKNOWN，不重复发送 |
| 负仓位价、非法合约 ID 或重复合约可降低曝光 | 默认 Adapter 和 TradingService 共用账户快照校验，求和和字典去重前拒绝异常；最终预检失败落盘 RISK_DATA_UNAVAILABLE，不提交 |
| BUY 对账接受 SELL 账单；浮点合约 ID 被截断 | 动作须与意图一致；账单 ID 不强制转换，非法证据保持 UNKNOWN |
| 同一合约多笔交易任选第一笔 | 核对唯一 `(contract_id, transaction_id)` 身份；相同身份重复记录可合并，不同身份不能自动确认 |
| UNKNOWN SELL 仅见合约已售出就确认成功 | 必须有归属于本逻辑 SELL 的唯一卖出账单；其他操作关闭合约不会产生本订单的成交回执 |

只读恢复在充分证据下允许缺交易 ID，保留已绑定 BUY 的指定合约核对。回归包含这一兼容约束。

纯计划类型、默认解析常量和 16 个纯解析函数移至 `planning.py`，在 `web_app.py` 保留显式导入兼容入口。迁移前后函数 AST 一致；模型调用、会话、确认与执行没有搬迁。

定向验证：财务执行、风险、账户和对账回归 **149 passed**；原计划、Manager、确认、界面及失败边界回归 **33 passed**；冻结补丁后的完整回归 **261 passed**。本轮新增测试位于 `test_order_engine.py`、`test_reconciliation.py`、`test_account_snapshots.py` 和 `test_reconciliation_evidence.py`。全部使用假传输和临时 SQLite，没有真实 Deriv、Jev 或解释模型调用。

GitHub Actions 在 Python 3.11/3.12 上执行完整回归、离线策略回放和补丁空白检查，关闭实盘写入能力且不配置模型密钥。离线回放只验证策略路由，不是实盘或真实模型验收。
