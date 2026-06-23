import { useState, useEffect } from "react";
import { BarChart3, RefreshCw } from "lucide-react";

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

type MarketPanelProps = {
  market: MarketData | null;
  brokerId: string;
  symbol: string;
  onRefresh: () => void;
  loading: boolean;
  language: "zh" | "en";
  tr: (zh: string, en: string) => string;
};

function MarketPanel({ market, brokerId, symbol, onRefresh, loading, tr }: MarketPanelProps) {
  if (!market || !market.ok) {
    return (
      <div className="market-panel market-panel--empty">
        <BarChart3 size={32} />
        <p>{tr("暂无行情数据", "No market data")}</p>
        <button className="btn-refresh" onClick={onRefresh} disabled={loading}>
          <RefreshCw size={14} className={loading ? "spinning" : ""} />
          {tr("刷新", "Refresh")}
        </button>
      </div>
    );
  }

  const changePct = market.window_change_pct;
  const isUp = changePct != null && changePct >= 0;

  return (
    <div className="market-panel">
      <div className="market-header">
        <h3 className="market-symbol">{symbol}</h3>
        <button className="btn-refresh" onClick={onRefresh} disabled={loading}>
          <RefreshCw size={14} className={loading ? "spinning" : ""} />
        </button>
      </div>

      <div className="market-tick">
        <span className="market-quote">{market.tick?.quote?.toFixed(4) ?? "--"}</span>
        {changePct != null && (
          <span className={`market-change ${isUp ? "market-change--up" : "market-change--down"}`}>
            {isUp ? "+" : ""}{changePct.toFixed(2)}%
          </span>
        )}
      </div>

      <div className="market-meta">
        <span>{tr("K线数", "Candles")}: {market.candle_count}</span>
        {market.latest_close != null && (
          <span>{tr("最新收盘", "Last Close")}: {market.latest_close.toFixed(4)}</span>
        )}
      </div>

      {market.closes && market.closes.length > 0 && (
        <div className="market-mini-chart">
          {/* Simple sparkline using divs */}
          <div className="sparkline">
            {market.closes.slice(-30).map((price, i) => {
              const min = Math.min(...market.closes!.slice(-30));
              const max = Math.max(...market.closes!.slice(-30));
              const height = max > min ? ((price - min) / (max - min)) * 100 : 50;
              return (
                <div
                  key={i}
                  className="sparkline-bar"
                  style={{ height: `${height}%` }}
                />
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

export default MarketPanel;
