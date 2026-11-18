import { useEffect, useMemo, useState } from "react";
import { api, type Ontology, type Run, type Tenant } from "../api";
import { formatLocalDateTime } from "../time";

interface Props {
  onCreated: () => void;
  runsVersion: number;
  onSelect: (path: string) => void;
}

export default function RunLauncher({ onCreated, runsVersion, onSelect }: Props) {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [ontologies, setOntologies] = useState<Ontology[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [sourceRef, setSourceRef] = useState("R1");
  const [limit, setLimit] = useState("");
  const [source, setSource] = useState<"jsonl" | "langfuse">("jsonl");
  const [runType, setRunType] = useState<"R1" | "R2" | "R3">("R1");
  const [writeback, setWriteback] = useState(false);
  const [tenantId, setTenantId] = useState("");
  const [ontologyId, setOntologyId] = useState("");

  useEffect(() => {
    void Promise.all([api.tenants(), api.ontologies()])
      .then(([tenantPage, ontologyPage]) => {
        setTenants(tenantPage.data);
        setOntologies(ontologyPage.data);
      })
      .catch(error => setError(String(error)));
  }, []);

  useEffect(() => {
    void api.runs()
      .then(result => setRuns(result.data))
      .catch(error => setError(String(error)));
  }, [runsVersion]);

  useEffect(() => {
    if (!tenants.length) return;
    if (!tenants.some(item => item.id === tenantId)) {
      const benchmark = tenants.find(item => item.id === "tenant-benchmark");
      setTenantId((benchmark ?? tenants[0]).id);
    }
  }, [tenants, tenantId]);

  useEffect(() => {
    if (!ontologies.length) return;
    if (!ontologies.some(item => item.id === ontologyId)) {
      setOntologyId(ontologies[0].id);
    }
  }, [ontologies, ontologyId]);

  const tenant = tenants.find(item => item.id === tenantId);
  const tenantOntologies = ontologies.filter(item => item.tenantId === tenant?.id);
  const ontology = ontologies.find(item => item.id === ontologyId)
    ?? tenantOntologies[0]
    ?? ontologies[0];
  const canSubmit = Boolean(tenant && ontology) && !submitting;
  const defaultWindow = useMemo(() => {
    const toLocalInputValue = (date: Date) => {
      const offset = date.getTimezoneOffset() * 60000;
      return new Date(date.getTime() - offset)
        .toISOString()
        .slice(0, 16);
    };
    const end = new Date();
    end.setSeconds(0, 0);
    const start = new Date(end.getTime() - 24 * 3600 * 1000);
    return { start: toLocalInputValue(start), end: toLocalInputValue(end) };
  }, []);
  const [windowStart, setWindowStart] = useState(defaultWindow.start);
  const [windowEnd, setWindowEnd] = useState(defaultWindow.end);

  async function createRun() {
    if (!tenant || !ontology) return;
    setSubmitting(true);
    setError(null);
    try {
      const run = await api.createRun({
        tenantId: tenant.id,
        ontologyId: ontology.id,
        source,
        sourceRef,
        runType,
        windowStart: new Date(windowStart).toISOString(),
        windowEnd: new Date(windowEnd).toISOString(),
        samplingRate: 1,
        limit: limit ? Number(limit) : undefined,
        triggerReason: source === "langfuse" ? `${runType} frontend launch` : "M1 frontend launch",
        writebackToLangfuse: source === "langfuse" && writeback
      });
      onCreated();
      onSelect(`/runs/${run.id}`);
    } catch (submitError) {
      setError(String(submitError));
    } finally {
      setSubmitting(false);
    }
  }

  function selectSource(value: "jsonl" | "langfuse") {
    setSource(value);
    if (value === "jsonl") {
      setSourceRef("R1");
      setRunType("R1");
      const benchmark = tenants.find(item => item.id === "tenant-benchmark");
      if (benchmark) {
        setTenantId(benchmark.id);
        const benchmarkOntology = ontologies.find(item => item.tenantId === benchmark.id);
        setOntologyId(benchmarkOntology?.id ?? "");
      }
      return;
    }
    const productionTenant = tenants.find(item => item.id !== "tenant-benchmark");
    if (productionTenant) {
      setTenantId(productionTenant.id);
      const productionOntology = ontologies.find(item => item.tenantId === productionTenant.id);
      setOntologyId(productionOntology?.id ?? "");
    }
    setSourceRef(`frontend-${new Date().toISOString().slice(0, 10)}`);
    setRunType("R2");
  }

  return (
    <section className="panel-grid">
      <div className="panel">
        <h2>发起分析 Run</h2>
        <div className="form-grid">
          <label>业务租户
            <select
              value={tenant?.id ?? ""}
              onChange={event => {
                setTenantId(event.target.value);
                const nextOntology = ontologies.find(item => item.tenantId === event.target.value);
                setOntologyId(nextOntology?.id ?? "");
              }}
            >
              {tenants.map(item => <option key={item.id} value={item.id}>{item.displayName}</option>)}
            </select>
          </label>
          <label>Project 限额
            <span>
              {tenant
                ? `单 Run 最大轨迹数 ${tenant.maxTracesPerRun.toLocaleString()}`
                : "..."}
            </span>
          </label>
          <label>本体
            <select value={ontology?.id ?? ""} onChange={event => setOntologyId(event.target.value)}>
              {tenantOntologies.map(item => (
                <option key={item.id} value={item.id}>{item.id} / {item.tier}</option>
              ))}
            </select>
          </label>
          <button onClick={() => ontology && onSelect(`/ontologies/${ontology.id}/versions`)}>
            本体版本管理
          </button>
          <label>数据源
            <select value={source} onChange={event => selectSource(event.target.value as "jsonl" | "langfuse")}>
              <option value="jsonl">基准 JSONL（算法回归）</option>
              <option value="langfuse">Langfuse Project（生产数据）</option>
            </select>
          </label>
          <label>Run 类型
            <select value={runType} onChange={event => setRunType(event.target.value as "R1" | "R2" | "R3")}>
              <option value="R2">R2 · 冷启动 / 重新聚类</option>
              <option value="R1">R1 · 固定结构周期刷新</option>
              <option value="R3">R3 · 本体升版评估</option>
            </select>
          </label>
          <label>
            {source === "jsonl" ? "基准数据集（R1~R8）" : "Run 标识（仅用于报告与追踪）"}
            <input
              value={sourceRef}
              readOnly={source === "jsonl"}
              placeholder={source === "jsonl" ? "R1" : "例如：daily-baseline-20261117"}
              onChange={event => setSourceRef(event.target.value)}
            />
          </label>
          <label>条数上限
            <input
              value={limit}
              placeholder={tenant ? `不超过 ${tenant.maxTracesPerRun.toLocaleString()}` : "留空表示按租户限额"}
              onChange={event => setLimit(event.target.value)}
            />
          </label>
          {source === "langfuse" && (
            <label className="checkbox">
              <input
                type="checkbox"
                checked={writeback}
                onChange={event => setWriteback(event.target.checked)}
              />
              评分写回 Langfuse Scores
            </label>
          )}
          <label>时间窗开始
            <input
              type="datetime-local"
              step={60}
              value={windowStart}
              onChange={event => setWindowStart(event.target.value)}
            />
          </label>
          <label>时间窗结束
            <input
              type="datetime-local"
              step={60}
              value={windowEnd}
              onChange={event => setWindowEnd(event.target.value)}
            />
          </label>
        </div>
        <button className="primary" disabled={!canSubmit} onClick={() => void createRun()}>
          {submitting ? "提交中..." : `发起 ${runType} Run`}
        </button>
      </div>
      <div className="panel wide">
        <h2>Run 列表</h2>
        {error && <div className="error-banner">{error}</div>}
        <table>
          <thead><tr><th>Run</th><th>类型</th><th>状态</th><th>Run 标识 / 数据集</th><th>分数身份</th><th>创建时间</th><th /></tr></thead>
          <tbody>
            {runs.map(run => (
              <tr key={run.id}>
                <td>{run.id}</td>
                <td><span className={`status ${run.status}`}>{run.runType}</span></td>
                <td><span className={`status ${run.status}`}>{run.status}</span></td>
                <td>{run.sourceRef ?? "-"}</td>
                <td>{run.codeHash}</td>
                <td>{formatLocalDateTime(run.createdAt)}</td>
                <td><button onClick={() => onSelect(`/runs/${run.id}`)}>查看</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
