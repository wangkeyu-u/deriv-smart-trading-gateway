import {
  Activity,
  AlertTriangle,
  AudioWaveform,
  BarChart3,
  Bot,
  BrainCircuit,
  BriefcaseBusiness,
  CandlestickChart,
  ChartNoAxesCombined,
  Check,
  ChevronRight,
  CircleDollarSign,
  Command,
  Database,
  FlaskConical,
  Gauge,
  History,
  KeyRound,
  LayoutDashboard,
  LoaderCircle,
  Menu,
  MessageSquareText,
  Network,
  PanelRightClose,
  PanelRightOpen,
  Plus,
  RadioTower,
  RefreshCw,
  Send,
  Settings2,
  ShieldCheck,
  Sparkles,
  Square,
  TerminalSquare,
  TrendingDown,
  TrendingUp,
  Users,
  Waypoints,
  Wifi,
  X
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type Message = { role: "user" | "assistant"; content: string; streaming?: boolean };
type AgentActivity = {
  id: string;
  name: string;
  state: "queued" | "running" | "done" | "error";
  report?: string;
  kind?: "agent" | "tool";
  durationMs?: number;
};
type RunSummary = {
  runId: string;
  status: "idle" | "running" | "completed" | "degraded" | "failed" | "cancelled" | "interrupted";
  elapsedMs?: number;
  successCount?: number;
  failedCount?: number;
};
type AgentRun = {
  id: string;
  case_id?: string | null;
  created_at: string;
  completed_at?: string | null;
  status: "running" | "completed" | "degraded" | "failed" | "cancelled" | "interrupted";
  provider: string;
  model: string;
  symbol?: string | null;
  route: string[];
  spans: Array<{ agent_id: string; name: string; status: string; duration_ms: number; error_code?: string | null }>;
  elapsed_ms?: number | null;
};
type Provider = "local" | "openai" | "deepseek" | "anthropic" | "compatible";
type CaseSummary = {
  id: string;
  title: string;
  objective?: string;
  symbol: string;
  status: string;
  stage: string;
  version: number;
  updated_at: string;
};
type AgentSpec = { id: string; name: string; prompt: string };
type HealthInfo = {
  ok: boolean;
  runtime: string;
  streaming: string;
  database: string;
  frontend_built: boolean;
};
type MarketData = {
  symbol: string;
  tick?: { quote?: number; epoch?: number } | null;
  candle_count: number;
  window_change_pct?: number | null;
  latest_close?: number | null;
  closes?: number[];
  ok: boolean;
};
type StrategyResult = {
  symbol: string;
  amount: number;
  market: MarketData;
  decision: Record<string, any>;
  budget: Record<string, any>;
  backtest: { ok: boolean; summary?: Record<string, any>; trades?: Record<string, any>[] };
};
type CaseDetail = {
  case: CaseSummary & { objective: string; context: Record<string, any> };
  decision: Record<string, any>;
  events: Array<{ id: number; created_at: string; event_type: string; actor: string; message: string; stage: string; status: string; version: number }>;
};
type ChatSession = { id: string; title: string; created_at: string; updated_at: string; message_count: number; preview: string };

const API = import.meta.env.VITE_API_BASE || "";

const NAV_ITEMS = [
  { id: "command", label: "指挥中心", icon: LayoutDashboard },
  { id: "cases", label: "交易任务", icon: BriefcaseBusiness },
  { id: "advisors", label: "谋士团", icon: Network },
  { id: "markets", label: "行情图表", icon: ChartNoAxesCombined },
  { id: "strategy", label: "小笔策略", icon: FlaskConical },
  { id: "monitor", label: "系统监控", icon: RadioTower }
] as const;

function App() {
  const [active, setActive] = useState("command");
  const [mobileNav, setMobileNav] = useState(false);
  const [rightOpen, setRightOpen] = useState(true);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [sessionsOpen, setSessionsOpen] = useState(false);
  const [provider, setProvider] = useState<Provider>("local");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [sessionId, setSessionId] = useState(localStorage.getItem("gateway-session") || "");
  const [messages, setMessages] = useState<Message[]>([]);
  const [activities, setActivities] = useState<AgentActivity[]>([]);
  const [route, setRoute] = useState<string[]>([]);
  const [symbol, setSymbol] = useState("R_100");
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [health, setHealth] = useState<"checking" | "online" | "offline">("checking");
  const [healthInfo, setHealthInfo] = useState<HealthInfo | null>(null);
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [linkedCase, setLinkedCase] = useState<CaseSummary | null>(null);
  const [agents, setAgents] = useState<AgentSpec[]>([]);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [runSummary, setRunSummary] = useState<RunSummary>({ runId: "", status: "idle" });
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    void bootstrap();
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, activities]);

  async function bootstrap() {
    try {
      const [healthResponse, casesResponse, agentsResponse, runsResponse] = await Promise.all([
        fetch(`${API}/api/health`),
        fetch(`${API}/api/cases`),
        fetch(`${API}/api/agents`),
        fetch(`${API}/api/runs`)
      ]);
      setHealth(healthResponse.ok ? "online" : "offline");
      if (healthResponse.ok) setHealthInfo(await healthResponse.json());
      if (casesResponse.ok) {
        const payload = await casesResponse.json();
        setCases(payload.cases || []);
      }
      if (agentsResponse.ok) {
        const payload = await agentsResponse.json();
        setAgents(payload.agents || []);
      }
      if (runsResponse.ok) {
        const payload = await runsResponse.json();
        setRuns(payload.runs || []);
      }
      let current = sessionId;
      if (!current) {
        const created = await fetch(`${API}/api/chat/session`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title: "Operator conversation" })
        });
        const payload = await created.json();
        current = payload.session_id;
        setSessionId(current);
        localStorage.setItem("gateway-session", current);
      }
      const history = await fetch(`${API}/api/chat/history/${current}`);
      if (history.ok) {
        const payload = await history.json();
        if (payload.session_id && payload.session_id !== current) {
          current = payload.session_id;
          setSessionId(current);
          localStorage.setItem("gateway-session", current);
        }
        setMessages((payload.messages || []).map((item: Message) => ({ role: item.role, content: item.content })));
      }
      await refreshSessions();
    } catch {
      setHealth("offline");
    }
  }

  async function newConversation() {
    if (streaming) abortRef.current?.abort();
    const response = await fetch(`${API}/api/chat/session`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: "Operator conversation" })
    });
    const payload = await response.json();
    setSessionId(payload.session_id);
    localStorage.setItem("gateway-session", payload.session_id);
    setMessages([]);
    setActivities([]);
    setRoute([]);
    setRunSummary({ runId: "", status: "idle" });
    setLinkedCase(null);
    await refreshSessions();
  }

  async function refreshCases() {
    const response = await fetch(`${API}/api/cases`);
    if (!response.ok) return;
    const payload = await response.json();
    const nextCases = payload.cases || [];
    setCases(nextCases);
    setLinkedCase((current) => {
      if (!current) return null;
      return nextCases.find((item: CaseSummary) => item.id === current.id) || current;
    });
  }

  async function refreshSessions() {
    const response = await fetch(`${API}/api/chat/sessions`);
    if (response.ok) {
      const payload = await response.json();
      setSessions(payload.sessions || []);
    }
  }

  async function refreshRuns() {
    const response = await fetch(`${API}/api/runs`);
    if (!response.ok) return;
    const payload = await response.json();
    setRuns(payload.runs || []);
  }

  async function switchSession(nextId: string) {
    if (streaming) abortRef.current?.abort();
    const response = await fetch(`${API}/api/chat/history/${nextId}`);
    if (!response.ok) return;
    const payload = await response.json();
    setSessionId(payload.session_id);
    localStorage.setItem("gateway-session", payload.session_id);
    setMessages((payload.messages || []).map((item: Message) => ({ role: item.role, content: item.content })));
    setActivities([]);
    setRoute([]);
    setRunSummary({ runId: "", status: "idle" });
    setLinkedCase(null);
    setSessionsOpen(false);
    setActive("command");
  }

  function upsertActivity(next: AgentActivity) {
    setActivities((current) => {
      const exists = current.some((item) => item.id === next.id);
      return exists ? current.map((item) => (item.id === next.id ? { ...item, ...next } : item)) : [...current, next];
    });
  }

  function stopStreaming() {
    abortRef.current?.abort();
    setRunSummary((current) => ({ ...current, status: "cancelled" }));
    setActivities((current) => current.map((item) => item.state === "running" ? { ...item, state: "error", report: "已由用户停止" } : item));
  }

  async function sendMessage(event: FormEvent) {
    event.preventDefault();
    const prompt = input.trim();
    if (!prompt || streaming) return;
    if (provider !== "local" && !apiKey.trim()) {
      setSettingsOpen(true);
      return;
    }
    setInput("");
    setActivities([]);
    setRoute([]);
    setRunSummary({ runId: "", status: "idle" });
    setMessages((current) => [...current, { role: "user", content: prompt }, { role: "assistant", content: "", streaming: true }]);
    setStreaming(true);
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const response = await fetch(`${API}/api/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        signal: controller.signal,
        body: JSON.stringify({
          message: prompt,
          session_id: sessionId,
          case_id: linkedCase?.id || null,
          provider,
          api_key: apiKey,
          model,
          base_url: baseUrl,
          language: "zh"
        })
      });
      if (!response.ok || !response.body) {
        throw new Error((await response.text()) || "流式连接失败");
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() || "";
        for (const frame of frames) {
          const line = frame.split("\n").find((part) => part.startsWith("data: "));
          if (!line) continue;
          const payload = JSON.parse(line.slice(6));
          handleStreamEvent(payload);
        }
      }
    } catch (error) {
      if ((error as Error).name !== "AbortError") {
        const text = error instanceof Error ? error.message : "流式连接失败";
        setMessages((current) => current.map((item, index) => index === current.length - 1 ? { ...item, content: `连接失败：${text}`, streaming: false } : item));
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
      setMessages((current) => current.map((item) => ({ ...item, streaming: false })));
      void refreshSessions();
      void refreshRuns();
      if (linkedCase) void refreshCases();
    }
  }

  function handleStreamEvent(payload: any) {
    if (payload.type === "session" && payload.session_id) {
      setSessionId(payload.session_id);
      localStorage.setItem("gateway-session", payload.session_id);
    }
    if (payload.type === "start") {
      setRoute(payload.route || []);
      setSymbol(payload.symbol || "R_100");
      setRunSummary({ runId: payload.run_id || "", status: "running" });
    }
    if (payload.type === "agent_start") {
      upsertActivity({ id: payload.agent_id, name: payload.name, state: "running" });
    }
    if (payload.type === "agent_done") {
      upsertActivity({ id: payload.agent_id, name: payload.name, state: "done", report: payload.report, durationMs: payload.duration_ms });
    }
    if (payload.type === "agent_error") {
      upsertActivity({ id: payload.agent_id, name: payload.name, state: "error", report: payload.message || payload.report, durationMs: payload.duration_ms });
    }
    if (payload.type === "tool_start") {
      upsertActivity({ id: `tool:${payload.tool}`, name: payload.label || payload.tool, state: "running", kind: "tool" });
    }
    if (payload.type === "tool_done") {
      upsertActivity({ id: `tool:${payload.tool}`, name: payload.label || "行情数据读取", state: payload.ok ? "done" : "error", kind: "tool", report: payload.ok ? "数据已返回并通过基础检查" : payload.error || "数据读取不完整", durationMs: payload.duration_ms });
    }
    if (payload.type === "manager_fallback") {
      upsertActivity({ id: "manager:fallback", name: "经理降级总结", state: "error", kind: "tool", report: "主模型总结未完成，已使用本地安全摘要继续返回结果。" });
    }
    if (payload.type === "case_updated" && payload.case) {
      const updated = payload.case as CaseSummary;
      setCases((current) => {
        const exists = current.some((item) => item.id === updated.id);
        return exists
          ? current.map((item) => item.id === updated.id ? { ...item, ...updated } : item)
          : [updated, ...current];
      });
      setLinkedCase((current) => current?.id === updated.id ? { ...current, ...updated } : current);
      upsertActivity({ id: `case:${updated.id}`, name: `任务同步 · ${updated.stage}`, state: "done", kind: "tool", report: `${updated.id} 已写入本地数据库，当前版本 v${updated.version}` });
    }
    if (payload.type === "answer_delta") {
      setMessages((current) => current.map((item, index) => index === current.length - 1 ? { ...item, content: item.content + payload.delta } : item));
    }
    if (payload.type === "error") {
      setRunSummary((current) => ({ ...current, status: "failed" }));
      setMessages((current) => current.map((item, index) => index === current.length - 1 ? { ...item, content: `运行失败：${payload.message}`, streaming: false } : item));
    }
    if (payload.type === "done") {
      const failedCount = (payload.failed_agents || []).length;
      setRunSummary({
        runId: payload.run_id || "",
        status: failedCount || payload.manager_fallback ? "degraded" : "completed",
        elapsedMs: payload.elapsed_ms,
        successCount: (payload.successful_agents || []).length,
        failedCount
      });
    }
  }

  const providerLabel = useMemo(() => ({
    local: "本地规则",
    openai: "OpenAI",
    deepseek: "DeepSeek",
    anthropic: "Anthropic",
    compatible: "兼容 API"
  }[provider]), [provider]);

  return (
    <div className="app-shell">
      <aside className={`side-nav ${mobileNav ? "side-nav--open" : ""}`}>
        <div className="brand-block">
          <div className="brand-mark"><Waypoints size={20} /></div>
          <div><strong>DERIV GATEWAY</strong><span>Agent Operations</span></div>
          <button className="icon-btn mobile-only" onClick={() => setMobileNav(false)} aria-label="关闭导航"><X size={18} /></button>
        </div>
        <nav>
          <p className="nav-caption">WORKSPACE</p>
          {NAV_ITEMS.map((item) => (
            <button key={item.id} className={`nav-item ${active === item.id ? "nav-item--active" : ""}`} aria-current={active === item.id ? "page" : undefined} onClick={() => { setActive(item.id); setMobileNav(false); }}>
              <item.icon size={18} /><span>{item.label}</span>{active === item.id && <ChevronRight size={16} />}
            </button>
          ))}
        </nav>
        <div className="nav-bottom">
          <button className="nav-item" onClick={() => setSettingsOpen(true)}><Settings2 size={18} /><span>模型与密钥</span></button>
          <div className="runtime-line"><span className={`status-dot status-dot--${health}`} /> FastAPI · {health === "online" ? "ONLINE" : "OFFLINE"}</div>
        </div>
      </aside>

      <main className="main-stage">
        <header className="top-bar">
          <button className="icon-btn mobile-only" onClick={() => setMobileNav(true)} aria-label="打开导航"><Menu size={19} /></button>
          <div className="top-title"><span>{NAV_ITEMS.find((item) => item.id === active)?.label}</span><small>多 Agent 实时协作与人工交易闸门</small></div>
          <div className="top-status">
            <span className="market-chip"><AudioWaveform size={14} /> {symbol}</span>
            <span className="model-chip"><Sparkles size={14} /> {providerLabel}</span>
            <button className="icon-btn" onClick={() => setRightOpen((value) => !value)} aria-label="切换活动面板">
              {rightOpen ? <PanelRightClose size={18} /> : <PanelRightOpen size={18} />}
            </button>
          </div>
        </header>

        {active === "command" && (
          <section className={`command-layout view-enter ${rightOpen ? "" : "command-layout--wide"}`}>
            <div className="conversation-panel">
              <div className="conversation-head">
                <div className="conversation-title"><p className="eyebrow">LIVE ORCHESTRATION</p><h1>老板指挥台</h1>{linkedCase && <div className="linked-case"><BriefcaseBusiness size={15} /><div><strong>{linkedCase.title}</strong><span>{linkedCase.symbol} · {humanStage(linkedCase.stage)} · v{linkedCase.version}</span></div><button type="button" onClick={() => setLinkedCase(null)} aria-label="解除交易任务绑定"><X size={14} /></button></div>}</div>
                <div className="conversation-actions"><button className="icon-btn" onClick={() => { void refreshSessions(); setSessionsOpen(true); }} aria-label="历史对话"><History size={17} /></button><button className="text-btn" onClick={newConversation}><Plus size={16} /> 新对话</button></div>
              </div>
              <div className="conversation-scroll" ref={scrollRef}>
                {messages.length === 0 ? <EmptyConversation onPick={setInput} /> : messages.map((message, index) => <MessageBubble key={`${index}-${message.role}`} message={message} />)}
              </div>
              <form className="composer" onSubmit={sendMessage}>
                <textarea value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); }
                }} placeholder="告诉经理你要分析什么。Enter 发送，Shift + Enter 换行。" rows={3} />
                <div className="composer-footer">
                  <div className="composer-meta"><ShieldCheck size={15} /> 默认只分析，不自动成交</div>
                  {streaming ? (
                    <button type="button" className="send-btn send-btn--stop" onClick={stopStreaming}><Square size={15} fill="currentColor" /> 停止</button>
                  ) : (
                    <button type="submit" className="send-btn" disabled={!input.trim()}><Send size={16} /> 发送</button>
                  )}
                </div>
              </form>
            </div>
            {rightOpen && <AgentRail activities={activities} route={route} run={runSummary} provider={providerLabel} cases={cases} onSettings={() => setSettingsOpen(true)} />}
          </section>
        )}

        {active !== "command" && <ModuleView id={active} cases={cases} agents={agents} runs={runs} health={healthInfo} provider={providerLabel} onCasesChange={setCases} onDispatch={(caseItem) => { setLinkedCase(caseItem); setSymbol(caseItem.symbol); setInput(`请接手交易任务 ${caseItem.id}：${caseItem.objective}。先让谋士团和行情 Agent 分析 ${caseItem.symbol}，把行情、结论和风控要求同步回任务。`); setActive("command"); }} onBack={() => setActive("command")} />}
      </main>

      {settingsOpen && (
        <SettingsDrawer provider={provider} setProvider={setProvider} apiKey={apiKey} setApiKey={setApiKey} model={model} setModel={setModel} baseUrl={baseUrl} setBaseUrl={setBaseUrl} onClose={() => setSettingsOpen(false)} />
      )}
      {sessionsOpen && <SessionDrawer sessions={sessions} currentId={sessionId} onSelect={switchSession} onNew={async () => { await newConversation(); setSessionsOpen(false); }} onClose={() => setSessionsOpen(false)} />}
    </div>
  );
}

function EmptyConversation({ onPick }: { onPick: (value: string) => void }) {
  const prompts = [
    "让谋士团分析 R_75 接下来 10 分钟的风险和机会",
    "检查 R_100 行情，然后给我一个不超过 1 美元的纸面策略",
    "解释最近一次交易任务为什么被风控拦截"
  ];
  return <div className="empty-state">
    <div className="empty-symbol"><Bot size={28} /></div>
    <p className="eyebrow">READY FOR ORDERS</p>
    <h2>经理和团队已就位</h2>
    <p>你的指令会被拆给策略、行情、风控、合规和报告 Agent。处理过程与最终回答都会实时出现。</p>
    <div className="prompt-grid">{prompts.map((prompt) => <button key={prompt} onClick={() => onPick(prompt)}>{prompt}<ChevronRight size={15} /></button>)}</div>
  </div>;
}

function MessageBubble({ message }: { message: Message }) {
  return <article className={`message message--${message.role}`}>
    <div className="message-avatar">{message.role === "assistant" ? <Bot size={17} /> : <span>你</span>}</div>
    <div className="message-body">
      <div className="message-label">{message.role === "assistant" ? "交易经理" : "老板"}</div>
      <div className="message-content">{message.content ? (message.role === "assistant" ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown> : message.content) : (message.streaming ? <span className="typing"><i /><i /><i /></span> : "")}{message.streaming && message.content && <span className="stream-caret" />}</div>
    </div>
  </article>;
}

function AgentRail({ activities, route, run, provider, cases, onSettings }: { activities: AgentActivity[]; route: string[]; run: RunSummary; provider: string; cases: CaseSummary[]; onSettings: () => void }) {
  return <aside className="agent-rail">
    <section className="rail-section">
      <div className="rail-heading"><div><p className="eyebrow">AGENT ACTIVITY</p><h2>实时协作</h2></div><span className="live-badge"><i /> LIVE</span></div>
      {run.status !== "idle" && <div className={`trace-strip trace-strip--${run.status}`}>
        <div><span>运行</span><code>{run.runId || "正在创建"}</code></div>
        <strong>{humanRunStatus(run.status)}</strong>
        <div className="trace-metrics"><span>{run.elapsedMs == null ? "计时中" : formatDuration(run.elapsedMs)}</span><span>{run.successCount ?? 0} 成功</span><span>{run.failedCount ?? 0} 降级</span></div>
      </div>}
      {activities.length === 0 ? <div className="quiet-state"><Activity size={20} /><span>发送指令后，这里会显示每个 Agent 的工作状态。</span></div> : <div className="activity-list">{activities.map((item) => <div className="activity-item" key={item.id}>
        <div className={`activity-icon activity-icon--${item.state}`}>{item.state === "running" ? <LoaderCircle size={15} className="spin" /> : item.state === "error" ? <AlertTriangle size={15} /> : <Check size={15} />}</div>
        <div><strong>{item.name}{item.durationMs != null && <em>{formatDuration(item.durationMs)}</em>}</strong><span>{item.state === "running" ? (item.kind === "tool" ? "正在调用工具" : "正在分析") : item.report || "完成"}</span></div>
      </div>)}</div>}
      {route.length > 0 && <div className="route-strip"><span>ROUTE</span><code>{route.join(" → ")}</code></div>}
    </section>
    <section className="rail-section connection-card">
      <div className="connection-row"><div className="connection-icon"><KeyRound size={17} /></div><div><span>模型连接</span><strong>{provider}</strong></div><button className="icon-btn" onClick={onSettings}><Settings2 size={16} /></button></div>
      <div className="connection-row"><div className="connection-icon"><Database size={17} /></div><div><span>本地记忆</span><strong>SQLite 已连接</strong></div><span className="ok-dot" /></div>
    </section>
    <section className="rail-section case-preview">
      <div className="rail-heading"><div><p className="eyebrow">TRADE CASES</p><h2>最近任务</h2></div><span>{cases.length}</span></div>
      {cases.slice(0, 3).map((item) => <div className="case-row" key={item.id}><div><strong>{item.symbol}</strong><span>{item.title}</span></div><em>{item.status}</em></div>)}
      {cases.length === 0 && <div className="quiet-state compact"><CircleDollarSign size={18} /><span>暂无交易任务</span></div>}
    </section>
  </aside>;
}

function ModuleView({ id, cases, agents, runs, health, provider, onCasesChange, onDispatch, onBack }: { id: string; cases: CaseSummary[]; agents: AgentSpec[]; runs: AgentRun[]; health: HealthInfo | null; provider: string; onCasesChange: (cases: CaseSummary[]) => void; onDispatch: (caseItem: CaseDetail["case"]) => void; onBack: () => void }) {
  const item = NAV_ITEMS.find((nav) => nav.id === id)!;
  const descriptions: Record<string, string> = {
    cases: "持久化跟踪谋士、行情、回测、风控、确认和成交复盘。",
    advisors: "多位独立谋士使用各自 Prompt 分析同一问题，由首席谋士汇总。",
    markets: "实时 Tick、完整 K 线、数据时效与指标验证。",
    strategy: "严格预算下的小额纸面交易、回测和熔断。",
    monitor: "服务健康、Agent 路由、模型连接和本地持久化状态。"
  };
  return <section className="module-page view-enter">
    <div className="module-title"><div className="module-icon"><item.icon size={22} /></div><div><p className="eyebrow">OPERATOR MODULE</p><h1>{item.label}</h1><p>{descriptions[id]}</p></div><button className="text-btn" onClick={onBack}><MessageSquareText size={16} /> 返回指挥台</button></div>
    {id === "cases" && <CaseModule cases={cases} onCasesChange={onCasesChange} onDispatch={onDispatch} />}
    {id === "advisors" && <AdvisorModule agents={agents} />}
    {id === "markets" && <MarketModule />}
    {id === "strategy" && <StrategyModule />}
    {id === "monitor" && <MonitorModule health={health} provider={provider} agentCount={agents.length} runs={runs} />}
  </section>;
}

function CaseModule({ cases, onCasesChange, onDispatch }: { cases: CaseSummary[]; onCasesChange: (cases: CaseSummary[]) => void; onDispatch: (caseItem: CaseDetail["case"]) => void }) {
  const [selectedId, setSelectedId] = useState(cases[0]?.id || "");
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [objective, setObjective] = useState("");
  const [symbol, setSymbol] = useState("R_75");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  const selectedVersion = cases.find((item) => item.id === selectedId)?.version;
  useEffect(() => { if (selectedId) void loadDetail(selectedId); else setDetail(null); }, [selectedId, selectedVersion]);
  useEffect(() => { if (!selectedId && cases[0]) setSelectedId(cases[0].id); }, [cases, selectedId]);

  async function loadDetail(caseId: string) {
    const response = await fetch(`${API}/api/cases/${caseId}`);
    if (response.ok) setDetail(await response.json());
  }

  async function createCase(event: FormEvent) {
    event.preventDefault();
    if (!objective.trim()) return;
    setCreating(true); setError("");
    try {
      const response = await fetch(`${API}/api/cases`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ objective, symbol }) });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "任务创建失败");
      const created = payload.case as CaseDetail["case"];
      const summary: CaseSummary = { id: created.id, title: created.title, symbol: created.symbol, status: created.status, stage: created.stage, version: created.version, updated_at: created.updated_at };
      onCasesChange([summary, ...cases]);
      setObjective(""); setSelectedId(created.id);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "任务创建失败"); }
    finally { setCreating(false); }
  }

  return <div className="case-workbench">
    <aside className="case-index">
      <form className="case-create" onSubmit={createCase}><p className="eyebrow">NEW TRADE CASE</p><textarea value={objective} onChange={(event) => setObjective(event.target.value)} placeholder="例如：用不超过 1 美元验证 R_75 的短线机会" rows={3} /><div><input value={symbol} onChange={(event) => setSymbol(event.target.value.toUpperCase())} aria-label="任务交易品种" /><button className="action-btn" disabled={creating || !objective.trim()}>{creating ? <LoaderCircle className="spin" size={15} /> : <Plus size={15} />} 新建</button></div>{error && <span className="form-error">{error}</span>}</form>
      <div className="case-stack">{cases.map((item) => <button key={item.id} className={selectedId === item.id ? "active" : ""} onClick={() => setSelectedId(item.id)}><div><strong>{item.title}</strong><code>{item.symbol}</code></div><span>{humanStage(item.stage)}</span><small>{humanCaseStatus(item.status)} · v{item.version}</small></button>)}{cases.length === 0 && <div className="module-empty">还没有任务。</div>}</div>
    </aside>
    <section className="case-detail">{detail ? <><div className="case-detail-head"><div><p className="eyebrow">{detail.case.id}</p><h2>{detail.case.title}</h2><p>{detail.case.objective}</p></div><button className="action-btn" onClick={() => onDispatch(detail.case)}><Bot size={16} /> 交给经理分析</button></div><div className="case-status-band"><Metric label="市场" value={detail.case.symbol} /><Metric label="阶段" value={humanStage(detail.case.stage)} /><Metric label="状态" value={humanCaseStatus(detail.case.status)} /><Metric label="同步版本" value={`v${detail.case.version}`} /></div><div className="case-decision"><p className="eyebrow">决策快照</p><h3>{caseDecisionSummary(detail.decision)}</h3><div className="case-evidence"><Evidence label="谋士结论" value={detail.decision.advisor?.action ? humanAction(detail.decision.advisor.action) : "尚未运行"} /><Evidence label="最新行情" value={detail.decision.market?.latest_close == null ? "尚未读取" : `${detail.case.symbol} · ${formatNumber(detail.decision.market.latest_close)}`} /><Evidence label="纸面交易" value={`${detail.decision.paper?.trade_count || 0} 次`} /><Evidence label="下一步" value={humanWorkflowStep(detail.decision.workflow_step)} /></div></div><div className="case-timeline"><p className="eyebrow">审计时间线</p>{detail.events.map((event) => <div key={event.id}><span>{new Date(event.created_at).toLocaleString()}</span><strong>{humanEventMessage(event.message)}</strong><code>{humanStage(event.stage)} · v{event.version}</code></div>)}</div></> : <div className="module-empty large"><CircleDollarSign size={30} /><h2>选择或创建交易任务</h2><p>任务会保存目标、证据、同步版本和完整审计记录。</p></div>}</section>
  </div>;
}

function AdvisorModule({ agents }: { agents: AgentSpec[] }) {
  return <div className="advisor-list">
    <div className="advisor-list-head"><span>Agent</span><span>职责与独立 Prompt</span><span>状态</span></div>
    {agents.map((agent, index) => <article className="advisor-row" key={agent.id}>
      <div className="advisor-identity"><span>{String(index + 1).padStart(2, "0")}</span><div><strong>{agent.name || agent.id}</strong><code>{agent.id}</code></div></div>
      <p>{agent.prompt || "使用默认职责分析并向交易经理提交报告。"}</p>
      <em><span className="ok-dot" /> 已加载</em>
    </article>)}
    {agents.length === 0 && <div className="module-empty">Agent Prompt 注册表暂时不可用。</div>}
  </div>;
}

function MarketModule() {
  const symbols = ["R_10", "R_25", "R_50", "R_75", "R_100", "BOOM500", "CRASH500"];
  const [selected, setSelected] = useState("R_75");
  const [market, setMarket] = useState<MarketData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function loadMarket() {
    setLoading(true); setError("");
    try {
      const response = await fetch(`${API}/api/market/${encodeURIComponent(selected)}`);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "行情读取失败");
      setMarket(payload.market);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "行情读取失败");
    } finally { setLoading(false); }
  }

  return <div className="work-surface">
    <div className="control-strip"><label>交易品种<select value={selected} onChange={(event) => setSelected(event.target.value)}>{symbols.map((value) => <option key={value}>{value}</option>)}</select></label><button className="action-btn" onClick={loadMarket} disabled={loading}>{loading ? <LoaderCircle className="spin" size={16} /> : <RefreshCw size={16} />} 获取最新行情</button></div>
    {error && <div className="inline-alert"><AlertTriangle size={17} />{error}</div>}
    {!market && !error && <div className="module-empty large"><CandlestickChart size={30} /><h2>选择市场并读取行情</h2><p>系统会同时获取最新 Tick 和 60 根 K 线，不会执行任何交易。</p></div>}
    {market && <MarketSnapshot market={market} />}
  </div>;
}

function MarketSnapshot({ market }: { market: MarketData }) {
  const change = Number(market.window_change_pct || 0);
  const values = market.closes || [];
  const width = 900, height = 250;
  const min = Math.min(...values), max = Math.max(...values);
  const points = values.map((value, index) => `${(index / Math.max(values.length - 1, 1)) * width},${height - ((value - min) / Math.max(max - min, 0.000001)) * (height - 24) - 12}`).join(" ");
  return <div className="market-result">
    <div className="metric-band"><Metric label="最新价格" value={formatNumber(market.tick?.quote ?? market.latest_close)} /><Metric label="60 分钟变化" value={`${change >= 0 ? "+" : ""}${change.toFixed(3)}%`} tone={change >= 0 ? "positive" : "negative"} /><Metric label="K 线数量" value={String(market.candle_count)} /><Metric label="数据状态" value={market.ok ? "实时可用" : "不完整"} tone={market.ok ? "positive" : "warning"} /></div>
    <div className="chart-panel"><div className="chart-heading"><div><strong>{market.symbol}</strong><span>最近 60 根 1 分钟收盘价</span></div>{change >= 0 ? <TrendingUp size={22} /> : <TrendingDown size={22} />}</div>{values.length > 1 ? <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${market.symbol} 收盘价趋势`}><polyline className="market-line" pathLength="1" points={points} fill="none" stroke={change >= 0 ? "#69d6b3" : "#ed7b72"} strokeWidth="3" vectorEffect="non-scaling-stroke" /></svg> : <div className="module-empty">没有足够数据绘图。</div>}</div>
  </div>;
}

function StrategyModule() {
  const [symbol, setSymbol] = useState("R_75");
  const [amount, setAmount] = useState(1);
  const [result, setResult] = useState<StrategyResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function analyze() {
    setLoading(true); setError("");
    try {
      const response = await fetch(`${API}/api/strategy/analyze`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ symbol, amount }) });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "策略分析失败");
      setResult(payload);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "策略分析失败"); }
    finally { setLoading(false); }
  }

  const decision = result?.decision || {};
  const summary = result?.backtest?.summary || {};
  return <div className="work-surface">
    <div className="control-strip strategy-controls"><label>交易品种<input value={symbol} onChange={(event) => setSymbol(event.target.value.toUpperCase())} /></label><label>单笔上限（USD）<input type="number" min="0.1" max="10" step="0.1" value={amount} onChange={(event) => setAmount(Number(event.target.value))} /></label><button className="action-btn" onClick={analyze} disabled={loading}>{loading ? <LoaderCircle className="spin" size={16} /> : <BarChart3 size={16} />} 分析并纸面回测</button></div>
    <div className="safety-line"><ShieldCheck size={16} />这里只读取行情、计算信号和纸面回测，不会提交订单。</div>
    {error && <div className="inline-alert"><AlertTriangle size={17} />{error}</div>}
    {!result && !error && <div className="module-empty large"><BrainCircuit size={30} /><h2>输入品种和严格预算</h2><p>你会得到当前动作、信心、阻断原因、风险参数和历史窗口纸面结果。</p></div>}
    {result && <div className="strategy-result">
      <div className="decision-banner"><div><span>当前建议</span><strong>{humanAction(decision.action)}</strong></div><div><span>信心</span><strong>{Math.round(Number(decision.confidence || 0) * 100)}%</strong></div><div><span>最新价</span><strong>{formatNumber(decision.latest_price)}</strong></div><div><span>预算检查</span><strong>{result.budget.ok ? "通过" : "拦截"}</strong></div></div>
      <div className="evidence-grid"><section><p className="eyebrow">为什么</p><h2>信号证据</h2><Evidence label="3 根动量" value={`${Number(decision.momentum_3_pct || 0).toFixed(4)}%`} /><Evidence label="7 根动量" value={`${Number(decision.momentum_7_pct || 0).toFixed(4)}%`} /><Evidence label="波动率" value={`${Number(decision.volatility_pct || 0).toFixed(4)}%`} /><Evidence label="阻断原因" value={(decision.blockers || []).length ? decision.blockers.join("、") : "无"} /></section><section><p className="eyebrow">纸面结果</p><h2>窗口回测</h2><Evidence label="交易次数" value={String(summary.trade_count ?? 0)} /><Evidence label="胜率" value={summary.win_rate == null ? "暂无交易" : `${(Number(summary.win_rate) * 100).toFixed(1)}%`} /><Evidence label="累计 PnL" value={formatNumber(summary.total_pnl, 6)} /><Evidence label="熔断" value={summary.halted ? `是：${summary.halt_reason}` : "否"} /></section></div>
    </div>}
  </div>;
}

function MonitorModule({ health, provider, agentCount, runs }: { health: HealthInfo | null; provider: string; agentCount: number; runs: AgentRun[] }) {
  const checks = [
    { label: "API 服务", value: health?.ok ? "在线" : "未连接", detail: health?.runtime || "FastAPI", icon: RadioTower },
    { label: "回答传输", value: health?.streaming === "sse" ? "真流式" : "待检查", detail: "Server-Sent Events", icon: AudioWaveform },
    { label: "本地记忆", value: health?.database ? "已连接" : "待检查", detail: health?.database || "SQLite", icon: Database },
    { label: "Agent 注册", value: `${agentCount} 个`, detail: "独立 Prompt 与独立调用", icon: Network },
    { label: "当前模型", value: provider, detail: "密钥仅驻留当前页面内存", icon: Sparkles },
    { label: "前端构建", value: health?.frontend_built ? "已加载" : "待构建", detail: "React + Vite", icon: LayoutDashboard }
  ];
  return <div className="monitor-stack">
    <div className="monitor-grid">{checks.map((check, index) => <article key={check.label} style={{ animationDelay: `${index * 45}ms` }}><div className="monitor-icon"><check.icon size={18} /></div><span>{check.label}</span><strong>{check.value}</strong><small>{check.detail}</small></article>)}</div>
    <section className="run-ledger">
      <div className="run-ledger-head"><div><p className="eyebrow">PERSISTENT RUN TRACE</p><h2>最近 Agent 运行</h2></div><span>刷新后仍保留</span></div>
      <div className="run-ledger-table">
        <div className="run-ledger-row run-ledger-labels"><span>运行 / 时间</span><span>状态</span><span>目标</span><span>Agent</span><span>耗时</span></div>
        {runs.slice(0, 12).map((run) => {
          const completed = run.spans.filter((span) => span.status === "completed").length;
          const failed = run.spans.filter((span) => span.status !== "completed").length;
          return <div className="run-ledger-row" key={run.id}>
            <div><code>{run.id}</code><small>{new Date(run.created_at).toLocaleString()}</small></div>
            <span className={`run-status run-status--${run.status}`}>{humanRunStatus(run.status)}</span>
            <div><strong>{run.symbol || "--"}</strong><small>{run.provider} · {run.model}</small></div>
            <span>{completed} 成功{failed ? ` / ${failed} 降级` : ""}</span>
            <span>{run.elapsed_ms == null ? "运行中" : formatDuration(run.elapsed_ms)}</span>
          </div>;
        })}
        {runs.length === 0 && <div className="module-empty">还没有 Agent 运行记录。完成一次指令后，这里会形成可追溯账本。</div>}
      </div>
    </section>
  </div>;
}

function Metric({ label, value, tone = "" }: { label: string; value: string; tone?: string }) { return <div className={`metric metric--${tone}`}><span>{label}</span><strong>{value}</strong></div>; }
function Evidence({ label, value }: { label: string; value: string }) { return <div className="evidence-row"><span>{label}</span><strong>{value}</strong></div>; }
function formatNumber(value: unknown, digits = 5) { const number = Number(value); return Number.isFinite(number) ? number.toFixed(digits).replace(/\.?0+$/, "") : "--"; }
function humanAction(action: unknown) { return ({ CALL: "看涨（CALL）", PUT: "看跌（PUT）", WAIT: "等待，不入场", BUY: "买入", SELL: "卖出", HOLD: "持有" } as Record<string, string>)[String(action)] || String(action || "无信号"); }
function humanRunStatus(status: unknown) { return ({ idle: "待命", running: "运行中", completed: "已完成", degraded: "降级完成", failed: "失败", cancelled: "已停止", interrupted: "重启中断" } as Record<string, string>)[String(status)] || String(status); }
function formatDuration(value: number) { return value < 1000 ? `${value} ms` : `${(value / 1000).toFixed(value < 10_000 ? 1 : 0)} s`; }
function humanStage(stage: unknown) { return ({ draft: "任务草稿", advisor_review: "谋士分析", market_validation: "行情验证", micro_backtest: "纸面回测", risk_review: "风控复核", awaiting_confirmation: "等待确认", execution: "执行中", review: "复盘" } as Record<string, string>)[String(stage)] || String(stage || "未知"); }
function humanCaseStatus(status: unknown) { return ({ active: "进行中", paused: "已暂停", completed: "已完成", cancelled: "已取消", failed: "失败" } as Record<string, string>)[String(status)] || String(status || "未知"); }
function humanWorkflowStep(step: unknown) { return ({ manager_dispatch: "经理调度", advisor_review: "谋士分析", market_validation: "行情验证", micro_backtest: "小笔策略回测", risk_review: "风控复核", human_confirmation: "人工确认" } as Record<string, string>)[String(step)] || "等待经理安排"; }
function humanEventMessage(message: string) { return ({ "Trade case created": "交易任务已创建" } as Record<string, string>)[message] || message; }
function caseDecisionSummary(decision: Record<string, any>) {
  const status = String(decision.status || "not_started");
  if (status === "not_started") return "任务已记录，等待经理开始组织分析。";
  if (status === "awaiting_confirmation") return "证据链已通过检查，正在等待人工确认。";
  if (status === "blocked") return `任务被安全闸门拦截：${(decision.gate?.blockers || []).join("、") || "需要补充证据"}`;
  if (status === "failed") return `任务运行失败，可从 ${decision.retry_step || "失败步骤"} 重试。`;
  if (status === "completed") return "任务已经完成，结果和回执已进入审计记录。";
  if (decision.workflow_step === "micro_backtest") return "谋士结论和行情证据已保存。下一步请到小笔策略完成纸面回测，再进入风控确认。";
  return `任务正在 ${decision.stage || "分析"} 阶段推进。`;
}

function SessionDrawer({ sessions, currentId, onSelect, onNew, onClose }: { sessions: ChatSession[]; currentId: string; onSelect: (id: string) => void; onNew: () => void; onClose: () => void }) {
  return <div className="drawer-layer drawer-layer--left" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <aside className="session-drawer">
      <div className="drawer-head"><div><p className="eyebrow">LOCAL MEMORY</p><h2>历史对话</h2></div><button className="icon-btn" onClick={onClose} aria-label="关闭历史对话"><X size={18} /></button></div>
      <button className="primary-wide" onClick={onNew}><Plus size={17} /> 开始新对话</button>
      <div className="session-list">{sessions.map((session) => <button key={session.id} className={session.id === currentId ? "active" : ""} onClick={() => onSelect(session.id)}><div className="session-icon"><MessageSquareText size={16} /></div><div><strong>{session.title}</strong><span>{session.preview || "尚无消息"}</span><small>{session.message_count} 条消息 · {relativeTime(session.updated_at)}</small></div></button>)}{sessions.length === 0 && <div className="module-empty">还没有历史对话。</div>}</div>
      <div className="session-foot"><Database size={15} /><span>全部会话仅保存在本机 SQLite</span></div>
    </aside>
  </div>;
}

function relativeTime(value: string) {
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 60) return "刚刚";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`;
  return `${Math.floor(seconds / 86400)} 天前`;
}

function SettingsDrawer({ provider, setProvider, apiKey, setApiKey, model, setModel, baseUrl, setBaseUrl, onClose }: {
  provider: Provider; setProvider: (value: Provider) => void; apiKey: string; setApiKey: (value: string) => void; model: string; setModel: (value: string) => void; baseUrl: string; setBaseUrl: (value: string) => void; onClose: () => void;
}) {
  return <div className="drawer-layer" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <aside className="settings-drawer">
      <div className="drawer-head"><div><p className="eyebrow">RUNTIME SETTINGS</p><h2>模型与密钥</h2></div><button className="icon-btn" onClick={onClose}><X size={18} /></button></div>
      <div className="security-note"><ShieldCheck size={17} /><span>API Key 只发送到本机 FastAPI 进程，不写入 SQLite，也不会出现在日志中。</span></div>
      <label>模型提供商<select value={provider} onChange={(event) => setProvider(event.target.value as Provider)}><option value="local">本地规则</option><option value="openai">OpenAI</option><option value="deepseek">DeepSeek</option><option value="anthropic">Anthropic</option><option value="compatible">OpenAI-Compatible</option></select></label>
      {provider !== "local" && <label>API Key<input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="sk-..." autoComplete="off" /></label>}
      <label>模型名<input value={model} onChange={(event) => setModel(event.target.value)} placeholder={provider === "local" ? "local-rule-engine" : "留空使用默认模型"} /></label>
      {provider === "compatible" && <label>Base URL<input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://your-api.example/v1" /></label>}
      <div className="drawer-agent-note"><BrainCircuit size={18} /><div><strong>每个 Agent 独立调用</strong><span>策略、行情、风控、合规和报告 Agent 分别使用自己的 Prompt；经理基于它们的报告流式总结。</span></div></div>
      <button className="primary-wide" onClick={onClose}><Check size={17} /> 应用设置</button>
    </aside>
  </div>;
}

export default App;
