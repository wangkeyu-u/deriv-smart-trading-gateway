export type Message = { role: "user" | "assistant"; content: string; streaming?: boolean };
export type AgentActivity = {
  id: string;
  name: string;
  state: "queued" | "running" | "done" | "error";
  report?: string;
  kind?: "agent" | "tool";
  durationMs?: number;
};
export type RunSummary = {
  runId: string;
  status: "idle" | "running" | "completed" | "degraded" | "failed" | "cancelled" | "interrupted";
  elapsedMs?: number;
  successCount?: number;
  failedCount?: number;
};
export type AgentRun = {
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
export type Provider = "local" | "openai" | "deepseek" | "anthropic" | "compatible";
export type CaseSummary = {
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
export type AgentSpec = { id: string; name: string; prompt: string };
export type HealthInfo = {
  ok: boolean;
  runtime: string;
  streaming: string;
  database: string;
  frontend_built: boolean;
};
export type MarketData = {
  broker_id?: string;
  symbol: string;
  tick?: { quote?: number; epoch?: number } | null;
  candle_count: number;
  window_change_pct?: number | null;
  latest_close?: number | null;
  closes?: number[];
  ok: boolean;
};
export type StrategyResult = {
  symbol: string;
  amount: number;
  market: MarketData;
  decision: Record<string, any>;
  budget: Record<string, any>;
  backtest: { ok: boolean; summary?: Record<string, any>; trades?: Record<string, any>[] };
};
export type CaseDetail = {
  case: CaseSummary & { objective: string; context: Record<string, any> };
  decision: Record<string, any>;
  events: Array<{ id: number; created_at: string; event_type: string; actor: string; message: string; stage: string; status: string; version: number }>;
};
export type ChatSession = { id: string; title: string; created_at: string; updated_at: string; message_count: number; preview: string };
export type DecisionItem = {
  case: CaseSummary;
  decision: Record<string, any>;
  state: "ready" | "blocked" | "evidence_requested" | "approved" | "rejected";
  evidence_score: number;
  blockers: string[];
  global_risk: Record<string, any>;
};
export type RiskPolicyState = {
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
export type BrokerDefinition = {
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
export type AccountSnapshot = {
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
export type BrokerConnectionResult = {
  ok: boolean;
  broker_id: string;
  status: string;
  message?: string;
  latency_ms?: number;
  checked_at?: string;
  account?: Record<string, unknown>;
  snapshot?: AccountSnapshot;
};
export type BrokerProfile = {
  id: string;
  broker_id: string;
  label: string;
  environment: string;
  account_id: string;
  is_default: boolean;
  settings: Record<string, unknown>;
  updated_at: string;
};
