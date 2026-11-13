import { useEffect, useState } from "react";
import { api, type Calibration, type Run, type RunStep } from "../api";

interface Props {
  runId: string;
  onSelect: (path: string) => void;
}

export default function RunOverview({ runId, onSelect }: Props) {
  const [run, setRun] = useState<Run | null>(null);
  const [steps, setSteps] = useState<RunStep[]>([]);
  const [calibration, setCalibration] = useState<Calibration | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reviewMessage, setReviewMessage] = useState<string | null>(null);
  const [reviewBusy, setReviewBusy] = useState(false);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const runResult = await api.run(runId);
        const stepResult = await api.runSteps(runId);
        if (!active) return;
        setRun(runResult);
        setSteps(stepResult);
        if (runResult.status === "succeeded") {
          setCalibration(await api.calibration(runId));
        }
      } catch (loadError) {
        if (active) setError(String(loadError));
      }
    }
    void load();
    const timer = window.setInterval(() => void load(), 5000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [runId]);

  async function pushReviewQueue(scope: "alerts" | "abstains" | "all") {
    setReviewBusy(true);
    setError(null);
    setReviewMessage(null);
    try {
      const result = await api.createReviewQueue(runId, { scope, limit: 50 });
      setReviewMessage(`已推送 ${result.pushed ?? 0} 条轨迹到 Langfuse 复核队列。`);
    } catch (submitError) {
      setError(String(submitError));
    } finally {
      setReviewBusy(false);
    }
  }

  async function syncReviewQueue() {
    setReviewBusy(true);
    setError(null);
    setReviewMessage(null);
    try {
      const result = await api.syncReviewQueue(runId);
      setReviewMessage(
        `同步完成：导入 ${result.imported ?? 0} 条人工复核，${result.awaitingReview ?? 0} 条待复核。`
      );
    } catch (submitError) {
      setError(String(submitError));
    } finally {
      setReviewBusy(false);
    }
  }

  return (
    <section className="panel-grid">
      <div className="panel wide">
        <h2>Run 概览</h2>
        {error && <div className="error-banner">{error}</div>}
        {run && (
          <div className="metric-grid">
            <div><span>状态</span><strong>{run.status}</strong></div>
            <div><span>数据集</span><strong>{run.sourceRef ?? "-"}</strong></div>
            <div><span>结构版本</span><strong>{run.structureVersion ?? "-"}</strong></div>
            <div><span>Kernel Hash</span><strong>{run.codeHash}</strong></div>
            <div><span>开始</span><strong>{run.startedAt?.replace("T", " ").slice(0, 19) ?? "-"}</strong></div>
            <div><span>结束</span><strong>{run.endedAt?.replace("T", " ").slice(0, 19) ?? "-"}</strong></div>
          </div>
        )}
        {run?.error && <div className="error-banner">{run.error}</div>}
        {reviewMessage && <div className="success-banner">{reviewMessage}</div>}
        <div className="button-row">
          <button onClick={() => onSelect(`/runs/${runId}/cells`)}>查看聚类</button>
          <button onClick={() => onSelect(`/runs/${runId}/lineage`)}>查看演化</button>
          <button onClick={() => onSelect(`/runs/${runId}/traces`)}>查看轨迹</button>
          <button onClick={() => onSelect(`/runs/${runId}/alerts`)}>查看告警</button>
          <button onClick={() => onSelect(`/runs/${runId}/calibration`)}>查看校准</button>
          {run?.source === "langfuse" && run.status === "succeeded" && (
            <>
              <button disabled={reviewBusy} onClick={() => void pushReviewQueue("all")}>
                推送告警/弃权到复核队列
              </button>
              <button disabled={reviewBusy} onClick={() => void syncReviewQueue()}>
                同步 Langfuse 人工复核
              </button>
            </>
          )}
        </div>
      </div>
      <div className="panel">
        <h2>执行步骤</h2>
        <table>
          <thead><tr><th>步骤</th><th>状态</th><th>开始</th><th>结束</th></tr></thead>
          <tbody>
            {steps.map(step => (
              <tr key={step.id}>
                <td>{step.name}</td>
                <td><span className={`status ${step.status}`}>{step.status}</span></td>
                <td>{step.startedAt.replace("T", " ").slice(0, 19)}</td>
                <td>{step.endedAt?.replace("T", " ").slice(0, 19) ?? "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="panel">
        <h2>校准</h2>
        {calibration ? (
          <div className="metric-grid">
            <div><span>方法</span><strong>{calibration.kind}</strong></div>
            <div><span>标签数</span><strong>{calibration.labelCount ?? "-"}</strong></div>
            <div><span>ECE</span><strong>{calibration.ece?.toFixed(4) ?? "-"}</strong></div>
          </div>
        ) : <p>Run 成功后显示校准信息。</p>}
      </div>
    </section>
  );
}
