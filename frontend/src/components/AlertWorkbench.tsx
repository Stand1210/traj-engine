import { useEffect, useState } from "react";
import { api, type AlertSummary, type AlertTraceScore } from "../api";

interface Props {
  runId: string;
  onSelect: (path: string) => void;
}

const statusLabels: Record<string, string> = {
  alerted: "正式告警",
  candidate: "预算外候选",
  suppressed_duplicate: "同组去重"
};

export default function AlertWorkbench({ runId, onSelect }: Props) {
  const [summary, setSummary] = useState<AlertSummary | null>(null);
  const [alerts, setAlerts] = useState<AlertTraceScore[]>([]);
  const [candidates, setCandidates] = useState<AlertTraceScore[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"alerts" | "candidates">("alerts");

  useEffect(() => {
    let active = true;
    void Promise.all([api.alertSummary(runId), api.alerts(runId), api.alertCandidates(runId)])
      .then(([summaryResult, alertResult, candidateResult]) => {
        if (!active) return;
        setSummary(summaryResult);
        setAlerts(alertResult);
        setCandidates(candidateResult);
      })
      .catch(loadError => setError(String(loadError)));
    return () => {
      active = false;
    };
  }, [runId]);

  const rows = mode === "alerts" ? alerts : candidates;

  return (
    <section className="panel-grid">
      <div className="panel">
        <h2>告警预算</h2>
        {error && <div className="error-banner">{error}</div>}
        {summary && (
          <div className="metric-grid">
            <div><span>预算</span><strong>{summary.budget}</strong></div>
            <div><span>正式告警</span><strong>{summary.emitted}</strong></div>
            <div><span>原始告警</span><strong>{summary.totalAlerts}</strong></div>
            <div><span>告警组</span><strong>{summary.groups}</strong></div>
            <div><span>预算外</span><strong>{summary.statusCounts.candidate ?? 0}</strong></div>
            <div><span>同组去重</span><strong>{summary.statusCounts.suppressed_duplicate ?? 0}</strong></div>
          </div>
        )}
        {summary && (
          <div className="group-list">
            {summary.topGroups.map(group => (
              <div key={group.groupKey} className="alert-group">
                <strong>{group.cause}</strong>
                <span>组大小 {group.groupSize} · 优先级 {group.topPriority.toFixed(2)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="panel wide">
        <h2>告警工作台</h2>
        <div className="tabs">
          <button className={mode === "alerts" ? "active" : ""} onClick={() => setMode("alerts")}>
            正式告警 {alerts.length}
          </button>
          <button className={mode === "candidates" ? "active" : ""} onClick={() => setMode("candidates")}>
            候选异常 {candidates.length}
          </button>
        </div>
        <table>
          <thead>
            <tr>
              <th>状态</th><th>优先级</th><th>Trace</th><th>总分</th>
              <th>根因</th><th>组</th><th>原因</th><th />
            </tr>
          </thead>
          <tbody>
            {rows.map(row => (
              <tr key={row.id} className={row.alertStatus === "alerted" ? "alert-row" : undefined}>
                <td><span className={`status ${row.alertStatus === "alerted" ? "failed" : "queued"}`}>
                  {statusLabels[row.alertStatus] ?? row.alertStatus}
                </span></td>
                <td className="score">{row.priority.toFixed(2)}</td>
                <td>{row.traceId}</td>
                <td>{row.totalScore.toFixed(2)}</td>
                <td>{row.cause}</td>
                <td>#{row.groupRank}/{row.groupSize}</td>
                <td title={row.reasons.join(" · ")}>{row.reasons.slice(0, 2).join(" · ")}</td>
                <td><button onClick={() => onSelect(`/runs/${runId}/trace/${row.traceId}`)}>下钻</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
