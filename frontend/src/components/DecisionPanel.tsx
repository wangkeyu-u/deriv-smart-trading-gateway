import { useState } from "react";
import { Inbox, Check, X, AlertTriangle } from "lucide-react";

type DecisionItem = {
  case: { id: string; title: string; symbol: string; status: string };
  decision: Record<string, any>;
  state: "ready" | "blocked" | "evidence_requested" | "approved" | "rejected";
  evidence_score: number;
  blockers: string[];
  global_risk: Record<string, any>;
};

type DecisionPanelProps = {
  decisions: DecisionItem[];
  onApprove: (caseId: string) => void;
  onReject: (caseId: string) => void;
  onRequestEvidence: (caseId: string) => void;
  language: "zh" | "en";
  tr: (zh: string, en: string) => string;
};

function DecisionPanel({ decisions, onApprove, onReject, onRequestEvidence, tr }: DecisionPanelProps) {
  if (decisions.length === 0) {
    return (
      <div className="decision-panel decision-panel--empty">
        <Inbox size={32} />
        <p>{tr("暂无待审批决策", "No pending decisions")}</p>
      </div>
    );
  }

  return (
    <div className="decision-panel">
      <h3 className="panel-title">
        {tr("决策审批", "Decision Inbox")}
        <span className="badge">{decisions.length}</span>
      </h3>

      {decisions.map((item) => (
        <div key={item.case.id} className={`decision-card decision-card--${item.state}`}>
          <div className="decision-header">
            <strong>{item.case.title}</strong>
            <span className="decision-symbol">{item.case.symbol}</span>
          </div>

          <div className="decision-meta">
            <span>{tr("置信度", "Confidence")}: {(item.evidence_score * 100).toFixed(0)}%</span>
            {item.blockers.length > 0 && (
              <span className="blockers">
                <AlertTriangle size={14} />
                {item.blockers.length} {tr("个阻碍", "blockers")}
              </span>
            )}
          </div>

          <div className="decision-actions">
            <button
              className="btn-approve"
              onClick={() => onApprove(item.case.id)}
              title={tr("批准", "Approve")}
            >
              <Check size={16} />
            </button>
            <button
              className="btn-reject"
              onClick={() => onReject(item.case.id)}
              title={tr("拒绝", "Reject")}
            >
              <X size={16} />
            </button>
            <button
              className="btn-evidence"
              onClick={() => onRequestEvidence(item.case.id)}
              title={tr("补充证据", "Request Evidence")}
            >
              {tr("补充", "Evidence")}
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

export default DecisionPanel;
