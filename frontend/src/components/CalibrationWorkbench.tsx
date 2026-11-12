import { useCallback, useEffect, useState } from "react";
import { api, type Page, type ReviewCalibration } from "../api";

interface Props {
  runId: string;
}

interface ReviewRow {
  id: string;
  traceScoreId: string;
  reviewer: string;
  verdict: string;
  label: string | null;
  comment: string | null;
}

export default function CalibrationWorkbench({ runId }: Props) {
  const [versions, setVersions] = useState<Page<ReviewCalibration> | null>(null);
  const [reviews, setReviews] = useState<Page<ReviewRow> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [versionResult, reviewResult] = await Promise.all([
      api.reviewCalibrations(runId),
      api.reviews(runId),
    ]);
    setVersions(versionResult);
    setReviews(reviewResult);
  }, [runId]);

  useEffect(() => {
    let active = true;
    void load()
      .then(() => undefined)
      .catch(loadError => {
        if (active) setError(String(loadError));
      });
    return () => {
      active = false;
    };
  }, [load]);

  async function triggerCalibration() {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const calibration = await api.triggerCalibration(runId, "frontend-user");
      setMessage(`校准版本已创建：${calibration.id}，可审核后激活。`);
      await load();
    } catch (submitError) {
      setError(String(submitError));
    } finally {
      setBusy(false);
    }
  }

  async function activateVersion(id: string) {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await api.activateCalibration(id);
      setMessage(`校准版本已激活：${id}。后续告警排序将应用根因严重度修正。`);
      await load();
    } catch (submitError) {
      setError(String(submitError));
    } finally {
      setBusy(false);
    }
  }

  const reviewCount = reviews?.data.length ?? 0;
  const reviewedTraces = new Set(reviews?.data.map(item => item.traceScoreId) ?? []).size;

  return (
    <section className="panel-grid">
      <div className="panel">
        <h2>人工复核回流</h2>
        {error && <div className="error-banner">{error}</div>}
        {message && <div className="success-banner">{message}</div>}
        <div className="metric-grid">
          <div><span>复核记录</span><strong>{reviewCount}</strong></div>
          <div><span>复核轨迹</span><strong>{reviewedTraces}</strong></div>
          <div><span>校准版本</span><strong>{versions?.data.length ?? 0}</strong></div>
          <div><span>激活版本</span><strong>{versions?.data.filter(item => item.activatedAt).length ?? 0}</strong></div>
        </div>
        <div className="button-row">
          <button className="primary" disabled={busy} onClick={() => void triggerCalibration()}>
            触发校准
          </button>
        </div>
        <p className="calibration-note">
          默认门槛：20 条复核标签、10 条已复核正式告警。不足时不会生成校准版本，避免小样本误校准。
        </p>
      </div>
      <div className="panel wide">
        <h2>校准版本</h2>
        <table>
          <thead>
            <tr>
              <th>版本</th><th>标签</th><th>正式告警</th><th>精确率</th>
              <th>ECE</th><th>Brier</th><th>创建人</th><th>状态</th><th />
            </tr>
          </thead>
          <tbody>
            {(versions?.data ?? []).map(item => (
              <tr key={item.id} className={item.activatedAt ? "alert-row" : undefined}>
                <td>{item.id}</td>
                <td>{item.labelCount}</td>
                <td>{item.alertReviewed}</td>
                <td>{item.alertPrecision?.toFixed(4) ?? "-"}</td>
                <td>{item.ece?.toFixed(4) ?? "-"}</td>
                <td>{item.brier?.toFixed(4) ?? "-"}</td>
                <td>{item.createdBy}</td>
                <td>{item.activatedAt ? "已激活" : "未激活"}</td>
                <td>
                  <button disabled={busy || Boolean(item.activatedAt)} onClick={() => void activateVersion(item.id)}>
                    激活
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <details>
          <summary>复核记录</summary>
          <table>
            <thead><tr><th>轨迹分数</th><th>复核人</th><th>结论</th><th>标签</th></tr></thead>
            <tbody>
              {(reviews?.data ?? []).map(item => (
                <tr key={item.id}>
                  <td>{item.traceScoreId}</td>
                  <td>{item.reviewer}</td>
                  <td>{item.verdict}</td>
                  <td>{item.label ?? "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      </div>
    </section>
  );
}
