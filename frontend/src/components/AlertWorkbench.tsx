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

interface AlertCache {
  summary: AlertSummary;
  alerts: AlertTraceScore[];
  candidates: AlertTraceScore[];
}

const alertCache = new Map<string, AlertCache>();

function readAlertCache(runId: string): AlertCache | undefined {
  return alertCache.get(runId);
}

export default function AlertWorkbench({ runId, onSelect }: Props) {
  const [summary, setSummary] = useState<AlertSummary | null>(() => readAlertCache(runId)?.summary ?? null);
  const [alerts, setAlerts] = useState<AlertTraceScore[]>(() => readAlertCache(runId)?.alerts ?? []);
  const [candidates, setCandidates] = useState<AlertTraceScore[]>(() => readAlertCache(runId)?.candidates ?? []);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(() => !readAlertCache(runId));
  const [refreshing, setRefreshing] = useState(false);
  const [mode, setMode] = useState<"alerts" | "candidates">("alerts");

  useEffect(() => {
    let active = true;
    setRefreshing(true);
    void Promise.all([api.alertSummary(runId), api.alerts(runId), api.alertCandidates(runId)])
      .then(([summaryResult, alertResult, candidateResult]) => {
        if (!active) return;
        alertCache.set(runId, {
          summary: summaryResult,
          alerts: alertResult,
          candidates: candidateResult
        });
        setSummary(summaryResult);
        setAlerts(alertResult);
        setCandidates(candidateResult);
      })
      .catch(loadError => setError(String(loadError)))
      .finally(() => {
        if (active) {
          setLoading(false);
          setRefreshing(false);
        }
      });
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
                <strong>{formatCause(group.cause)}</strong>
                <span>组大小 {group.groupSize} · 优先级 {group.topPriority.toFixed(2)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="panel wide">
        <h2>告警工作台</h2>
        {loading && <div className="loading-panel">正在加载告警决策...</div>}
        {!loading && refreshing && <div className="loading-panel muted">正在后台刷新告警决策...</div>}
        <div className="tabs">
          <button className={mode === "alerts" ? "active" : ""} onClick={() => setMode("alerts")}>
            正式告警 {alerts.length}
          </button>
          <button className={mode === "candidates" ? "active" : ""} onClick={() => setMode("candidates")}>
            候选异常 {candidates.length}
          </button>
        </div>
        {!loading && (
        <table>
          <thead>
            <tr>
              <th>状态</th><th>优先级</th><th>Trace</th><th>总分</th>
              <th>根因</th><th>组内排序</th><th>原因</th><th />
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
                <td>{formatCause(row.cause)}</td>
                <td
                  title={`同聚类 Cell + 同根因聚合为组；仅组内第 1 条进入正式告警，其余去重。当前组大小：${row.groupSize}`}
                >
                  组内 {row.groupRank} / {row.groupSize}
                </td>
                <td title={row.reasons.map(formatReason).join(" · ")}>
                  {row.reasons.slice(0, 2).map(formatReason).join(" · ")}
                </td>
                <td><button onClick={() => onSelect(`/runs/${runId}/trace/${row.traceId}`)}>下钻</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        )}
      </div>
    </section>
  );
}

function formatCause(cause: string) {
  const labels: Record<string, string> = {
    "rule:result_broken": "结果破坏",
    "rule:forbidden_action": "禁用动作",
    "rule:unrecovered_error": "错误未恢复",
    "rule:truncated_generation": "生成被截断",
    "rule:unfinished": "未完成",
    "rule:missing_step": "步骤缺失",
    "rule:missing_declared_step": "声明步骤缺失",
    "rule:untraceable_answer_number": "数字不可追溯",
    "rule:untraceable_answer_fact": "事实不可追溯",
    "rule:runaway_loop": "循环失控",
    "alert:unspecified": "未指定根因",
  };
  if (labels[cause]) return `${cause}（${labels[cause]}）`;
  if (cause.startsWith("metric:")) {
    const metric = cause.slice("metric:".length);
    return `${cause}（${metricLabel(metric)}偏离）`;
  }
  return cause;
}

function metricLabel(metric: string) {
  const labels: Record<string, string> = {
    retry_count: "重试次数",
    loop_count: "循环次数",
    latency_ms: "时延",
    tok: "Token 用量",
    total_tokens: "总 Token",
    input_tokens: "输入 Token",
    output_tokens: "输出 Token",
    cost: "成本",
  };
  if (metric.includes(":")) {
    const [action, name] = metric.split(":");
    return `${action} 的${labels[name] ?? name}`;
  }
  return labels[metric] ?? metric;
}

function formatReason(reason: string) {
  if (reason.startsWith("total_score=")) return `${reason}（总分）`;
  if (reason.startsWith("worst_dimension=")) {
    const dimension = reason.split(":", 1)[0].slice("worst_dimension=".length);
    return `${reason}（最弱维度：${dimensionLabel(dimension)}）`;
  }
  if (reason.startsWith("deduction=")) return `${reason}（LMDI 扣分）`;
  if (reason.startsWith("primary_cause=")) return formatCause(reason.slice("primary_cause=".length));
  if (reason.startsWith("priority=")) return `${reason}（优先级）`;
  return reason;
}

function dimensionLabel(dimension: string) {
  const labels: Record<string, string> = {
    result: "结果符合度",
    process: "过程合规",
    latency: "时延",
    cost: "成本",
    robustness: "鲁棒性",
  };
  return labels[dimension] ?? dimension;
}
