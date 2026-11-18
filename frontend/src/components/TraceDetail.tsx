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
            <div className="metric-grid">
              <div>
                <span>硬门禁基准分 100G</span>
                <strong>{detail.baseScore.toFixed(4)}</strong>
              </div>
              <div>
                <span>门禁乘数 G</span>
                <strong>{detail.gateMultiplier.toFixed(4)}</strong>
              </div>
              <div>
                <span>LMDI 扣分合计</span>
                <strong>{detail.evidenceSum.toFixed(4)}</strong>
              </div>
              <div>
                <span>对账残差</span>
                <strong>{detail.attributionResidual.toFixed(6)}</strong>
              </div>
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
        {detail && (
          <p className="scheduler-note">
            对账公式：总分 S = 硬门禁基准分 100G + LMDI 维度扣分合计。
            本条轨迹不是从 100 分直接扣分：硬门禁先把基准乘到 {detail.baseScore.toFixed(4)}，
            再由各维度扣 {detail.evidenceSum.toFixed(4)}，得到总分 {detail.totalScore.toFixed(4)}。
            五个维度分是 0~1 的质量项，通过加权几何均值进入总分，不能直接相加或直接乘 100。
          </p>
        )}
        {detail?.evidence.some(item => item.payload?.kernel_evidence) && (
          <details>
            <summary>内核原始证据</summary>
            <p className="scheduler-note">
              内核原始证据是轨迹级证据，下面只展示一份；上方五条维度扣分是 LMDI 归因结果，
              不是五个维度各自持有不同原始证据。
            </p>
            <pre>{JSON.stringify(detail.evidence[0]?.payload?.kernel_evidence, null, 2)}</pre>
          </details>
        )}
      </div>
    </section>
  );
}
