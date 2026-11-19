import { useEffect, useState } from "react";
import {
  api,
  type LifecycleEvaluation,
  type LifecycleInput,
  type LifecycleSchedule,
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
  r2MinNoveltyTraces: 50,
  r2TrainingLimit: 0,
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
    r2MinNoveltyTraces: schedule.r2MinNoveltyTraces,
    r2TrainingLimit: schedule.r2TrainingLimit,
    r2AlertRateThreshold: schedule.r2AlertRateThreshold,
    writebackToLangfuse: schedule.writebackToLangfuse
  };
}

export default function LifecycleWorkbench({ onSelect }: Props) {
  const [ontologies, setOntologies] = useState<Ontology[]>([]);
  const [ontologyId, setOntologyId] = useState("");
  const [schedule, setSchedule] = useState<LifecycleSchedule | null>(null);
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
        setSchedule(schedule);
        setConfig(fromSchedule(schedule));
        setEvaluations(history.data);
      })
      .catch(loadError => {
        setSchedule(null);
        setConfig(emptyConfig);
        setEvaluations([]);
        if (String(loadError).includes("lifecycle_not_configured")) {
          setError(null);
          setMessage("当前本体尚未配置生命周期调度，可填写后保存。");
        } else {
          setError(String(loadError));
        }
      });
  }, [ontologyId]);

  async function save() {
    if (!ontologyId) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const schedule = await api.saveLifecycle(ontologyId, config);
      setSchedule(schedule);
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
        <div className={`lifecycle-summary ${schedule ? "registered" : "unregistered"}`}>
          <div>
            <span>注册状态</span>
            <strong>{schedule ? "已注册" : "未注册"}</strong>
          </div>
          <div>
            <span>调度 ID</span>
            <strong>{schedule?.id ?? "-"}</strong>
          </div>
          <div>
            <span>调度状态</span>
            <strong>{schedule ? (schedule.enabled ? "启用" : "停用") : "-"}</strong>
          </div>
          <div>
            <span>R1 周期</span>
            <strong>{schedule ? `${schedule.intervalHours} 小时` : "-"}</strong>
          </div>
          <div>
            <span>R2 训练上限</span>
            <strong>
              {schedule
                ? (schedule.r2TrainingLimit === 0 ? "自动（1 小时预算）" : `${schedule.r2TrainingLimit} 条`)
                : "-"}
            </strong>
          </div>
          <div>
            <span>分析窗口</span>
            <strong>{schedule ? `${schedule.windowHours} 小时` : "-"}</strong>
          </div>
          <div>
            <span>最近更新</span>
            <strong>{formatLocalDateTime(schedule?.updatedAt)}</strong>
          </div>
        </div>
        <p className="scheduler-note">
          {schedule
            ? "该业务本体已有生命周期配置，保存将更新原配置，不会重复注册。"
            : "该业务本体尚未注册生命周期配置，保存后创建一条调度记录。"}
        </p>
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
          <label>R2 最小 novelty 轨迹数<input
            type="number" min="0" step="1" value={config.r2MinNoveltyTraces}
            onChange={event => setConfig({ ...config, r2MinNoveltyTraces: Number(event.target.value) })}
          /></label>
          <label>R2 告警率阈值<input
            type="number" min="0" max="1" step="0.01" value={config.r2AlertRateThreshold}
            onChange={event => setConfig({ ...config, r2AlertRateThreshold: Number(event.target.value) })}
          /></label>
          <label>R2 训练策略
            <select
              value={config.r2TrainingLimit === 0 ? "auto" : "manual"}
              onChange={event => setConfig({
                ...config,
                r2TrainingLimit: event.target.value === "auto" ? 0 : 300
              })}
            >
              <option value="auto">自动：1 小时内全量，超时按预算采样</option>
              <option value="manual">手动：指定训练上限</option>
            </select>
          </label>
          {config.r2TrainingLimit !== 0 && (
            <label>R2 训练上限（条）<input
              type="number" min="2" step="1" value={config.r2TrainingLimit}
              placeholder="例如 300"
              onChange={event => setConfig({
                ...config,
                r2TrainingLimit: Number(event.target.value)
              })}
            /></label>
          )}
          <p className="scheduler-note">
            自动策略在加载时间窗轨迹后决策：预计 R2 不超过 1 小时使用全量结构学习；
            超过 1 小时则按预算推荐训练样本数。窗口内全部轨迹始终参与检测与评分。
          </p>
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
          <button disabled={busy} onClick={() => void save()}>{schedule ? "更新调度" : "注册调度"}</button>
          <button disabled={busy} onClick={() => void evaluate(false)}>评估并按策略触发</button>
          <button disabled={busy} onClick={() => void evaluate(true)}>强制 R2 重聚类</button>
          <button disabled={busy} onClick={() => void evaluateAll()}>调度扫描全部本体</button>
        </div>
      </div>
      <div className="panel wide">
        <h2>调度器状态</h2>
        {scheduler && (
          <div className="metric-grid scheduler-grid">
            <div><span>调度线程</span><strong>{formatThreadState(scheduler.threadAlive)}</strong></div>
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
        <p className="scheduler-note">
          展示最近 48 小时的评估记录；连续未到期扫描会合并为一行，完整记录仍在数据库审计中保留。
        </p>
        <table>
          <thead>
            <tr><th>时间</th><th>决策</th><th>触发原因</th><th>窗口内轨迹</th><th>novelty</th><th>累计 novelty</th><th>告警率</th><th>Run</th></tr>
          </thead>
          <tbody>
            {evaluations.map(item => (
              <tr key={item.id}>
                <td>
                  {formatLocalDateTime(item.lastSeenAt ?? item.createdAt)}
                  {item.repeatCount && item.repeatCount > 1 && item.firstSeenAt && (
                    <span className="table-subtext">
                      {`（${formatLocalDateTime(item.firstSeenAt)} 起）`}
                    </span>
                  )}
                </td>
                <td>{formatDecision(item)}</td>
                <td>{item.reason}</td>
                <td>{item.metrics.traceCount ?? "-"}</td>
                <td>{item.metrics.noveltyRate == null ? "-" : `${(item.metrics.noveltyRate * 100).toFixed(1)}%`}</td>
                <td>
                  {item.metrics.accumulatedNoveltyTraces == null
                    ? "-"
                    : `${item.metrics.accumulatedNoveltyTraces} / ${item.metrics.r2MinNoveltyTraces ?? "-"}`}
                </td>
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

function formatThreadState(alive: boolean | null | undefined) {
  if (alive === null || alive === undefined) return "未知";
  return alive ? "运行中" : "已停止";
}

function formatDecision(item: LifecycleEvaluation) {
  const repeatCount = item.repeatCount ?? 1;
  return repeatCount > 1 ? `${item.decision} ×${repeatCount}` : item.decision;
}
import { formatLocalDateTime } from "../time";

