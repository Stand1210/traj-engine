import { useEffect, useState } from "react";
import {
  api,
  type LifecycleEvaluation,
  type LifecycleInput,
  type Ontology,
  type SchedulerStatus
} from "../api";

interface Props {
  onSelect: (path: string) => void;
}

const emptyConfig: LifecycleInput = {
  enabled: true,
  source: "langfuse",
  sourceRef: "lifecycle",
  intervalHours: 24,
  windowHours: 24,
  samplingRate: 1,
  maxTraces: null,
  r2NoveltyThreshold: 0.15,
  r2AlertRateThreshold: 0.2,
  writebackToLangfuse: false
};

function fromSchedule(schedule: LifecycleInput): LifecycleInput {
  return {
    enabled: schedule.enabled,
    source: schedule.source,
    sourceRef: schedule.sourceRef,
    intervalHours: schedule.intervalHours,
    windowHours: schedule.windowHours,
    samplingRate: schedule.samplingRate,
    maxTraces: schedule.maxTraces,
    r2NoveltyThreshold: schedule.r2NoveltyThreshold,
    r2AlertRateThreshold: schedule.r2AlertRateThreshold,
    writebackToLangfuse: schedule.writebackToLangfuse
  };
}

export default function LifecycleWorkbench({ onSelect }: Props) {
  const [ontologies, setOntologies] = useState<Ontology[]>([]);
  const [ontologyId, setOntologyId] = useState("");
  const [config, setConfig] = useState<LifecycleInput>(emptyConfig);
  const [evaluations, setEvaluations] = useState<LifecycleEvaluation[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [scheduler, setScheduler] = useState<SchedulerStatus | null>(null);

  useEffect(() => {
    void api.ontologies()
      .then(result => {
        setOntologies(result.data);
        if (result.data[0]) setOntologyId(result.data[0].id);
      })
      .catch(loadError => setError(String(loadError)));
  }, []);

  useEffect(() => {
    void api.schedulerStatus()
      .then(setScheduler)
      .catch(loadError => setError(String(loadError)));
  }, []);

  useEffect(() => {
    if (!ontologyId) return;
    setError(null);
    void Promise.all([api.lifecycle(ontologyId), api.lifecycleEvaluations(ontologyId)])
      .then(([schedule, history]) => {
        setConfig(fromSchedule(schedule));
        setEvaluations(history.data);
      })
      .catch(loadError => {
        setConfig(emptyConfig);
        setEvaluations([]);
        setError(String(loadError));
      });
  }, [ontologyId]);

  async function save() {
    if (!ontologyId) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const schedule = await api.saveLifecycle(ontologyId, config);
      setConfig(fromSchedule(schedule));
      setMessage("生命周期调度已保存。");
    } catch (submitError) {
      setError(String(submitError));
    } finally {
      setBusy(false);
    }
  }

  async function evaluate(forceR2: boolean) {
    if (!ontologyId) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await api.evaluateLifecycle(ontologyId, forceR2);
      setMessage(
        result.run
          ? `评估决策 ${result.decision}（${result.reason}），已创建 Run：${result.run.id}。`
          : `评估决策 ${result.decision}（${result.reason}），本轮无需创建 Run。`
      );
      if (result.run) onSelect(`/runs/${result.run.id}`);
      const history = await api.lifecycleEvaluations(ontologyId);
      setEvaluations(history.data);
    } catch (submitError) {
      setError(String(submitError));
    } finally {
      setBusy(false);
    }
  }

  async function evaluateAll() {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await api.evaluateAllLifecycles();
      if (result.status === "skipped") {
        setMessage(`调度扫描跳过：${result.reason ?? "lock_held"}。`);
      } else {
        setMessage(
          `调度扫描${result.status === "succeeded" ? "完成" : "失败"}：` +
          `看门狗处理 ${result.watchdogFailedRuns?.length ?? 0} 条，` +
          `评估 ${result.evaluations?.length ?? 0} 个本体。`
        );
      }
      setScheduler(await api.schedulerStatus());
      if (ontologyId) {
        const history = await api.lifecycleEvaluations(ontologyId);
        setEvaluations(history.data);
      }
    } catch (submitError) {
      setError(String(submitError));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel-grid">
      <div className="panel">
        <h2>生命周期调度</h2>
        {error && <div className="error-banner">{error}</div>}
        {message && <div className="success-banner">{message}</div>}
        <div className="form-grid">
          <label>业务本体
            <select value={ontologyId} onChange={event => setOntologyId(event.target.value)}>
              {ontologies.map(item => (
                <option key={item.id} value={item.id}>{item.id} / {item.tier}</option>
              ))}
            </select>
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={config.enabled}
              onChange={event => setConfig({ ...config, enabled: event.target.checked })}
            />
            启用调度
          </label>
          <label>数据源
            <select
              value={config.source}
              onChange={event => setConfig({ ...config, source: event.target.value as "jsonl" | "langfuse" })}
            >
              <option value="langfuse">Langfuse Project</option>
              <option value="jsonl">基准 JSONL</option>
            </select>
          </label>
          <label>数据源标识<input
            value={config.sourceRef}
            onChange={event => setConfig({ ...config, sourceRef: event.target.value })}
          /></label>
          <label>R1 周期（小时）<input
            type="number" min="1" step="1" value={config.intervalHours}
            onChange={event => setConfig({ ...config, intervalHours: Number(event.target.value) })}
          /></label>
          <label>分析窗口（小时）<input
            type="number" min="1" step="1" value={config.windowHours}
            onChange={event => setConfig({ ...config, windowHours: Number(event.target.value) })}
          /></label>
          <label>采样率<input
            type="number" min="0.01" max="1" step="0.01" value={config.samplingRate}
            onChange={event => setConfig({ ...config, samplingRate: Number(event.target.value) })}
          /></label>
          <label>条数上限<input
            type="number" min="1" step="1" value={config.maxTraces ?? ""}
            placeholder="留空表示全量"
            onChange={event => setConfig({
              ...config,
              maxTraces: event.target.value ? Number(event.target.value) : null
            })}
          /></label>
          <label>R2 novelty 阈值<input
            type="number" min="0" max="1" step="0.01" value={config.r2NoveltyThreshold}
            onChange={event => setConfig({ ...config, r2NoveltyThreshold: Number(event.target.value) })}
          /></label>
          <label>R2 告警率阈值<input
            type="number" min="0" max="1" step="0.01" value={config.r2AlertRateThreshold}
            onChange={event => setConfig({ ...config, r2AlertRateThreshold: Number(event.target.value) })}
          /></label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={config.writebackToLangfuse}
              onChange={event => setConfig({ ...config, writebackToLangfuse: event.target.checked })}
            />
            评分写回 Langfuse Scores
          </label>
        </div>
        <div className="button-row">
          <button disabled={busy} onClick={() => void save()}>保存调度</button>
          <button disabled={busy} onClick={() => void evaluate(false)}>评估并按策略触发</button>
          <button disabled={busy} onClick={() => void evaluate(true)}>强制 R2 重聚类</button>
          <button disabled={busy} onClick={() => void evaluateAll()}>调度扫描全部本体</button>
        </div>
      </div>
      <div className="panel wide">
        <h2>调度器状态</h2>
        {scheduler && (
          <div className="metric-grid scheduler-grid">
            <div><span>启用调度</span><strong>{scheduler.enabledSchedules}</strong></div>
            <div><span>当前锁</span><strong>{scheduler.lock ? "占用" : "空闲"}</strong></div>
            <div><span>最近扫描</span><strong>{scheduler.latestScan?.status ?? "-"}</strong></div>
            <div><span>看门狗处理</span><strong>{scheduler.latestScan?.watchdogFailedRuns ?? 0}</strong></div>
          </div>
        )}
        {scheduler?.latestScan?.error && (
          <div className="error-banner">{scheduler.latestScan.error}</div>
        )}
        <p className="scheduler-note">
          后台调度器由后端启动参数 `--scheduler` 开启；调度器每次先执行看门狗，
          再按策略评估全部启用调度。若另一个实例正在执行扫描，本轮会直接跳过。
        </p>
        <h2>评估历史</h2>
        <table>
          <thead>
            <tr><th>时间</th><th>决策</th><th>触发原因</th><th>窗口内轨迹</th><th>novelty</th><th>告警率</th><th>Run</th></tr>
          </thead>
          <tbody>
            {evaluations.map(item => (
              <tr key={item.id}>
                <td>{item.createdAt.replace("T", " ").slice(0, 19)}</td>
                <td>{item.decision}</td>
                <td>{item.reason}</td>
                <td>{item.metrics.traceCount ?? "-"}</td>
                <td>{item.metrics.noveltyRate == null ? "-" : `${(item.metrics.noveltyRate * 100).toFixed(1)}%`}</td>
                <td>{item.metrics.alertRate == null ? "-" : `${(item.metrics.alertRate * 100).toFixed(1)}%`}</td>
                <td>
                  {item.run ? (
                    <button onClick={() => onSelect(`/runs/${item.run?.id}`)}>查看</button>
                  ) : "-"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
