import { ReactNode, useState } from "react";
import { NAV_ITEMS } from "../constants";
import { Menu, X, Check, AlertTriangle } from "lucide-react";

type NavItem = typeof NAV_ITEMS[number];

type SidebarProps = {
  active: string;
  onNavigate: (id: string) => void;
  onSettingsOpen: () => void;
  onSessionsOpen: () => void;
  onMobileNavToggle: () => void;
  mobileNavOpen: boolean;
  health: "checking" | "online" | "offline";
  language: "zh" | "en";
  tr: (zh: string, en: string) => string;
};

function StatusDot({ status }: { status: SidebarProps["health"] }) {
  const dotClass = {
    checking: "status-dot status-dot--checking",
    online: "status-dot status-dot--online",
    offline: "status-dot status-dot--offline",
  }[status];

  return <span className={dotClass} />;
}

function Sidebar({ active, onNavigate, onSettingsOpen, onSessionsOpen, onMobileNavToggle, mobileNavOpen, health, language, tr }: SidebarProps) {
  return (
    <aside className={`side-nav ${mobileNavOpen ? "side-nav--open" : ""}`}>
      {/* Mobile close button */}
      <button className="icon-btn mobile-only" onClick={onMobileNavToggle} style={{ position: "absolute", top: 12, right: 12 }}>
        <X size={18} />
      </button>

      {/* Brand block */}
      <div className="brand-block">
        <div className="brand-mark">
          <span style={{ fontSize: 14, fontWeight: 700 }}>DC</span>
        </div>
        <strong>Deriv Command</strong>
        <span>{tr("AI 交易指挥", "AI Trading Command")}</span>
      </div>

      {/* Navigation items */}
      <nav>
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              className={`nav-item ${active === item.id ? "nav-item--active" : ""}`}
              onClick={() => onNavigate(item.id)}
            >
              <Icon size={18} />
              <span>{tr(item.zh, item.en)}</span>
            </button>
          );
        })}
      </nav>

      {/* Runtime line */}
      <div className="runtime-line">
        <StatusDot status={health} />
        <span>{tr("系统", "System")}: {health === "online" ? tr("在线", "Online") : tr("离线", "Offline")}</span>
      </div>

      {/* Bottom section */}
      <div className="nav-bottom">
        <button className="nav-item" onClick={onSessionsOpen}>
          {/* Session icon */}
          <span>{tr("会话", "Sessions")}</span>
        </button>
        <button className="nav-item" onClick={onSettingsOpen}>
          {/* Settings icon */}
          <span>{tr("设置", "Settings")}</span>
        </button>
      </div>
    </aside>
  );
}

export default Sidebar;
