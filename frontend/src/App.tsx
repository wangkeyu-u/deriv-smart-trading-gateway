import {
  Activity,
  AlertTriangle,
  AudioWaveform,
  BarChart3,
  Building2,
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
  ExternalLink,
  FlaskConical,
  Gauge,
  History,
  Inbox,
  KeyRound,
  Languages,
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
  ShieldAlert,
  Sparkles,
  Square,
  TerminalSquare,
  Trash2,
  TrendingDown,
  TrendingUp,
  Users,
  Waypoints,
  Wifi,
  X
} from "lucide-react";
import { createContext, FormEvent, useContext, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import Sidebar from "./components/Sidebar";
import ChatPanel from "./components/ChatPanel";
import DecisionPanel from "./components/DecisionPanel";
import MarketPanel from "./components/MarketPanel";

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
  broker_id?: string;
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
  broker_id?: string;
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
type DecisionItem = {
  case: CaseSummary;
  decision: Record<string, any>;
  state: "ready" | "blocked" | "evidence_requested" | "approved" | "rejected";
  evidence_score: number;
  blockers: string[];
  global_risk: Record<string, any>;
};
type RiskPolicyState = {
  policy: {
    enabled: boolean;
    max_single_trade_amount: number;
    max_daily_trade_budget: number;
    max_total_trade_budget: number;
    max_daily_loss: number;
    max_open_positions: number;
    cooldown_seconds: number;
  };
  usage: {
    budget_day: string;
    spent_today: number;
    spent_total: number;
    realized_pnl_today: number;
    open_positions: number;
    last_trade_at?: string | null;
  };
  updated_at: string;
};
type BrokerDefinition = {
  id: string;
  name: string;
  category: string;
  regions: string[];
  environments: string[];
  capabilities: string[];
  auth_type: string;
  credential_fields: string[];
  account_id_required: boolean;
  connection_test_supported: boolean;
  docs_url: string;
  notes: string;
  integration_level: "full_adapter" | "market_and_account" | "market_data_only" | "account_diagnostic" | "catalog_only";
  implemented_capabilities: string[];
};
type AccountSnapshot = {
  broker_id: string;
  account_id?: string | null;
  currency?: string | null;
  status: string;
  balance?: string | number | null;
  buying_power?: string | number | null;
  net_equity?: string | number | null;
  position_count?: number | null;
  asset_count?: number | null;
  can_trade?: boolean | null;
  positions: Array<Record<string, unknown>>;
};
type BrokerConnectionResult = {
  ok: boolean;
  broker_id: string;
  status: string;
  message?: string;
  latency_ms?: number;
  checked_at?: string;
  account?: Record<string, unknown>;
  snapshot?: AccountSnapshot;
};
type BrokerProfile = {
  id: string;
  broker_id: string;
  label: string;
  environment: string;
  account_id: string;
  is_default: boolean;
  settings: Record<string, unknown>;
  updated_at: string;
};

const API = import.meta.env.VITE_API_BASE || "";

type Language = "zh" | "en";
const LanguageContext = createContext<Language>("zh");
const useLanguage = () => useContext(LanguageContext);
const bilingual = (language: Language, zh: string, en: string) => language === "zh" ? zh : en;

const NAV_ITEMS = [
  { id: "command", zh: "指挥中心", en: "Command Center", icon: LayoutDashboard },
  { id: "brokers", zh: "券商中心", en: "Broker Hub", icon: Building2 },
  { id: "decisions", zh: "决策审批", en: "Decision Inbox", icon: Inbox },
  { id: "cases", zh: "交易任务", en: "Trade Cases", icon: BriefcaseBusiness },
  { id: "advisors", zh: "谋士团", en: "Advisor Council", icon: Network },
  { id: "markets", zh: "行情图表", en: "Market Charts", icon: ChartNoAxesCombined },
  { id: "strategy", zh: "小笔策略", en: "Micro Strategy", icon: FlaskConical },
  { id: "risk", zh: "全局风控", en: "Risk Governor", icon: ShieldAlert },
  { id: "monitor", zh: "系统监控", en: "System Monitor", icon: RadioTower }
] as const;

const BROKER_OPTIONS = [
  { id: "deriv", name: "Deriv" }, { id: "alpaca", name: "Alpaca" },
  { id: "oanda", name: "OANDA" }, { id: "ibkr", name: "Interactive Brokers" },
  { id: "coinbase", name: "Coinbase Advanced" }, { id: "kraken", name: "Kraken" },
  { id: "binance", name: "Binance" }
];
const BROKER_VISUALS = {
  deriv: { icon: Activity, accent: "#79d9b8", defaultSymbol: "R_75", marketData: true },
  alpaca: { icon: TrendingUp, accent: "#73b5da", defaultSymbol: "AAPL", marketData: false },
  oanda: { icon: CandlestickChart, accent: "#ef8b84", defaultSymbol: "EUR_USD", marketData: false },
  ibkr: { icon: Building2, accent: "#db8b76", defaultSymbol: "AAPL", marketData: false },
  coinbase: { icon: CircleDollarSign, accent: "#7fa8f7", defaultSymbol: "BTC-USD", marketData: true },
  kraken: { icon: Waypoints, accent: "#aa94e8", defaultSymbol: "XBTUSD", marketData: true },
  binance: { icon: BarChart3, accent: "#e6bd6a", defaultSymbol: "BTCUSDT", marketData: true }
} as const;
const brokerVisual = (brokerId: string) => BROKER_VISUALS[brokerId as keyof typeof BROKER_VISUALS] || BROKER_VISUALS.deriv;
const brokerDefaultSymbol = (brokerId: string) => brokerVisual(brokerId).defaultSymbol;

function App() {
  const [language, setLanguage] = useState<Language>(() => localStorage.getItem("gateway-language") === "en" ? "en" : "zh");
  const tr = (zh: string, en: string) => bilingual(language, zh, en);
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
  const [brokerId, setBrokerId] = useState(() => localStorage.getItem("gateway-broker") || "deriv");
  const [symbol, setSymbol] = useState<string>(() => brokerDefaultSymbol(localStorage.getItem("gateway-broker") || "deriv"));
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
    const updateBroker = (event: Event) => {
      const next = (event as CustomEvent<string>).detail;
      if (next) { setBrokerId(next); setSymbol(brokerDefaultSymbol(next)); localStorage.setItem("gateway-broker", next); }
    };
    window.addEventListener("broker-default-changed", updateBroker);
    return () => window.removeEventListener("broker-default-changed", updateBroker);
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, activities]);

  async function bootstrap() {
    try {
      const [healthResponse, casesResponse, agentsResponse, runsResponse, brokersResponse] = await Promise.all([
        fetch(`${API}/api/health`),
        fetch(`${API}/api/cases`),
        fetch(`${API}/api/agents`),
        fetch(`${API}/api/runs`),
        fetch(`${API}/api/brokers`)
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
      if (brokersResponse.ok) {
        const payload = await brokersResponse.json();
        const defaultProfile = (payload.profiles || []).find((profile: BrokerProfile) => profile.is_default);
        const storedBroker = localStorage.getItem("gateway-broker");
        const storedBrokerExists = (payload.brokers || []).some((broker: BrokerDefinition) => broker.id === storedBroker);
        const resolvedBroker = storedBrokerExists ? storedBroker : defaultProfile?.broker_id;
        if (resolvedBroker) { setBrokerId(resolvedBroker); setSymbol(brokerDefaultSymbol(resolvedBroker)); localStorage.setItem("gateway-broker", resolvedBroker); }
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
      setActivities((current) => current.map((item) => item.state === "running" ? { ...item, state: "error", report: tr("已由用户停止", "Stopped by user") } : item));
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
          language,
          broker_id: linkedCase?.broker_id || brokerId
        })
      });
      if (!response.ok || !response.body) {
        throw new Error((await response.text()) || tr("流式连接失败", "Streaming connection failed"));
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
        const text = error instanceof Error ? error.message : tr("流式连接失败", "Streaming connection failed");
        setMessages((current) => current.map((item, index) => index === current.length - 1 ? { ...item, content: `${tr("连接失败", "Connection failed")}: ${text}`, streaming: false } : item));
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
      upsertActivity({ id: `tool:${payload.tool}`, name: payload.label || tr("行情数据读取", "Market data fetch"), state: payload.ok ? "done" : "error", kind: "tool", report: payload.ok ? tr("数据已返回并通过基础检查", "Data returned and passed basic validation") : payload.error || tr("数据读取不完整", "Incomplete market data"), durationMs: payload.duration_ms });
    }
    if (payload.type === "manager_fallback") {
      upsertActivity({ id: "manager:fallback", name: tr("经理降级总结", "Manager fallback summary"), state: "error", kind: "tool", report: tr("主模型总结未完成，已使用本地安全摘要继续返回结果。", "The main model summary failed; a safe local summary was returned instead.") });
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
      upsertActivity({ id: `case:${updated.id}`, name: `${tr("任务同步", "Case sync")} · ${humanStage(updated.stage, language)}`, state: "done", kind: "tool", report: tr(`${updated.id} 已写入本地数据库，当前版本 v${updated.version}`, `${updated.id} saved to the local database at version v${updated.version}`) });
    }
    if (payload.type === "answer_delta") {
      setMessages((current) => current.map((item, index) => index === current.length - 1 ? { ...item, content: item.content + payload.delta } : item));
    }
    if (payload.type === "error") {
      setRunSummary((current) => ({ ...current, status: "failed" }));
      setMessages((current) => current.map((item, index) => index === current.length - 1 ? { ...item, content: `${tr("运行失败", "Run failed")}: ${payload.message}`, streaming: false } : item));
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
    local: tr("本地规则", "Local rules"),
    openai: "OpenAI",
    deepseek: "DeepSeek",
    anthropic: "Anthropic",
    compatible: tr("兼容 API", "Compatible API")
  }[provider]), [provider, language]);
  const WorkspaceBrokerIcon = brokerVisual(linkedCase?.broker_id || brokerId).icon;

  return (
    <LanguageContext.Provider value={language}>
    <div className="app-shell" lang={language === "zh" ? "zh-CN" : "en"} data-broker={linkedCase?.broker_id || brokerId}>
      <aside className={`side-nav ${mobileNav ? "side-nav--open" : ""}`}>
        <div className="brand-block">
          <div className="brand-mark"><Waypoints size={20} /></div>
          <div><strong>MARKET GATEWAY</strong><span>Multi-Broker Agent Operations</span></div>
          <button className="icon-btn mobile-only" onClick={() => setMobileNav(false)} aria-label={tr("关闭导航", "Close navigation")}><X size={18} /></button>
        </div>
        <nav>
          <p className="nav-caption">WORKSPACE</p>
          {NAV_ITEMS.map((item) => (
            <button key={item.id} className={`nav-item ${active === item.id ? "nav-item--active" : ""}`} aria-current={active === item.id ? "page" : undefined} onClick={() => { setActive(item.id); setMobileNav(false); }}>
              <item.icon size={18} /><span>{item[language]}</span>{active === item.id && <ChevronRight size={16} />}
            </button>
          ))}
        </nav>
        <div className="nav-bottom">
          <button className="nav-item" onClick={() => setSettingsOpen(true)}><Settings2 size={18} /><span>{tr("模型与密钥", "Models & API Keys")}</span></button>
          <button className="nav-item language-switch" onClick={() => { const next = language === "zh" ? "en" : "zh"; setLanguage(next); localStorage.setItem("gateway-language", next); }} aria-label={tr("切换到英文", "Switch to Chinese")}><Languages size={18} /><span>{language === "zh" ? "English" : "ZH"}</span></button>
          <div className="runtime-line"><span className={`status-dot status-dot--${health}`} /> FastAPI · {health === "online" ? "ONLINE" : "OFFLINE"}</div>
        </div>
      </aside>

      <main className="main-stage">
        <header className="top-bar">
          <button className="icon-btn mobile-only" onClick={() => setMobileNav(true)} aria-label={tr("打开导航", "Open navigation")}><Menu size={19} /></button>
          <div className="top-title"><span>{NAV_ITEMS.find((item) => item.id === active)?.[language]}</span><small>{tr("多 Agent 实时协作与人工交易闸门", "Live multi-agent orchestration with human approval gates")}</small></div>
          <div className="top-status">
            <span className="market-chip"><WorkspaceBrokerIcon size={14} /> {brokerName(linkedCase?.broker_id || brokerId)} · {symbol}</span>
            <span className="model-chip"><Sparkles size={14} /> {providerLabel}</span>
            <button className="text-btn language-top" onClick={() => { const next = language === "zh" ? "en" : "zh"; setLanguage(next); localStorage.setItem("gateway-language", next); }} aria-label={tr("切换到英文", "Switch to Chinese")}><Languages size={16} /> {language === "zh" ? "EN" : "ZH"}</button>
            <button className="icon-btn" onClick={() => setRightOpen((value) => !value)} aria-label={tr("切换活动面板", "Toggle activity panel")}>
              {rightOpen ? <PanelRightClose size={18} /> : <PanelRightOpen size={18} />}
            </button>
          </div>
        </header>

        {active === "command" && (
          <section className={`command-layout view-enter ${rightOpen ? "" : "command-layout--wide"}`}>
            <div className="conversation-panel">
              <div className="conversation-head">
                <div className="conversation-title"><p className="eyebrow">LIVE ORCHESTRATION</p><h1>{tr("老板指挥台", "Executive Command Desk")}</h1>{linkedCase && <div className="linked-case"><BriefcaseBusiness size={15} /><div><strong>{localizedCaseText(linkedCase.title, linkedCase.symbol, language)}</strong><span>{linkedCase.symbol} · {humanStage(linkedCase.stage, language)} · v{linkedCase.version}</span></div><button type="button" onClick={() => setLinkedCase(null)} aria-label={tr("解除交易任务绑定", "Unlink trade case")}><X size={14} /></button></div>}</div>
                <div className="conversation-actions"><button className="icon-btn" onClick={() => { void refreshSessions(); setSessionsOpen(true); }} aria-label={tr("历史对话", "Conversation history")}><History size={17} /></button><button className="text-btn" onClick={newConversation}><Plus size={16} /> {tr("新对话", "New chat")}</button></div>
              </div>
              <div className="conversation-scroll" ref={scrollRef}>
                {messages.length === 0 ? <EmptyConversation onPick={setInput} /> : messages.map((message, index) => <MessageBubble key={`${index}-${message.role}`} message={message} />)}
              </div>
              <form className="composer" onSubmit={sendMessage}>
                <textarea value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); }
                }} placeholder={tr("告诉经理你要分析什么。Enter 发送，Shift + Enter 换行。", "Tell the manager what to analyze. Enter to send, Shift + Enter for a new line.")} rows={3} />
                <div className="composer-footer">
                  <div className="composer-meta"><ShieldCheck size={15} /> {tr("默认只分析，不自动成交", "Analysis only by default; no automatic execution")}</div>
                  {streaming ? (
                    <button type="button" className="send-btn send-btn--stop" onClick={stopStreaming}><Square size={15} fill="currentColor" /> {tr("停止", "Stop")}</button>
                  ) : (
                    <button type="submit" className="send-btn" disabled={!input.trim()}><Send size={16} /> {tr("发送", "Send")}</button>
                  )}
                </div>
              </form>
            </div>
            {rightOpen && <AgentRail activities={activities} route={route} run={runSummary} provider={providerLabel} cases={cases} onSettings={() => setSettingsOpen(true)} />}
          </section>
        )}

        {active !== "command" && <ModuleView id={active} cases={cases} agents={agents} runs={runs} health={healthInfo} provider={providerLabel} onCasesChange={setCases} onDispatch={(caseItem) => { const nextBroker = caseItem.broker_id || "deriv"; setLinkedCase(caseItem); setSymbol(caseItem.symbol); setBrokerId(nextBroker); localStorage.setItem("gateway-broker", nextBroker); const objective = localizedCaseText(caseItem.objective, caseItem.symbol, language); setInput(tr(`请接手交易任务 ${caseItem.id}：${objective}。先让谋士团和行情 Agent 分析 ${caseItem.symbol}，把行情、结论和风控要求同步回任务。`, `Take ownership of trade case ${caseItem.id}: ${objective}. Ask the advisor council and market agent to analyze ${caseItem.symbol}, then sync market evidence, conclusions, and risk requirements back to the case.`)); setActive("command"); }} onBack={() => setActive("command")} />}
      </main>

      {settingsOpen && (
        <SettingsDrawer provider={provider} setProvider={setProvider} apiKey={apiKey} setApiKey={setApiKey} model={model} setModel={setModel} baseUrl={baseUrl} setBaseUrl={setBaseUrl} onClose={() => setSettingsOpen(false)} />
      )}
      {sessionsOpen && <SessionDrawer sessions={sessions} currentId={sessionId} onSelect={switchSession} onNew={async () => { await newConversation(); setSessionsOpen(false); }} onClose={() => setSessionsOpen(false)} />}
    </div>
    </LanguageContext.Provider>
  );
}

function ModuleSkeleton({ label }: { label: string }) {
  return <div className="module-skeleton" role="status" aria-live="polite" aria-label={label}>
    <div className="skeleton-head"><span /><span /></div>
    <div className="skeleton-band"><span /><span /><span /><span /></div>
    <div className="skeleton-body"><span /><span /><span /></div>
    <p>{label}</p>
  </div>;
}

function EmptyConversation({ onPick }: { onPick: (value: string) => void }) {
  const language = useLanguage();
  const t = (zh: string, en: string) => bilingual(language, zh, en);
  const prompts = language === "zh" ? [
    "让谋士团分析 R_75 接下来 10 分钟的风险和机会",
    "检查 R_100 行情，然后给我一个不超过 1 美元的纸面策略",
    "解释最近一次交易任务为什么被风控拦截"
  ] : [
    "Ask the advisor council to assess R_75 risks and opportunities over the next 10 minutes",
    "Check R_100 and prepare a paper strategy capped at USD 1",
    "Explain why risk controls blocked the latest trade case"
  ];
  return <div className="empty-state">
    <div className="empty-symbol"><Bot size={28} /></div>
    <p className="eyebrow">READY FOR ORDERS</p>
    <h2>{t("经理和团队已就位", "Your manager and agents are ready")}</h2>
    <p>{t("你的指令会被拆给策略、行情、风控、合规和报告 Agent。处理过程与最终回答都会实时出现。", "Your request is delegated to strategy, market, risk, compliance, and reporting agents. Progress and the final answer stream in live.")}</p>
    <div className="prompt-grid">{prompts.map((prompt) => <button key={prompt} onClick={() => onPick(prompt)}>{prompt}<ChevronRight size={15} /></button>)}</div>
  </div>;
}

function MessageBubble({ message }: { message: Message }) {
  const language = useLanguage();
  return <article className={`message message--${message.role}`}>
    <div className="message-avatar">{message.role === "assistant" ? <Bot size={17} /> : <span>{bilingual(language, "你", "You")}</span>}</div>
    <div className="message-body">
      <div className="message-label">{message.role === "assistant" ? bilingual(language, "交易经理", "Trading Manager") : bilingual(language, "老板", "Executive")}</div>
      <div className="message-content">{message.content ? (message.role === "assistant" ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{localizedMessage(message.content, message.role, language)}</ReactMarkdown> : localizedMessage(message.content, message.role, language)) : (message.streaming ? <span className="typing"><i /><i /><i /></span> : "")}{message.streaming && message.content && <span className="stream-caret" />}</div>
    </div>
  </article>;
}

function AgentRail({ activities, route, run, provider, cases, onSettings }: { activities: AgentActivity[]; route: string[]; run: RunSummary; provider: string; cases: CaseSummary[]; onSettings: () => void }) {
  const language = useLanguage();
  const t = (zh: string, en: string) => bilingual(language, zh, en);
  return <aside className="agent-rail">
    <section className="rail-section">
      <div className="rail-heading"><div><p className="eyebrow">AGENT ACTIVITY</p><h2>{t("实时协作", "Live Collaboration")}</h2></div><span className="live-badge"><i /> LIVE</span></div>
      {run.status !== "idle" && <div className={`trace-strip trace-strip--${run.status}`}>
        <div><span>{t("运行", "Run")}</span><code>{run.runId || t("正在创建", "Starting")}</code></div>
        <strong>{humanRunStatus(run.status, language)}</strong>
        <div className="trace-metrics"><span>{run.elapsedMs == null ? t("计时中", "Timing") : formatDuration(run.elapsedMs)}</span><span>{run.successCount ?? 0} {t("成功", "passed")}</span><span>{run.failedCount ?? 0} {t("降级", "degraded")}</span></div>
      </div>}
      {activities.length === 0 ? <div className="quiet-state"><Activity size={20} /><span>{t("发送指令后，这里会显示每个 Agent 的工作状态。", "Each agent's status will appear here after you send a request.")}</span></div> : <div className="activity-list" aria-live="polite">{activities.map((item) => <div className="activity-item" key={item.id}>
        <div className={`activity-icon activity-icon--${item.state}`}>{item.state === "running" ? <LoaderCircle size={15} className="spin" /> : item.state === "error" ? <AlertTriangle size={15} /> : <Check size={15} />}</div>
        <div><strong>{item.name}{item.durationMs != null && <em>{formatDuration(item.durationMs)}</em>}</strong><span>{item.state === "running" ? (item.kind === "tool" ? t("正在调用工具", "Calling tool") : t("正在分析", "Analyzing")) : item.report || t("完成", "Done")}</span></div>
      </div>)}</div>}
      {route.length > 0 && <div className="route-strip"><span>ROUTE</span><code>{route.join(" → ")}</code></div>}
    </section>
    <section className="rail-section connection-card">
      <div className="connection-row"><div className="connection-icon"><KeyRound size={17} /></div><div><span>{t("模型连接", "Model connection")}</span><strong>{provider}</strong></div><button className="icon-btn" onClick={onSettings}><Settings2 size={16} /></button></div>
      <div className="connection-row"><div className="connection-icon"><Database size={17} /></div><div><span>{t("本地记忆", "Local memory")}</span><strong>{t("SQLite 已连接", "SQLite connected")}</strong></div><span className="ok-dot" /></div>
    </section>
    <section className="rail-section case-preview">
      <div className="rail-heading"><div><p className="eyebrow">TRADE CASES</p><h2>{t("最近任务", "Recent Cases")}</h2></div><span>{cases.length}</span></div>
      {cases.slice(0, 3).map((item) => <div className="case-row" key={item.id}><div><strong>{item.symbol}</strong><span>{localizedCaseText(item.title, item.symbol, language)}</span></div><em>{humanCaseStatus(item.status, language)}</em></div>)}
      {cases.length === 0 && <div className="quiet-state compact"><CircleDollarSign size={18} /><span>{t("暂无交易任务", "No trade cases")}</span></div>}
    </section>
  </aside>;
}

function ModuleView({ id, cases, agents, runs, health, provider, onCasesChange, onDispatch, onBack }: { id: string; cases: CaseSummary[]; agents: AgentSpec[]; runs: AgentRun[]; health: HealthInfo | null; provider: string; onCasesChange: (cases: CaseSummary[]) => void; onDispatch: (caseItem: CaseDetail["case"]) => void; onBack: () => void }) {
  const language = useLanguage();
  const t = (zh: string, en: string) => bilingual(language, zh, en);
  const item = NAV_ITEMS.find((nav) => nav.id === id)!;
  const descriptions: Record<string, [string, string]> = {
    brokers: ["选择、验证并管理不同金融平台的账户连接与能力。", "Select, validate, and manage account connections across financial platforms."],
    decisions: ["集中复核待决策任务、证据完整度、风险阻断和人工决定。", "Review pending cases, evidence completeness, risk blockers, and operator decisions in one queue."],
    cases: ["持久化跟踪谋士、行情、回测、风控、确认和成交复盘。", "Persist advisor, market, backtest, risk, approval, and execution evidence."],
    advisors: ["多位独立谋士使用各自 Prompt 分析同一问题，由首席谋士汇总。", "Independent advisors analyze the same question with dedicated prompts; a lead advisor synthesizes the result."],
    markets: ["实时 Tick、完整 K 线、数据时效与指标验证。", "Live ticks, complete candles, freshness checks, and indicator validation."],
    strategy: ["严格预算下的小额纸面交易、回测和熔断。", "Budget-capped paper trading, backtests, and circuit breakers."],
    risk: ["所有策略分析和审批流程共用的持久化资金与风险硬限制。", "Persistent capital and risk limits shared by every strategy analysis and approval workflow."],
    monitor: ["服务健康、Agent 路由、模型连接和本地持久化状态。", "Service health, agent routes, model connections, and local persistence."]
  };
  return <section className="module-page view-enter">
    <div className="module-title"><div className="module-icon"><item.icon size={22} /></div><div><p className="eyebrow">OPERATOR MODULE</p><h1>{item[language]}</h1><p>{descriptions[id] ? bilingual(language, descriptions[id][0], descriptions[id][1]) : ""}</p></div><button className="text-btn" onClick={onBack}><MessageSquareText size={16} /> {t("返回指挥台", "Back to Command")}</button></div>
    {id === "decisions" && <DecisionInbox />}
    {id === "brokers" && <BrokerHub />}
    {id === "cases" && <CaseModule cases={cases} onCasesChange={onCasesChange} onDispatch={onDispatch} />}
    {id === "advisors" && <AdvisorModule agents={agents} />}
    {id === "markets" && <MarketModule />}
    {id === "strategy" && <StrategyModule />}
    {id === "risk" && <RiskGovernor />}
    {id === "monitor" && <MonitorModule health={health} provider={provider} agentCount={agents.length} runs={runs} />}
  </section>;
}

function BrokerHub() {
  const language = useLanguage();
  const t = (zh: string, en: string) => bilingual(language, zh, en);
  const [brokers, setBrokers] = useState<BrokerDefinition[]>([]);
  const [profiles, setProfiles] = useState<BrokerProfile[]>([]);
  const [selectedId, setSelectedId] = useState("deriv");
  const [environment, setEnvironment] = useState("");
  const [accountId, setAccountId] = useState("");
  const [label, setLabel] = useState("");
  const [credentials, setCredentials] = useState<Record<string, string>>({});
  const [makeDefault, setMakeDefault] = useState(true);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<BrokerConnectionResult | null>(null);
  const [error, setError] = useState("");

  useEffect(() => { void load(); }, []);
  const selected = brokers.find((broker) => broker.id === selectedId);

  async function load() {
    setError("");
    try {
      const response = await fetch(`${API}/api/brokers`);
      const payload = await response.json();
      if (!response.ok) throw new Error(String(payload.detail || "Broker catalog unavailable"));
      const catalog = payload.brokers || [];
      setBrokers(catalog); setProfiles(payload.profiles || []);
      const storedId = localStorage.getItem("gateway-broker");
      const initialId = catalog.some((broker: BrokerDefinition) => broker.id === storedId) ? storedId : (payload.profiles || []).find((profile: BrokerProfile) => profile.is_default)?.broker_id || catalog[0]?.id || "deriv";
      selectBroker(initialId, catalog);
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("券商目录读取失败", "Failed to load broker catalog")); }
  }

  function selectBroker(id: string, catalog = brokers) {
    const broker = catalog.find((item) => item.id === id);
    setSelectedId(id); setEnvironment(broker?.environments[0] || ""); setAccountId(""); setLabel(broker?.name || ""); setCredentials({}); setResult(null); setError("");
    if (broker) { localStorage.setItem("gateway-broker", broker.id); window.dispatchEvent(new CustomEvent("broker-default-changed", { detail: broker.id })); }
  }

  async function testConnection() {
    if (!selected) return;
    setTesting(true); setResult(null); setError("");
    try {
      const response = await fetch(`${API}/api/brokers/${selected.id}/test`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ environment, account_id: accountId, credentials })
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(String(payload.detail || "Connection test failed"));
      setResult(payload);
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("连接测试失败", "Connection test failed")); }
    finally { setTesting(false); }
  }

  async function saveProfile() {
    if (!selected) return;
    setSaving(true); setError("");
    try {
      const response = await fetch(`${API}/api/broker-profiles`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ broker_id: selected.id, label, environment, account_id: accountId, is_default: makeDefault, settings: {} })
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(String(payload.detail || "Profile save failed"));
      setProfiles(payload.profiles || []);
      if (makeDefault) { localStorage.setItem("gateway-broker", selected.id); window.dispatchEvent(new CustomEvent("broker-default-changed", { detail: selected.id })); }
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("连接档案保存失败", "Failed to save connection profile")); }
    finally { setSaving(false); }
  }

  async function removeProfile(profile: BrokerProfile) {
    if (!window.confirm(t(`删除连接档案“${profile.label}”？不会删除券商账户。`, `Delete connection profile “${profile.label}”? This will not affect the broker account.`))) return;
    const response = await fetch(`${API}/api/broker-profiles/${profile.id}`, { method: "DELETE" });
    const payload = await response.json();
    if (response.ok) setProfiles(payload.profiles || []); else setError(String(payload.detail || "Delete failed"));
  }

  if (!selected) return <ModuleSkeleton label={t("正在加载券商目录", "Loading broker catalog")} />;
  const attached = profiles.filter((profile) => profile.broker_id === selected.id);
  const SelectedBrokerIcon = brokerVisual(selected.id).icon;
  return <div className="broker-workspace">
    <div className="broker-switcher">
      <div className="broker-switcher-copy"><div className="broker-switcher-icon"><SelectedBrokerIcon size={19} /></div><div><strong>{t("选择要连接的券商", "Choose a broker to connect")}</strong><span>{t("选择后会同步工作区图标、默认品种、行情能力、账户字段和凭证要求。", "The workspace icon, default symbol, market capability, account fields, and credentials update together.")}</span></div></div>
      <label><span>{t("券商", "Broker")}</span><select value={selectedId} onChange={(event) => selectBroker(event.target.value)} aria-label={t("选择券商", "Select broker")}>{brokers.map((broker) => <option value={broker.id} key={broker.id}>{broker.name} · {integrationLevelLabel(broker.integration_level, language, true)}</option>)}</select></label>
      <div className="broker-switcher-state"><span className={`connection-dot ${attached.length ? "connection-dot--saved" : ""}`} /><div><small>{t("本地连接档案", "Local connection profile")}</small><strong>{attached.length ? t(`已保存 ${attached.length} 个`, `${attached.length} saved`) : t("尚未保存", "Not saved yet")}</strong></div></div>
    </div>
    <section className="broker-console">
      <div className="broker-hero"><div><p className="eyebrow">{selected.id.toUpperCase()} · {selected.auth_type.replaceAll("_", " ")}</p><div className="broker-hero-heading"><div className="broker-hero-icon"><SelectedBrokerIcon size={22} /></div><h2>{selected.name}</h2></div><p>{selected.notes}</p></div><a className="text-btn" href={selected.docs_url} target="_blank" rel="noreferrer">API Docs <ExternalLink size={14} /></a></div>
      <div className="capability-matrix"><div><span>{t("资产范围", "Asset Scope")}</span><strong>{selected.category}</strong></div><div><span>{t("集成深度", "App Integration")}</span><strong>{integrationLevelLabel(selected.integration_level, language)}</strong></div><div><span>{t("可用环境", "Environments")}</span><strong>{selected.environments.join(" · ")}</strong></div><div><span>{t("连接状态", "Connection")}</span><strong className={result?.ok ? "positive-text" : ""}>{result?.ok ? `${t("已验证", "Verified")} · ${result.latency_ms} ms` : t("未验证", "Not Verified")}</strong></div></div>
      <div className="capability-sections">
        <div><strong>{t("本软件已实现", "Implemented in This App")}</strong><div className="broker-capabilities broker-capabilities--implemented">{selected.implemented_capabilities.length ? selected.implemented_capabilities.map((capability) => <span key={capability}><Check size={13} />{capabilityLabel(capability, language)}</span>) : <span className="capability-empty"><AlertTriangle size={13} />{t("仅提供目录信息，尚无运行时适配器", "Catalog information only; no runtime adapter yet")}</span>}</div></div>
        <div><strong>{t("券商平台能力（不代表本软件已实现）", "Broker Platform Scope (not app coverage)")}</strong><div className="broker-capabilities broker-capabilities--platform">{selected.capabilities.map((capability) => <span key={capability}>{capabilityLabel(capability, language)}</span>)}</div></div>
      </div>
      <div className="broker-config-grid"><form className="broker-connect-form" onSubmit={(event) => { event.preventDefault(); void testConnection(); }}><div className="form-section-title"><div><p className="eyebrow">SESSION-ONLY SECRETS</p><h3>{t("验证账户连接", "Verify Account Connection")}</h3></div><ShieldCheck size={19} /></div><label>{t("环境", "Environment")}<select value={environment} onChange={(event) => setEnvironment(event.target.value)}>{selected.environments.map((item) => <option key={item}>{item}</option>)}</select></label>{selected.account_id_required && <label>{t("账户 ID", "Account ID")}<input value={accountId} onChange={(event) => setAccountId(event.target.value)} autoComplete="off" /></label>}{selected.credential_fields.map((field) => <label key={field}>{credentialLabel(field)}<input type="password" value={credentials[field] || ""} onChange={(event) => setCredentials((current) => ({ ...current, [field]: event.target.value }))} autoComplete="new-password" placeholder={field === "app_id" ? "1089" : "••••••••••••"} /></label>)}<div className="secret-boundary"><KeyRound size={16} /><span>{t("密钥仅用于本次验证请求，不写入浏览器存储或本地数据库。", "Secrets are used for this verification request only and are never written to browser storage or the local database.")}</span></div><button className="action-btn" disabled={testing || !selected.connection_test_supported}>{testing ? <LoaderCircle className="spin" size={16} /> : <Wifi size={16} />}{selected.connection_test_supported ? t("测试连接", "Test Connection") : t("需要专用适配器", "Dedicated Adapter Required")}</button></form>
        <div className="broker-profile-panel"><div className="form-section-title"><div><p className="eyebrow">LOCAL ROUTING PROFILE</p><h3>{t("保存非敏感档案", "Save Non-Secret Profile")}</h3></div><Database size={19} /></div><label>{t("档案名称", "Profile Label")}<input value={label} onChange={(event) => setLabel(event.target.value)} /></label>{!selected.account_id_required && <label>{t("账户 ID（可选）", "Account ID (optional)")}<input value={accountId} onChange={(event) => setAccountId(event.target.value)} /></label>}<label className="default-profile"><input type="checkbox" checked={makeDefault} onChange={(event) => setMakeDefault(event.target.checked)} /><span>{t("设为 Agent 默认交易平台", "Use as the default platform for agents")}</span></label><button className="text-btn profile-save" onClick={() => void saveProfile()} disabled={saving}>{saving ? <LoaderCircle className="spin" size={15} /> : <Plus size={15} />}{t("保存连接档案", "Save Connection Profile")}</button>{attached.map((profile) => <div className="saved-profile" key={profile.id}><div><strong>{profile.label}</strong><span>{profile.environment}{profile.account_id ? ` · ${profile.account_id}` : ""}</span></div>{profile.is_default && <em>DEFAULT</em>}<button className="icon-btn" onClick={() => void removeProfile(profile)} aria-label={t("删除连接档案", "Delete connection profile")}><Trash2 size={14} /></button></div>)}</div></div>
      {result && <div className={`connection-result ${result.ok ? "success" : "warning"}`} role="status" aria-live="polite"><div>{result.ok ? <Check size={18} /> : <AlertTriangle size={18} />}<strong>{result.ok ? t("账户连接已验证", "Account connection verified") : t("连接尚未就绪", "Connection not ready")}</strong></div><span>{result.message || `${selected.name} · ${result.status}${result.latency_ms == null ? "" : ` · ${result.latency_ms} ms`}`}</span></div>}
      {result?.ok && result.snapshot && <AccountOverview snapshot={result.snapshot} broker={selected} />}
      {error && <div className="inline-alert"><AlertTriangle size={17} />{error}</div>}
    </section>
  </div>;
}

function AccountOverview({ snapshot, broker }: { snapshot: AccountSnapshot; broker: BrokerDefinition }) {
  const language = useLanguage();
  const t = (zh: string, en: string) => bilingual(language, zh, en);
  const BrokerIcon = brokerVisual(broker.id).icon;
  const positionCount = snapshot.position_count ?? snapshot.asset_count ?? snapshot.positions.length;
  return <section className="account-overview">
    <div className="account-overview-head"><div className="broker-hero-icon"><BrokerIcon size={20} /></div><div><h3>{t("统一账户快照", "Unified Account Snapshot")}</h3><p>{t("来自券商实时连接，仅展示标准化字段，不保存密钥。", "Normalized from the live broker connection; credentials are never persisted.")}</p></div><span className={snapshot.can_trade === false ? "account-state account-state--blocked" : "account-state"}>{snapshot.can_trade === false ? t("禁止交易", "Trading Blocked") : t("连接正常", "Connected")}</span></div>
    <div className="account-metrics">
      <Metric label={t("账户", "Account")} value={String(snapshot.account_id || "--")} />
      <Metric label={t("余额", "Balance")} value={formatMoney(snapshot.balance, snapshot.currency)} />
      <Metric label={t("净值", "Net Equity")} value={formatMoney(snapshot.net_equity, snapshot.currency)} />
      <Metric label={t("可用购买力", "Buying Power")} value={formatMoney(snapshot.buying_power, snapshot.currency)} />
      <Metric label={t("持仓 / 资产", "Positions / Assets")} value={String(positionCount)} />
    </div>
    {snapshot.positions.length > 0 && <div className="account-positions"><div className="account-position account-position--head"><span>{t("品种", "Instrument")}</span><span>{t("数量", "Quantity")}</span><span>{t("市值 / 可用", "Value / Available")}</span><span>{t("未实现盈亏 / 锁定", "PnL / Locked")}</span></div>{snapshot.positions.map((position, index) => <div className="account-position" key={`${String(position.symbol || position.contract_id || "position")}-${index}`}><strong>{String(position.symbol || position.contract_type || position.contract_id || "--")}</strong><span>{String(position.quantity ?? position.buy_price ?? "--")}</span><span>{String(position.market_value ?? position.available ?? position.payout ?? "--")}</span><span>{String(position.unrealized_pnl ?? position.locked ?? "--")}</span></div>)}</div>}
  </section>;
}

function DecisionInbox() {
  const language = useLanguage();
  const t = (zh: string, en: string) => bilingual(language, zh, en);
  const [items, setItems] = useState<DecisionItem[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => { void load(); }, []);

  async function load() {
    setLoading(true); setError("");
    try {
      const response = await fetch(`${API}/api/decisions`);
      const payload = await response.json();
      if (!response.ok) throw new Error(String(payload.detail || t("审批队列读取失败", "Failed to load decision inbox")));
      setItems(payload.items || []); setCounts(payload.counts || {});
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("审批队列读取失败", "Failed to load decision inbox")); }
    finally { setLoading(false); }
  }

  async function act(item: DecisionItem, action: "approve" | "reject" | "request_evidence") {
    setBusy(`${item.case.id}:${action}`); setError("");
    try {
      const response = await fetch(`${API}/api/decisions/${item.case.id}/action`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, note: notes[item.case.id] || "", expected_version: item.case.version })
      });
      const payload = await response.json();
      if (!response.ok) {
        const detail = typeof payload.detail === "object" ? payload.detail.message : payload.detail;
        throw new Error(String(detail || t("决定保存失败", "Failed to save decision")));
      }
      await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("决定保存失败", "Failed to save decision")); }
    finally { setBusy(""); }
  }

  return <div className="decision-workspace">
    <div className="decision-summary">
      <Metric label={t("可审批", "Ready")} value={String(counts.ready || 0)} tone="positive" />
      <Metric label={t("被阻断", "Blocked")} value={String(counts.blocked || 0)} tone="warning" />
      <Metric label={t("待补证据", "Evidence Requested")} value={String(counts.evidence_requested || 0)} />
      <Metric label={t("已决定", "Decided")} value={String((counts.approved || 0) + (counts.rejected || 0))} />
    </div>
    <div className="safety-line"><ShieldCheck size={16} />{t("批准只记录老板决定；真实执行仍需独立确认和执行闸门。", "Approval records operator intent only. Real execution still requires a separate confirmation and execution gate.")}</div>
    {error && <div className="inline-alert"><AlertTriangle size={17} />{error}</div>}
    {loading && <ModuleSkeleton label={t("正在整理决策队列", "Building decision queue")} />}
    {!loading && items.length === 0 && <div className="module-empty large"><Inbox size={30} /><h2>{t("审批队列为空", "Decision Inbox Is Clear")}</h2><p>{t("活跃交易任务进入证据审查后会出现在这里。", "Active trade cases appear here when evidence review begins.")}</p></div>}
    <div className="decision-list">{items.map((item) => {
      const decision = item.decision;
      const paper = decision.paper || {};
      const pending = decision.pending || {};
      const isReady = item.state === "ready";
      return <article className={`decision-card decision-card--${item.state}`} key={item.case.id}>
        <div className="decision-card-head"><div><p className="eyebrow">{item.case.id}</p><h2>{localizedCaseText(item.case.title, item.case.symbol, language)}</h2><span>{item.case.symbol} · {humanStage(item.case.stage, language)} · v{item.case.version}</span></div><em>{decisionStateLabel(item.state, language)}</em></div>
        <div className="evidence-meter"><div><span>{t("证据完整度", "Evidence completeness")}</span><strong>{item.evidence_score}%</strong></div><i><b style={{ width: `${item.evidence_score}%` }} /></i></div>
        <div className="decision-facts">
          <Evidence label={t("谋士方向", "Advisor")} value={humanAction(decision.advisor?.action, language)} />
          <Evidence label={t("策略方向", "Strategy")} value={humanAction(decision.strategy?.action, language)} />
          <Evidence label={t("纸面表现", "Paper Result")} value={`${paper.trade_count || 0} ${t("笔", "trades")} · ${formatNumber(paper.total_pnl, 5)} PnL`} />
          <Evidence label={t("待确认金额", "Pending Amount")} value={pending.exists ? `$${formatNumber(pending.amount, 2)}` : t("尚无草稿", "No Draft")} />
        </div>
        {item.blockers.length > 0 && <div className="blocker-strip"><strong>{t("当前不能批准", "Why approval is blocked")}</strong><div>{item.blockers.map((code) => <span key={code}>{blockerLabel(code, language)}</span>)}</div></div>}
        <div className="decision-actions"><input value={notes[item.case.id] || ""} onChange={(event) => setNotes((current) => ({ ...current, [item.case.id]: event.target.value }))} placeholder={t("给团队的决定说明或补充要求", "Decision note or evidence request for the team")} /><button className="text-btn" disabled={!!busy} onClick={() => void act(item, "request_evidence")}>{t("补证据", "Request Evidence")}</button><button className="text-btn danger" disabled={!!busy} onClick={() => void act(item, "reject")}>{t("拒绝", "Reject")}</button><button className="action-btn" disabled={!isReady || !!busy} title={!isReady ? t("证据和风险检查通过后才能批准", "Approval unlocks after evidence and risk checks pass") : undefined} onClick={() => void act(item, "approve")}>{busy === `${item.case.id}:approve` ? <LoaderCircle className="spin" size={15} /> : <Check size={15} />}{t("批准计划", "Approve Plan")}</button></div>
      </article>;
    })}</div>
  </div>;
}

function RiskGovernor() {
  const language = useLanguage();
  const t = (zh: string, en: string) => bilingual(language, zh, en);
  const [state, setState] = useState<RiskPolicyState | null>(null);
  const [draft, setDraft] = useState<RiskPolicyState["policy"] | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => { void load(); }, []);
  async function load() {
    try {
      const response = await fetch(`${API}/api/risk-policy`);
      const payload = await response.json();
      if (!response.ok) throw new Error(String(payload.detail || t("风控策略读取失败", "Failed to load risk policy")));
      setState(payload); setDraft(payload.policy);
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("风控策略读取失败", "Failed to load risk policy")); }
  }
  async function save(event: FormEvent) {
    event.preventDefault(); if (!draft) return;
    setSaving(true); setSaved(false); setError("");
    try {
      const response = await fetch(`${API}/api/risk-policy`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(draft) });
      const payload = await response.json();
      if (!response.ok) throw new Error(String(payload.detail || t("风控策略保存失败", "Failed to save risk policy")));
      setState(payload); setDraft(payload.policy); setSaved(true);
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("风控策略保存失败", "Failed to save risk policy")); }
    finally { setSaving(false); }
  }
  type NumericRiskKey = Exclude<keyof RiskPolicyState["policy"], "enabled">;
  function numberField(key: NumericRiskKey, label: string, min: number, step: number) {
    if (!draft) return null;
    return <label>{label}<input type="number" min={min} step={step} value={Number(draft[key])} onChange={(event) => setDraft({ ...draft, [key]: Number(event.target.value) })} /></label>;
  }
  if (error && (!state || !draft)) return <div className="inline-alert"><AlertTriangle size={17} />{error}</div>;
  if (!state || !draft) return <ModuleSkeleton label={t("正在加载风控策略", "Loading risk policy")} />;
  const usage = state.usage;
  const dailyRemaining = Math.max(0, draft.max_daily_trade_budget - usage.spent_today);
  const totalRemaining = Math.max(0, draft.max_total_trade_budget - usage.spent_total);
  return <div className="risk-governor">
    <div className="risk-usage-band"><Metric label={t("今日剩余预算", "Daily Budget Left")} value={`$${formatNumber(dailyRemaining, 2)}`} tone="positive" /><Metric label={t("总剩余预算", "Total Budget Left")} value={`$${formatNumber(totalRemaining, 2)}`} /><Metric label={t("今日已实现盈亏", "Realized PnL Today")} value={`$${formatNumber(usage.realized_pnl_today, 2)}`} tone={usage.realized_pnl_today < 0 ? "negative" : "positive"} /><Metric label={t("当前持仓", "Open Positions")} value={`${usage.open_positions} / ${draft.max_open_positions}`} /></div>
    <form className="risk-policy-form" onSubmit={save}>
      <div className="risk-policy-head"><div><p className="eyebrow">GLOBAL HARD LIMITS</p><h2>{t("资金与执行边界", "Capital & Execution Boundaries")}</h2><p>{t("这些限制由策略分析和审批中心共同读取。关闭保护只适合隔离测试环境。", "Strategy analysis and Decision Inbox share these limits. Disable protection only in an isolated test environment.")}</p></div><label className="policy-toggle"><input type="checkbox" checked={draft.enabled} onChange={(event) => setDraft({ ...draft, enabled: event.target.checked })} /><span>{draft.enabled ? t("保护已开启", "Protection On") : t("保护已关闭", "Protection Off")}</span></label></div>
      <div className="risk-fields">{numberField("max_single_trade_amount", t("单笔金额上限（USD）", "Max Per Trade (USD)"), 0.01, 0.1)}{numberField("max_daily_trade_budget", t("每日总预算（USD）", "Daily Budget (USD)"), 0.01, 0.5)}{numberField("max_total_trade_budget", t("累计总预算（USD）", "Lifetime Budget (USD)"), 0.01, 1)}{numberField("max_daily_loss", t("每日最大亏损（USD）", "Max Daily Loss (USD)"), 0.01, 0.1)}{numberField("max_open_positions", t("最大同时持仓", "Max Open Positions"), 1, 1)}{numberField("cooldown_seconds", t("交易冷却时间（秒）", "Cooldown (seconds)"), 0, 10)}</div>
      {error && <div className="inline-alert"><AlertTriangle size={17} />{error}</div>}
      <div className="risk-form-footer"><span>{saved ? t("已保存并立即应用到新分析与审批。", "Saved and applied to new analyses and approvals.") : t("最后更新", "Last updated") + ` · ${new Date(state.updated_at).toLocaleString(language === "zh" ? "zh-CN" : "en-US")}`}</span><button className="action-btn" disabled={saving}>{saving ? <LoaderCircle className="spin" size={16} /> : <ShieldCheck size={16} />}{t("保存硬限制", "Save Hard Limits")}</button></div>
    </form>
  </div>;
}

function CaseModule({ cases, onCasesChange, onDispatch }: { cases: CaseSummary[]; onCasesChange: (cases: CaseSummary[]) => void; onDispatch: (caseItem: CaseDetail["case"]) => void }) {
  const language = useLanguage();
  const t = (zh: string, en: string) => bilingual(language, zh, en);
  const [selectedId, setSelectedId] = useState(cases[0]?.id || "");
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [objective, setObjective] = useState("");
  const initialBroker = localStorage.getItem("gateway-broker") || "deriv";
  const [symbol, setSymbol] = useState<string>(brokerDefaultSymbol(initialBroker));
  const [brokerId, setBrokerId] = useState(initialBroker);
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
      const response = await fetch(`${API}/api/cases`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ objective, symbol, broker_id: brokerId }) });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || t("任务创建失败", "Failed to create trade case"));
      const created = payload.case as CaseDetail["case"];
      const summary: CaseSummary = { id: created.id, title: created.title, symbol: created.symbol, broker_id: created.broker_id, status: created.status, stage: created.stage, version: created.version, updated_at: created.updated_at };
      onCasesChange([summary, ...cases]);
      setObjective(""); setSelectedId(created.id);
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("任务创建失败", "Failed to create trade case")); }
    finally { setCreating(false); }
  }

  return <div className="case-workbench">
    <aside className="case-index">
      <form className="case-create" onSubmit={createCase}><p className="eyebrow">NEW TRADE CASE</p><textarea value={objective} onChange={(event) => setObjective(event.target.value)} placeholder={t("例如：用不超过 1 美元验证 R_75 的短线机会", "Example: validate an R_75 short-term opportunity with no more than USD 1")} rows={3} /><select value={brokerId} onChange={(event) => { const next = event.target.value; setBrokerId(next); setSymbol(brokerDefaultSymbol(next)); }} aria-label={t("任务券商", "Trade case broker")}>{BROKER_OPTIONS.map((broker) => <option value={broker.id} key={broker.id}>{broker.name}</option>)}</select><div><input value={symbol} onChange={(event) => setSymbol(event.target.value.toUpperCase())} aria-label={t("任务交易品种", "Trade case symbol")} /><button className="action-btn" disabled={creating || !objective.trim()}>{creating ? <LoaderCircle className="spin" size={15} /> : <Plus size={15} />} {t("新建", "Create")}</button></div>{error && <span className="form-error">{error}</span>}</form>
      <div className="case-stack">{cases.map((item) => <button key={item.id} className={selectedId === item.id ? "active" : ""} onClick={() => setSelectedId(item.id)}><div><strong>{localizedCaseText(item.title, item.symbol, language)}</strong><code>{brokerName(item.broker_id)} · {item.symbol}</code></div><span>{humanStage(item.stage, language)}</span><small>{humanCaseStatus(item.status, language)} · v{item.version}</small></button>)}{cases.length === 0 && <div className="module-empty">{t("还没有任务。", "No trade cases yet.")}</div>}</div>
    </aside>
    <section className="case-detail">{detail ? <><div className="case-detail-head"><div><p className="eyebrow">{detail.case.id}</p><h2>{localizedCaseText(detail.case.title, detail.case.symbol, language)}</h2><p>{localizedCaseText(detail.case.objective, detail.case.symbol, language)}</p></div><button className="action-btn" onClick={() => onDispatch(detail.case)}><Bot size={16} /> {t("交给经理分析", "Send to Manager")}</button></div><div className="case-status-band"><Metric label={t("平台", "Broker")} value={brokerName(detail.case.broker_id)} /><Metric label={t("市场", "Market")} value={detail.case.symbol} /><Metric label={t("阶段", "Stage")} value={humanStage(detail.case.stage, language)} /><Metric label={t("同步版本", "Sync Version")} value={`v${detail.case.version}`} /></div><div className="case-decision"><p className="eyebrow">{t("决策快照", "DECISION SNAPSHOT")}</p><h3>{caseDecisionSummary(detail.decision, language)}</h3><div className="case-evidence"><Evidence label={t("谋士结论", "Advisor Decision")} value={detail.decision.advisor?.action ? humanAction(detail.decision.advisor.action, language) : t("尚未运行", "Not Run")} /><Evidence label={t("最新行情", "Latest Market")} value={detail.decision.market?.latest_close == null ? t("尚未读取", "Not Loaded") : `${detail.case.symbol} · ${formatNumber(detail.decision.market.latest_close)}`} /><Evidence label={t("纸面交易", "Paper Trades")} value={`${detail.decision.paper?.trade_count || 0} ${t("次", "trades")}`} /><Evidence label={t("下一步", "Next Step")} value={humanWorkflowStep(detail.decision.workflow_step, language)} /></div></div><div className="case-timeline"><p className="eyebrow">{t("审计时间线", "AUDIT TIMELINE")}</p>{detail.events.map((event) => <div key={event.id}><span>{new Date(event.created_at).toLocaleString(language === "zh" ? "zh-CN" : "en-US")}</span><strong>{localizedEventMessage(event.message, language)}</strong><code>{humanStage(event.stage, language)} · v{event.version}</code></div>)}</div></> : <div className="module-empty large"><CircleDollarSign size={30} /><h2>{t("选择或创建交易任务", "Select or Create a Trade Case")}</h2><p>{t("任务会保存目标、证据、同步版本和完整审计记录。", "Cases preserve the objective, evidence, sync version, and full audit trail.")}</p></div>}</section>
  </div>;
}

function AdvisorModule({ agents }: { agents: AgentSpec[] }) {
  const language = useLanguage();
  const t = (zh: string, en: string) => bilingual(language, zh, en);
  return <div className="advisor-list">
    <div className="advisor-list-head"><span>Agent</span><span>{t("职责与独立 Prompt", "Role & Dedicated Prompt")}</span><span>{t("状态", "Status")}</span></div>
    {agents.map((agent, index) => <article className="advisor-row" key={agent.id}>
      <div className="advisor-identity"><span>{String(index + 1).padStart(2, "0")}</span><div><strong>{agentDisplayName(agent, language)}</strong><code>{agent.id}</code></div></div>
      <p>{agentDisplayPrompt(agent, language)}</p>
      <em><span className="ok-dot" /> {t("已加载", "Loaded")}</em>
    </article>)}
    {agents.length === 0 && <div className="module-empty">{t("Agent Prompt 注册表暂时不可用。", "The agent prompt registry is currently unavailable.")}</div>}
  </div>;
}

function MarketModule() {
  const language = useLanguage();
  const t = (zh: string, en: string) => bilingual(language, zh, en);
  const initialBroker = BROKER_OPTIONS.some((item) => item.id === localStorage.getItem("gateway-broker")) ? String(localStorage.getItem("gateway-broker")) : "deriv";
  const [brokerId, setBrokerId] = useState(initialBroker);
  const [selected, setSelected] = useState<string>(brokerDefaultSymbol(initialBroker));
  const [market, setMarket] = useState<MarketData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const marketSupported = brokerVisual(brokerId).marketData;

  function switchBroker(next: string) {
    setBrokerId(next); setSelected(brokerDefaultSymbol(next)); setMarket(null); setError("");
    localStorage.setItem("gateway-broker", next);
    window.dispatchEvent(new CustomEvent("broker-default-changed", { detail: next }));
  }

  async function loadMarket() {
    if (!marketSupported) { setError(t("该券商尚未建立认证行情会话，请先在券商中心连接账户。", "This broker needs an authenticated market session. Connect it in Broker Hub first.")); return; }
    setLoading(true); setError("");
    try {
      const response = await fetch(`${API}/api/market/${encodeURIComponent(selected)}?broker_id=${encodeURIComponent(brokerId)}`);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || t("行情读取失败", "Failed to load market data"));
      setMarket(payload.market);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("行情读取失败", "Failed to load market data"));
    } finally { setLoading(false); }
  }

  return <div className="work-surface">
    <div className="control-strip"><label>{t("数据平台", "Market Provider")}<select value={brokerId} onChange={(event) => switchBroker(event.target.value)}>{BROKER_OPTIONS.map((broker) => <option value={broker.id} key={broker.id}>{broker.name}{brokerVisual(broker.id).marketData ? "" : ` · ${t("需连接", "connection required")}`}</option>)}</select></label><label>{t("交易品种", "Symbol")}<input value={selected} onChange={(event) => setSelected(event.target.value.toUpperCase())} /></label><button className="action-btn" onClick={loadMarket} disabled={loading || !marketSupported}>{loading ? <LoaderCircle className="spin" size={16} /> : <RefreshCw size={16} />} {marketSupported ? t("获取最新行情", "Load Latest Market") : t("需要认证行情", "Market Session Required")}</button></div>
    {!marketSupported && <div className="broker-capability-notice"><AlertTriangle size={17} /><div><strong>{brokerName(brokerId)} · {t("认证行情尚未接入", "Authenticated market data not connected")}</strong><span>{t("账户诊断可以使用，但图表和小笔策略不会回退到其他券商的数据。", "Account diagnostics remain available, but charts and micro strategy will not fall back to another broker's data.")}</span></div></div>}
    {error && <div className="inline-alert"><AlertTriangle size={17} />{error}</div>}
    {!market && !error && <div className="module-empty large"><CandlestickChart size={30} /><h2>{t("选择市场并读取行情", "Select a Market to Load Data")}</h2><p>{t("系统会同时获取最新 Tick 和 60 根 K 线，不会执行任何交易。", "The system loads the latest tick and 60 candles without executing any trade.")}</p></div>}
    {market && <MarketSnapshot market={market} />}
  </div>;
}

function MarketSnapshot({ market }: { market: MarketData }) {
  const language = useLanguage();
  const t = (zh: string, en: string) => bilingual(language, zh, en);
  const change = Number(market.window_change_pct || 0);
  const values = market.closes || [];
  const width = 900, height = 250;
  const min = Math.min(...values), max = Math.max(...values);
  const points = values.map((value, index) => `${(index / Math.max(values.length - 1, 1)) * width},${height - ((value - min) / Math.max(max - min, 0.000001)) * (height - 24) - 12}`).join(" ");
  return <div className="market-result" data-market-broker={market.broker_id || "deriv"}>
    <div className="metric-band"><Metric label={t("最新价格", "Latest Price")} value={formatNumber(market.tick?.quote ?? market.latest_close)} /><Metric label={t("60 分钟变化", "60-Min Change")} value={`${change >= 0 ? "+" : ""}${change.toFixed(3)}%`} tone={change >= 0 ? "positive" : "negative"} /><Metric label={t("K 线数量", "Candles")} value={String(market.candle_count)} /><Metric label={t("数据状态", "Data Status")} value={market.ok ? t("实时可用", "Live") : t("不完整", "Incomplete")} tone={market.ok ? "positive" : "warning"} /></div>
    <div className="chart-panel"><div className="chart-heading"><div><strong>{brokerName(market.broker_id)} · {market.symbol}</strong><span>{t("最近 60 根 1 分钟收盘价", "Latest 60 one-minute closes")}</span></div>{change >= 0 ? <TrendingUp size={22} /> : <TrendingDown size={22} />}</div>{values.length > 1 ? <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${market.symbol} ${t("收盘价趋势", "close-price trend")}`}><polyline className="market-line" pathLength="1" points={points} fill="none" stroke={change >= 0 ? "var(--broker-accent)" : "var(--coral)"} strokeWidth="3" vectorEffect="non-scaling-stroke" /></svg> : <div className="module-empty">{t("没有足够数据绘图。", "Not enough data to draw the chart.")}</div>}</div>
  </div>;
}

function StrategyModule() {
  const language = useLanguage();
  const t = (zh: string, en: string) => bilingual(language, zh, en);
  const initialBroker = BROKER_OPTIONS.some((item) => item.id === localStorage.getItem("gateway-broker")) ? String(localStorage.getItem("gateway-broker")) : "deriv";
  const [symbol, setSymbol] = useState<string>(brokerDefaultSymbol(initialBroker));
  const [brokerId, setBrokerId] = useState(initialBroker);
  const [amount, setAmount] = useState(1);
  const [result, setResult] = useState<StrategyResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const marketSupported = brokerVisual(brokerId).marketData;

  function switchBroker(next: string) {
    setBrokerId(next); setSymbol(brokerDefaultSymbol(next)); setResult(null); setError("");
    localStorage.setItem("gateway-broker", next);
    window.dispatchEvent(new CustomEvent("broker-default-changed", { detail: next }));
  }

  async function analyze() {
    if (!marketSupported) { setError(t("该券商尚未建立认证行情会话，不能用其他券商的数据替代回测。", "This broker has no authenticated market session, so another broker's data cannot be substituted for the backtest.")); return; }
    setLoading(true); setError("");
    try {
      const response = await fetch(`${API}/api/strategy/analyze`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ symbol, amount, broker_id: brokerId }) });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || t("策略分析失败", "Strategy analysis failed"));
      setResult(payload);
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("策略分析失败", "Strategy analysis failed")); }
    finally { setLoading(false); }
  }

  const decision = result?.decision || {};
  const summary = result?.backtest?.summary || {};
  return <div className="work-surface">
    <div className="control-strip strategy-controls"><label>{t("数据平台", "Market Provider")}<select value={brokerId} onChange={(event) => switchBroker(event.target.value)}>{BROKER_OPTIONS.map((broker) => <option value={broker.id} key={broker.id}>{broker.name}{brokerVisual(broker.id).marketData ? "" : ` · ${t("需连接", "connection required")}`}</option>)}</select></label><label>{t("交易品种", "Symbol")}<input value={symbol} onChange={(event) => setSymbol(event.target.value.toUpperCase())} /></label><label>{t("单笔上限（USD）", "Per-Trade Cap (USD)")}<input type="number" min="0.1" max="10" step="0.1" value={amount} onChange={(event) => setAmount(Number(event.target.value))} /></label><button className="action-btn" onClick={analyze} disabled={loading || !marketSupported}>{loading ? <LoaderCircle className="spin" size={16} /> : <BarChart3 size={16} />} {marketSupported ? t("分析并纸面回测", "Analyze & Paper Backtest") : t("需要认证行情", "Market Session Required")}</button></div>
    {!marketSupported && <div className="broker-capability-notice"><AlertTriangle size={17} /><div><strong>{brokerName(brokerId)} · {t("暂不能运行纸面策略", "Paper strategy unavailable")}</strong><span>{t("先在券商中心连接账户并完成该平台的行情适配。系统不会混用其他券商的价格。", "Connect the account and its market adapter in Broker Hub first. The system will not mix prices from another broker.")}</span></div></div>}
    <div className="safety-line"><ShieldCheck size={16} />{t("这里只读取行情、计算信号和纸面回测，不会提交订单。", "This module only reads market data, computes signals, and runs paper backtests. It never submits orders.")}</div>
    {error && <div className="inline-alert"><AlertTriangle size={17} />{error}</div>}
    {!result && !error && <div className="module-empty large"><BrainCircuit size={30} /><h2>{t("输入品种和严格预算", "Set a Symbol and Strict Budget")}</h2><p>{t("你会得到当前动作、信心、阻断原因、风险参数和历史窗口纸面结果。", "You will receive the current action, confidence, blockers, risk parameters, and paper results for the historical window.")}</p></div>}
    {result && <div className="strategy-result">
      <div className="decision-banner"><div><span>{t("当前建议", "Current Recommendation")}</span><strong>{humanAction(decision.action, language)}</strong></div><div><span>{t("信心", "Confidence")}</span><strong>{Math.round(Number(decision.confidence || 0) * 100)}%</strong></div><div><span>{t("最新价", "Latest Price")}</span><strong>{formatNumber(decision.latest_price)}</strong></div><div><span>{t("预算检查", "Budget Check")}</span><strong>{result.budget.ok ? t("通过", "Passed") : t("拦截", "Blocked")}</strong></div></div>
      {!result.budget.ok && <div className="blocker-strip"><strong>{t("当前不能进入审批", "Why this cannot enter approval")}</strong><div>{(result.budget.blockers || []).map((code: string) => <span key={code}>{blockerLabel(code, language)}</span>)}</div></div>}
      <div className="evidence-grid"><section><p className="eyebrow">{t("为什么", "WHY")}</p><h2>{t("信号证据", "Signal Evidence")}</h2><Evidence label={t("3 根动量", "3-Bar Momentum")} value={`${Number(decision.momentum_3_pct || 0).toFixed(4)}%`} /><Evidence label={t("7 根动量", "7-Bar Momentum")} value={`${Number(decision.momentum_7_pct || 0).toFixed(4)}%`} /><Evidence label={t("波动率", "Volatility")} value={`${Number(decision.volatility_pct || 0).toFixed(4)}%`} /><Evidence label={t("阻断原因", "Blockers")} value={(decision.blockers || []).length ? decision.blockers.map((code: string) => blockerLabel(code, language)).join(language === "zh" ? "、" : ", ") : t("无", "None")} /></section><section><p className="eyebrow">{t("纸面结果", "PAPER RESULTS")}</p><h2>{t("窗口回测", "Window Backtest")}</h2><Evidence label={t("交易次数", "Trades")} value={String(summary.trade_count ?? 0)} /><Evidence label={t("胜率", "Win Rate")} value={summary.win_rate == null ? t("暂无交易", "No Trades") : `${(Number(summary.win_rate) * 100).toFixed(1)}%`} /><Evidence label={t("累计 PnL", "Cumulative PnL")} value={formatNumber(summary.total_pnl, 6)} /><Evidence label={t("熔断", "Circuit Breaker")} value={summary.halted ? `${t("是", "Yes")}: ${summary.halt_reason}` : t("否", "No")} /></section></div>
    </div>}
  </div>;
}

function MonitorModule({ health, provider, agentCount, runs }: { health: HealthInfo | null; provider: string; agentCount: number; runs: AgentRun[] }) {
  const language = useLanguage();
  const t = (zh: string, en: string) => bilingual(language, zh, en);
  const checks = [
    { label: t("API 服务", "API Service"), value: health?.ok ? t("在线", "Online") : t("未连接", "Disconnected"), detail: health?.runtime || "FastAPI", icon: RadioTower },
    { label: t("回答传输", "Response Transport"), value: health?.streaming === "sse" ? t("真流式", "True Streaming") : t("待检查", "Needs Check"), detail: "Server-Sent Events", icon: AudioWaveform },
    { label: t("本地记忆", "Local Memory"), value: health?.database ? t("已连接", "Connected") : t("待检查", "Needs Check"), detail: health?.database || "SQLite", icon: Database },
    { label: t("Agent 注册", "Agent Registry"), value: `${agentCount} ${t("个", "agents")}`, detail: t("独立 Prompt 与独立调用", "Dedicated prompts and independent calls"), icon: Network },
    { label: t("当前模型", "Current Model"), value: provider, detail: t("密钥仅驻留当前页面内存", "The key remains only in this page's memory"), icon: Sparkles },
    { label: t("前端构建", "Frontend Build"), value: health?.frontend_built ? t("已加载", "Loaded") : t("待构建", "Not Built"), detail: "React + Vite", icon: LayoutDashboard }
  ];
  return <div className="monitor-stack">
    <div className="monitor-grid">{checks.map((check, index) => <article key={check.label} style={{ animationDelay: `${index * 45}ms` }}><div className="monitor-icon"><check.icon size={18} /></div><span>{check.label}</span><strong>{check.value}</strong><small>{check.detail}</small></article>)}</div>
    <section className="run-ledger">
      <div className="run-ledger-head"><div><p className="eyebrow">PERSISTENT RUN TRACE</p><h2>{t("最近 Agent 运行", "Recent Agent Runs")}</h2></div><span>{t("刷新后仍保留", "Preserved after refresh")}</span></div>
      <div className="run-ledger-table">
        <div className="run-ledger-row run-ledger-labels"><span>{t("运行 / 时间", "Run / Time")}</span><span>{t("状态", "Status")}</span><span>{t("目标", "Target")}</span><span>Agent</span><span>{t("耗时", "Duration")}</span></div>
        {runs.slice(0, 12).map((run) => {
          const completed = run.spans.filter((span) => span.status === "completed").length;
          const failed = run.spans.filter((span) => span.status !== "completed").length;
          return <div className="run-ledger-row" key={run.id}>
            <div><code>{run.id}</code><small>{new Date(run.created_at).toLocaleString()}</small></div>
            <span className={`run-status run-status--${run.status}`}>{humanRunStatus(run.status, language)}</span>
            <div><strong>{run.symbol || "--"}</strong><small>{run.provider} · {run.model}</small></div>
            <span>{completed} {t("成功", "passed")}{failed ? ` / ${failed} ${t("降级", "degraded")}` : ""}</span>
            <span>{run.elapsed_ms == null ? t("运行中", "Running") : formatDuration(run.elapsed_ms)}</span>
          </div>;
        })}
        {runs.length === 0 && <div className="module-empty">{t("还没有 Agent 运行记录。完成一次指令后，这里会形成可追溯账本。", "No agent runs yet. Completing a request will create a persistent trace here.")}</div>}
      </div>
    </section>
  </div>;
}

function Metric({ label, value, tone = "" }: { label: string; value: string; tone?: string }) { return <div className={`metric metric--${tone}`}><span>{label}</span><strong>{value}</strong></div>; }
function Evidence({ label, value }: { label: string; value: string }) { return <div className="evidence-row"><span>{label}</span><strong>{value}</strong></div>; }
function formatNumber(value: unknown, digits = 5) { const number = Number(value); return Number.isFinite(number) ? number.toFixed(digits).replace(/\.?0+$/, "") : "--"; }
function formatMoney(value: unknown, currency: unknown) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  const code = String(currency || "USD").toUpperCase();
  try { return new Intl.NumberFormat(undefined, { style: "currency", currency: code, maximumFractionDigits: 2 }).format(number); }
  catch { return `${code} ${number.toFixed(2)}`; }
}
function humanAction(action: unknown, language: Language) {
  const zh = { CALL: "看涨（CALL）", PUT: "看跌（PUT）", WAIT: "等待，不入场", BUY: "买入", SELL: "卖出", HOLD: "持有" } as Record<string, string>;
  const en = { CALL: "Bullish (CALL)", PUT: "Bearish (PUT)", WAIT: "Wait / No Entry", BUY: "Buy", SELL: "Sell", HOLD: "Hold" } as Record<string, string>;
  return (language === "zh" ? zh : en)[String(action)] || String(action || bilingual(language, "无信号", "No Signal"));
}
function brokerName(brokerId: unknown) { return BROKER_OPTIONS.find((broker) => broker.id === String(brokerId || "deriv"))?.name || String(brokerId || "Deriv"); }
function credentialLabel(field: string) {
  return ({ api_token: "API Token", app_id: "App ID", api_key: "API Key", api_secret: "API Secret", api_key_name: "API Key Name", private_key: "Private Key" } as Record<string, string>)[field] || field.replaceAll("_", " ");
}
function capabilityLabel(capability: string, language: Language) {
  const zh: Record<string, string> = { market_data: "实时行情", account: "账户", positions: "持仓", options_contracts: "数字期权合约", equities: "股票", crypto: "加密资产", forex: "外汇", cfd: "差价合约", options: "期权", futures: "期货", bonds: "债券", spot: "现货", paper: "模拟盘", live_orders: "实盘订单" };
  const en: Record<string, string> = { market_data: "Market Data", account: "Account", positions: "Positions", options_contracts: "Options Contracts", equities: "Equities", crypto: "Crypto", forex: "Forex", cfd: "CFDs", options: "Options", futures: "Futures", bonds: "Bonds", spot: "Spot", paper: "Paper", live_orders: "Live Orders" };
  return (language === "zh" ? zh : en)[capability] || capability.replaceAll("_", " ");
}
function integrationLevelLabel(level: BrokerDefinition["integration_level"], language: Language, compact = false) {
  const labels = {
    full_adapter: compact ? ["完整", "FULL"] : ["完整适配器", "Full Adapter"],
    market_and_account: compact ? ["行情+账户", "DATA + ACCOUNT"] : ["实时行情 + 账户诊断", "Live Data + Account Diagnostics"],
    market_data_only: compact ? ["公开行情", "PUBLIC DATA"] : ["公开行情与纸面策略", "Public Data + Paper Strategy"],
    account_diagnostic: compact ? ["账户诊断", "ACCOUNT CHECK"] : ["仅账户连接诊断", "Account Diagnostics Only"],
    catalog_only: compact ? ["仅目录", "CATALOG"] : ["仅目录信息", "Catalog Only"],
  } as const;
  return language === "zh" ? labels[level][0] : labels[level][1];
}
function humanRunStatus(status: unknown, language: Language) {
  const zh = { idle: "待命", running: "运行中", completed: "已完成", degraded: "降级完成", failed: "失败", cancelled: "已停止", interrupted: "重启中断" } as Record<string, string>;
  const en = { idle: "Idle", running: "Running", completed: "Completed", degraded: "Completed with Degradation", failed: "Failed", cancelled: "Stopped", interrupted: "Interrupted by Restart" } as Record<string, string>;
  return (language === "zh" ? zh : en)[String(status)] || String(status);
}
function formatDuration(value: number) { return value < 1000 ? `${value} ms` : `${(value / 1000).toFixed(value < 10_000 ? 1 : 0)} s`; }
function humanStage(stage: unknown, language: Language) {
  const zh = { draft: "任务草稿", advisor_review: "谋士分析", market_validation: "行情验证", micro_backtest: "纸面回测", risk_review: "风控复核", awaiting_confirmation: "等待确认", execution: "执行中", review: "复盘" } as Record<string, string>;
  const en = { draft: "Draft", advisor_review: "Advisor Review", market_validation: "Market Validation", micro_backtest: "Paper Backtest", risk_review: "Risk Review", awaiting_confirmation: "Awaiting Approval", execution: "Executing", review: "Review" } as Record<string, string>;
  return (language === "zh" ? zh : en)[String(stage)] || String(stage || bilingual(language, "未知", "Unknown"));
}
function humanCaseStatus(status: unknown, language: Language) {
  const zh = { active: "进行中", paused: "已暂停", completed: "已完成", cancelled: "已取消", failed: "失败" } as Record<string, string>;
  const en = { active: "Active", paused: "Paused", completed: "Completed", cancelled: "Cancelled", failed: "Failed" } as Record<string, string>;
  return (language === "zh" ? zh : en)[String(status)] || String(status || bilingual(language, "未知", "Unknown"));
}
function humanWorkflowStep(step: unknown, language: Language) {
  const zh = { manager_dispatch: "经理调度", advisor_review: "谋士分析", market_validation: "行情验证", micro_backtest: "小笔策略回测", risk_review: "风控复核", human_confirmation: "人工确认" } as Record<string, string>;
  const en = { manager_dispatch: "Manager Dispatch", advisor_review: "Advisor Review", market_validation: "Market Validation", micro_backtest: "Micro-Strategy Backtest", risk_review: "Risk Review", human_confirmation: "Human Approval" } as Record<string, string>;
  return (language === "zh" ? zh : en)[String(step)] || bilingual(language, "等待经理安排", "Awaiting Manager");
}
function decisionStateLabel(state: DecisionItem["state"], language: Language) {
  const zh = { ready: "可审批", blocked: "被阻断", evidence_requested: "待补证据", approved: "已批准", rejected: "已拒绝" };
  const en = { ready: "Ready", blocked: "Blocked", evidence_requested: "Evidence Requested", approved: "Approved", rejected: "Rejected" };
  return (language === "zh" ? zh : en)[state];
}
function blockerLabel(code: string, language: Language) {
  const zh: Record<string, string> = {
    analysis_only: "当前仅分析",
    micro_strategy_not_run: "尚未完成小笔回测",
    human_confirmation_required: "仍需人工确认",
    missing_trade_draft: "缺少交易草稿",
    single_trade_limit_exceeded: "超过单笔上限",
    daily_budget_exceeded: "超过每日预算",
    total_budget_exceeded: "超过累计预算",
    daily_loss_limit_reached: "达到每日亏损上限",
    open_position_limit_reached: "达到持仓数量上限",
    broker_mismatch: "证据来自不同券商",
    trade_cooldown_active: "上一笔交易仍在冷却期",
    invalid_last_trade_timestamp: "最近交易时间记录无效",
    invalid_amount: "交易金额无效",
    circuit_breaker_halted: "纸面回测已触发熔断",
  };
  const en: Record<string, string> = {
    analysis_only: "Analysis only",
    micro_strategy_not_run: "Micro backtest missing",
    human_confirmation_required: "Human confirmation required",
    missing_trade_draft: "Trade draft missing",
    single_trade_limit_exceeded: "Per-trade limit exceeded",
    daily_budget_exceeded: "Daily budget exceeded",
    total_budget_exceeded: "Lifetime budget exceeded",
    daily_loss_limit_reached: "Daily loss limit reached",
    open_position_limit_reached: "Open-position limit reached",
    broker_mismatch: "Evidence comes from different brokers",
    trade_cooldown_active: "Previous trade is still cooling down",
    invalid_last_trade_timestamp: "Last-trade timestamp is invalid",
    invalid_amount: "Trade amount is invalid",
    circuit_breaker_halted: "Paper backtest triggered a circuit breaker",
  };
  return (language === "zh" ? zh : en)[code] || code.replaceAll("_", " ");
}
function containsHan(text: string) { return /[\u3400-\u9fff]/.test(text); }
function localizedCaseText(text: string, symbol: string, language: Language) {
  if (language === "zh" || !containsHan(text)) return text;
  const opportunity = text.match(/验证\s+([A-Z0-9_]+)\s+最近\s+(\d+)\s+分钟的短线机会[，,]\s*只做分析并同步证据/);
  if (opportunity) return `Validate the ${opportunity[1]} short-term opportunity over the latest ${opportunity[2]} minutes; analysis and evidence sync only.`;
  const marketReview = text.match(/请分析\s+([A-Z0-9_]+)\s+最近\s+(\d+)\s+分钟走势/);
  if (marketReview) return `Analyze the ${marketReview[1]} trend over the latest ${marketReview[2]} minutes.`;
  return `Legacy trade case for ${symbol}. Switch to ZH to view the original objective.`;
}
function localizedMessage(content: string, role: Message["role"], language: Language) {
  if (language === "zh" || !containsHan(content)) return content;
  const dispatch = content.match(/请接手交易任务\s+(TC-[A-Z0-9]+)[：:]([\s\S]*?)[。.]先让谋士团和行情\s+Agent\s+分析\s+([A-Z0-9_]+)/);
  if (dispatch) {
    const objective = localizedCaseText(dispatch[2].trim(), dispatch[3], language);
    return `Take ownership of trade case ${dispatch[1]}: ${objective} Ask the advisor council and market agent to analyze ${dispatch[3]}, then sync market evidence, conclusions, and risk requirements back to the case.`;
  }
  const marketRequest = content.match(/请分析\s+([A-Z0-9_]+)\s+最近\s+(\d+)\s+分钟走势/);
  if (marketRequest) return `Analyze the ${marketRequest[1]} trend over the latest ${marketRequest[2]} minutes. Ask strategy, market, risk, and compliance agents for evidence. Analysis only; do not place an order.`;
  const managerRun = content.match(/我已让团队围绕\s+([A-Z0-9_]+)\s+完成一轮分析/);
  if (managerRun) {
    const latest = content.match(/最新价\s+([\d.]+)/)?.[1] || "unavailable";
    const change = content.match(/窗口变化\s+([+-]?[\d.]+%)/)?.[1] || "unavailable";
    return `The team completed one analysis round for ${managerRun[1]}.\n\n- Strategy: define the observation window, entry and exit rules, and maximum trade amount; keep WAIT when evidence is insufficient.\n- Market: latest price ${latest}; 60-minute change ${change}.\n- Risk: use small demo validation with strict trade, budget, and maximum-loss limits.\n- Compliance: real write operations require explicit parameters and human approval.\n\nConclusion: analysis only. No order was placed.`;
  }
  if (content.includes("介绍一下你的能力")) return "Explain your capabilities.";
  return role === "user"
    ? "Legacy request created in Chinese. Switch to ZH to view the original."
    : "Legacy agent response created in Chinese. Switch to ZH to view the original.";
}
function humanEventMessage(message: string, language: Language = "zh") {
  const zh = { "Trade case created": "交易任务已创建" } as Record<string, string>;
  const en = {
    "Trade case created": "Trade case created",
    "经理已派发本轮多 Agent 分析": "The manager dispatched this multi-agent analysis run",
    "谋士团结论已从经理对话同步": "Advisor council conclusions synced from the manager conversation",
    "行情快照已同步到交易任务": "Market snapshot synced to the trade case",
    "风控 Agent 已记录剩余前置条件": "The risk agent recorded the remaining prerequisites",
    "本轮分析完成，下一步进入小笔策略纸面回测": "Analysis completed; the next step is a Micro Strategy paper backtest"
  } as Record<string, string>;
  return (language === "zh" ? zh : en)[message] || message;
}
function localizedEventMessage(message: string, language: Language = "zh") {
  const translated = humanEventMessage(message, language);
  if (language === "en" && containsHan(translated)) return "Legacy audit event. Switch to ZH to view the original.";
  return translated;
}
function caseDecisionSummary(decision: Record<string, any>, language: Language = "zh") {
  const status = String(decision.status || "not_started");
  if (status === "not_started") return bilingual(language, "任务已记录，等待经理开始组织分析。", "The case is recorded and waiting for the manager to begin analysis.");
  if (status === "awaiting_confirmation") return bilingual(language, "证据链已通过检查，正在等待人工确认。", "The evidence chain passed validation and is awaiting human approval.");
  if (status === "blocked") return language === "zh" ? `任务被安全闸门拦截：${(decision.gate?.blockers || []).join("、") || "需要补充证据"}` : `Blocked by the safety gate: ${(decision.gate?.blockers || []).join(", ") || "additional evidence required"}`;
  if (status === "failed") return language === "zh" ? `任务运行失败，可从 ${decision.retry_step || "失败步骤"} 重试。` : `The case failed and can be retried from ${decision.retry_step || "the failed step"}.`;
  if (status === "completed") return bilingual(language, "任务已经完成，结果和回执已进入审计记录。", "The case is complete; results and receipts are stored in the audit trail.");
  if (decision.workflow_step === "micro_backtest") return bilingual(language, "谋士结论和行情证据已保存。下一步请到小笔策略完成纸面回测，再进入风控确认。", "Advisor conclusions and market evidence are saved. Next, complete a paper backtest in Micro Strategy before risk approval.");
  return language === "zh" ? `任务正在 ${decision.stage || "分析"} 阶段推进。` : `The case is progressing through ${decision.stage || "analysis"}.`;
}

const AGENT_EN: Record<string, { name: string; prompt: string }> = {
  manager: { name: "Trading Manager", prompt: "Breaks the executive goal into market, strategy, risk, compliance, execution, and reporting tasks. Never places orders directly." },
  market: { name: "Market Analyst", prompt: "Reads Deriv ticks and candles, then reports trends, consecutive moves, and trigger conditions in a concise, auditable form." },
  strategy: { name: "Strategy Researcher", prompt: "Converts the trading goal into hypotheses, observation windows, entry and exit rules, and required agent collaboration." },
  risk: { name: "Risk Officer", prompt: "Checks tokens, accounts, amounts, live/demo boundaries, and maximum loss. Protecting capital is the default priority." },
  compliance: { name: "Compliance Reviewer", prompt: "Blocks ambiguous, unauthorized, directionless, all-in, or safety-bypass requests." },
  chart: { name: "Chart Engineer", prompt: "Builds candle snapshots, compares price action, measures windows, and prepares downloadable data." },
  execution: { name: "Execution Trader", prompt: "The only agent allowed to submit Deriv write operations, and only after risk, compliance, and human approval." },
  report: { name: "Reporting Agent", prompt: "Turns each collaboration run into a timeline, structured result, receipt, and review summary." }
};
function agentDisplayName(agent: AgentSpec, language: Language) { return language === "en" ? AGENT_EN[agent.id]?.name || agent.id : agent.name || agent.id; }
function agentDisplayPrompt(agent: AgentSpec, language: Language) { return language === "en" ? AGENT_EN[agent.id]?.prompt || "Analyze under the registered role and report to the trading manager." : agent.prompt || "使用默认职责分析并向交易经理提交报告。"; }

function SessionDrawer({ sessions, currentId, onSelect, onNew, onClose }: { sessions: ChatSession[]; currentId: string; onSelect: (id: string) => void; onNew: () => void; onClose: () => void }) {
  const language = useLanguage();
  const t = (zh: string, en: string) => bilingual(language, zh, en);
  return <div className="drawer-layer drawer-layer--left" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <aside className="session-drawer">
      <div className="drawer-head"><div><p className="eyebrow">LOCAL MEMORY</p><h2>{t("历史对话", "Conversation History")}</h2></div><button className="icon-btn" onClick={onClose} aria-label={t("关闭历史对话", "Close conversation history")}><X size={18} /></button></div>
      <button className="primary-wide" onClick={onNew}><Plus size={17} /> {t("开始新对话", "Start New Chat")}</button>
      <div className="session-list">{sessions.map((session) => <button key={session.id} className={session.id === currentId ? "active" : ""} onClick={() => onSelect(session.id)}><div className="session-icon"><MessageSquareText size={16} /></div><div><strong>{localizedMessage(session.title, "user", language)}</strong><span>{session.preview ? localizedMessage(session.preview, "assistant", language) : t("尚无消息", "No messages yet")}</span><small>{session.message_count} {t("条消息", "messages")} · {relativeTime(session.updated_at, language)}</small></div></button>)}{sessions.length === 0 && <div className="module-empty">{t("还没有历史对话。", "No saved conversations yet.")}</div>}</div>
      <div className="session-foot"><Database size={15} /><span>{t("全部会话仅保存在本机 SQLite", "All conversations are stored only in local SQLite")}</span></div>
    </aside>
  </div>;
}

function relativeTime(value: string, language: Language = "zh") {
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 60) return bilingual(language, "刚刚", "Just now");
  if (seconds < 3600) return language === "zh" ? `${Math.floor(seconds / 60)} 分钟前` : `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return language === "zh" ? `${Math.floor(seconds / 3600)} 小时前` : `${Math.floor(seconds / 3600)} hr ago`;
  return language === "zh" ? `${Math.floor(seconds / 86400)} 天前` : `${Math.floor(seconds / 86400)} days ago`;
}

function SettingsDrawer({ provider, setProvider, apiKey, setApiKey, model, setModel, baseUrl, setBaseUrl, onClose }: {
  provider: Provider; setProvider: (value: Provider) => void; apiKey: string; setApiKey: (value: string) => void; model: string; setModel: (value: string) => void; baseUrl: string; setBaseUrl: (value: string) => void; onClose: () => void;
}) {
  const language = useLanguage();
  const t = (zh: string, en: string) => bilingual(language, zh, en);
  return <div className="drawer-layer" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <aside className="settings-drawer">
      <div className="drawer-head"><div><p className="eyebrow">RUNTIME SETTINGS</p><h2>{t("模型与密钥", "Models & API Keys")}</h2></div><button className="icon-btn" onClick={onClose} aria-label={t("关闭设置", "Close settings")}><X size={18} /></button></div>
      <div className="security-note"><ShieldCheck size={17} /><span>{t("API Key 只发送到本机 FastAPI 进程，不写入 SQLite，也不会出现在日志中。", "Your API key is sent only to the local FastAPI process. It is never stored in SQLite or written to logs.")}</span></div>
      <label>{t("模型提供商", "Model Provider")}<select value={provider} onChange={(event) => setProvider(event.target.value as Provider)}><option value="local">{t("本地规则", "Local Rules")}</option><option value="openai">OpenAI</option><option value="deepseek">DeepSeek</option><option value="anthropic">Anthropic</option><option value="compatible">OpenAI-Compatible</option></select></label>
      {provider !== "local" && <label>API Key<input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="sk-..." autoComplete="off" /></label>}
      <label>{t("模型名", "Model Name")}<input value={model} onChange={(event) => setModel(event.target.value)} placeholder={provider === "local" ? "local-rule-engine" : t("留空使用默认模型", "Leave blank to use the default model")} /></label>
      {provider === "compatible" && <label>Base URL<input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://your-api.example/v1" /></label>}
      <div className="drawer-agent-note"><BrainCircuit size={18} /><div><strong>{t("每个 Agent 独立调用", "Independent Calls per Agent")}</strong><span>{t("策略、行情、风控、合规和报告 Agent 分别使用自己的 Prompt；经理基于它们的报告流式总结。", "Strategy, market, risk, compliance, and reporting agents each use a dedicated prompt; the manager streams a synthesis of their reports.")}</span></div></div>
      <button className="primary-wide" onClick={onClose}><Check size={17} /> {t("应用设置", "Apply Settings")}</button>
    </aside>
  </div>;
}

export default App;
