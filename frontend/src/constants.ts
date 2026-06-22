import {
  LayoutDashboard,
  Building2,
  Inbox,
  BriefcaseBusiness,
  Network,
  ChartNoAxesCombined,
  FlaskConical,
  ShieldAlert,
  RadioTower,
  TrendingUp,
  CandlestickChart,
  CircleDollarSign,
  Waypoints,
  BarChart3,
} from "lucide-react";

export const NAV_ITEMS = [
  { id: "command", zh: "指挥中心", en: "Command Center", icon: LayoutDashboard },
  { id: "brokers", zh: "券商中心", en: "Broker Hub", icon: Building2 },
  { id: "decisions", zh: "决策审批", en: "Decision Inbox", icon: Inbox },
  { id: "cases", zh: "交易任务", en: "Trade Cases", icon: BriefcaseBusiness },
  { id: "advisors", zh: "谋士团", en: "Advisor Council", icon: Network },
  { id: "markets", zh: "行情图表", en: "Market Charts", icon: ChartNoAxesCombined },
  { id: "strategy", zh: "小笔策略", en: "Micro Strategy", icon: FlaskConical },
  { id: "risk", zh: "全局风控", en: "Risk Governor", icon: ShieldAlert },
  { id: "monitor", zh: "系统监控", en: "System Monitor", icon: RadioTower },
] as const;

export const BROKER_OPTIONS = [
  { id: "deriv", name: "Deriv" },
  { id: "alpaca", name: "Alpaca" },
  { id: "oanda", name: "OANDA" },
  { id: "ibkr", name: "Interactive Brokers" },
  { id: "coinbase", name: "Coinbase Advanced" },
  { id: "kraken", name: "Kraken" },
  { id: "binance", name: "Binance" },
];

export const BROKER_VISUALS: Record<string, { icon: any; accent: string; defaultSymbol: string; marketData: boolean }> = {
  deriv: { icon: RadioTower, accent: "#79d9b8", defaultSymbol: "R_75", marketData: true },
  alpaca: { icon: TrendingUp, accent: "#73b5da", defaultSymbol: "AAPL", marketData: false },
  oanda: { icon: CandlestickChart, accent: "#ef8b84", defaultSymbol: "EUR_USD", marketData: false },
  ibkr: { icon: Building2, accent: "#db8b76", defaultSymbol: "AAPL", marketData: false },
  coinbase: { icon: CircleDollarSign, accent: "#7fa8f7", defaultSymbol: "BTC-USD", marketData: true },
  kraken: { icon: Waypoints, accent: "#aa94e8", defaultSymbol: "XBTUSD", marketData: true },
  binance: { icon: BarChart3, accent: "#e6bd6a", defaultSymbol: "BTCUSDT", marketData: true },
};
