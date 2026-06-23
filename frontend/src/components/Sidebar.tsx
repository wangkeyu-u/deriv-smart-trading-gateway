import { ReactNode } from "react";
import { Waypoints, X, Settings2, Languages, ChevronRight } from "lucide-react";
import { NAV_ITEMS } from "../constants";

type SidebarProps = {
  active: string;
  mobileNav: boolean;
  health: "checking" | "online" | "offline";
  language: "zh" | "en";
  onNavigate: (id: string) => void;
  onCloseMobile: () => void;
  onSettingsOpen: () => void;
  onLanguageToggle: () => void;
  tr: (zh: string, en: string) => string;
};

function Sidebar({
  active,
  mobileNav,
  health,
  language,
  onNavigate,
  onCloseMobile,
  onSettingsOpen,
  onLanguageToggle,
  tr,
}: SidebarProps) {
  return (
    <aside className={`side-nav ${mobileNav ? "side-nav--open" : ""}`}>
      <div className="brand-block">
        <div className="brand-mark">
          <Waypoints size={20} />
        </div>
        <div>
          <strong>MARKET GATEWAY</strong>
          <span>Multi-Broker Agent Operations</span>
        </div>
        <button
          className="icon-btn mobile-only"
          onClick={onCloseMobile}
          aria-label={tr("关闭导航", "Close navigation")}
        >
          <X size={18} />
        </button>
      </div>

      <nav>
        <p className="nav-caption">WORKSPACE</p>
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              className={`nav-item ${active === item.id ? "nav-item--active" : ""}`}
              aria-current={active === item.id ? "page" : undefined}
              onClick={() => onNavigate(item.id)}
            >
              <Icon size={18} />
              <span>{item[language]}</span>
              {active === item.id && <ChevronRight size={16} />}
            </button>
          );
        })}
      </nav>

      <div className="nav-bottom">
        <button className="nav-item" onClick={onSettingsOpen}>
          <Settings2 size={18} />
          <span>{tr("模型与密钥", "Models & API Keys")}</span>
        </button>
        <button
          className="nav-item language-switch"
          onClick={onLanguageToggle}
          aria-label={tr("切换到英文", "Switch to Chinese")}
        >
          <Languages size={18} />
          <span>{language === "zh" ? "English" : "ZH"}</span>
        </button>
        <div className="runtime-line">
          <span className={`status-dot status-dot--${health}`} /> FastAPI ·{" "}
          {health === "online" ? "ONLINE" : "OFFLINE"}
        </div>
      </div>
    </aside>
  );
}

export default Sidebar;
