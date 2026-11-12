import { useEffect, useState } from "react";
import { api, type TraceScoreDetail } from "../api";

interface Props {
  runId: string;
  traceId: string;
}

const dimensions = [
  { key: "resultScore", label: "结果符合度" },
  { key: "processScore", label: "过程合规" },
  { key: "latencyScore", label: "时延" },
  { key: "costScore", label: "成本" },
  { key: "robustnessScore", label: "鲁棒性" }
] as const;

export default function TraceDetail({ runId, traceId }: Props) {
  const [detail, setDetail] = useState<TraceScoreDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void api.trace(runId, traceId)
      .then(setDetail)
      .catch(error => setError(String(error)));
  }, [runId, traceId]);

  return (
    <section className="panel-grid">
      <div className="panel">
        <h2>轨迹 {traceId}</h2>
        {error && <div className="error-banner">{error}</div>}
        {detail && (
          <>
            <div className="score-head">
              <span>总分</span><strong>{detail.totalScore.toFixed(2)}</strong>
              <span className={`status ${detail.isAlert ? "failed" : "succeeded"}`}>
                {detail.isAlert ? "告警" : detail.isAbstain ? "弃权" : "正常"}
              </span>
            </div>
            <div className="dimension-list">
              {dimensions.map(item => (
                <div key={item.key} className="dimension">
                  <span>{item.label}</span>
                  <div><i style={{ width: `${Math.max(0, Math.min(1, detail[item.key])) * 100}%` }} /></div>
                  <strong>{detail[item.key].toFixed(2)}</strong>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
      <div className="panel wide">
        <h2>扣分证据</h2>
        <table>
          <thead><tr><th>维度</th><th>扣分</th><th>说明</th><th>Span</th></tr></thead>
          <tbody>
            {detail?.evidence.map(item => (
              <tr key={item.id}>
                <td>{item.dimension}</td>
                <td className="score">{item.contribution.toFixed(4)}</td>
                <td>{item.explanation}</td>
                <td>{item.spanId ?? "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {detail?.evidence.some(item => item.payload?.kernel_evidence) && (
          <details>
            <summary>内核原始证据</summary>
            <pre>{JSON.stringify(detail.evidence.map(item => item.payload?.kernel_evidence), null, 2)}</pre>
          </details>
        )}
      </div>
    </section>
  );
}
