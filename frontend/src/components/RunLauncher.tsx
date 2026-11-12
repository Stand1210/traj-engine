import { useEffect, useMemo, useState } from "react";
import { api, type Ontology, type Run, type Tenant } from "../api";

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
  const [writeback, setWriteback] = useState(false);

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

  const tenant = tenants[0];
  const ontology = ontologies.find(item => item.tenantId === tenant?.id) ?? ontologies[0];
  const canSubmit = Boolean(tenant && ontology) && !submitting;
  const defaultWindow = useMemo(() => {
    const end = new Date();
    const start = new Date(end.getTime() - 7 * 24 * 3600 * 1000);
    return { start: start.toISOString(), end: end.toISOString() };
  }, []);

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
        runType: "R1",
        windowStart: defaultWindow.start,
        windowEnd: defaultWindow.end,
        samplingRate: 1,
        limit: limit ? Number(limit) : undefined,
        triggerReason: source === "langfuse" ? "M3 frontend launch" : "M1 frontend launch",
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

  return (
    <section className="panel-grid">
      <div className="panel">
        <h2>发起分析 Run</h2>
        <div className="form-grid">
          <label>租户<span>{tenant?.displayName ?? "..."}</span></label>
          <label>本体<span>{ontology?.id ?? "..."} / {ontology?.tier ?? "..."}</span></label>
          <label>数据源
            <select value={source} onChange={event => setSource(event.target.value as "jsonl" | "langfuse")}>
              <option value="jsonl">基准 JSONL</option>
              <option value="langfuse">Langfuse Project</option>
            </select>
          </label>
          <label>数据集 / Run 标识<input value={sourceRef} onChange={event => setSourceRef(event.target.value)} /></label>
          <label>条数上限<input value={limit} placeholder="留空表示全量" onChange={event => setLimit(event.target.value)} /></label>
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
          <label>时间窗<span>{defaultWindow.start.slice(0, 19)} ~ {defaultWindow.end.slice(0, 19)}</span></label>
        </div>
        <button className="primary" disabled={!canSubmit} onClick={() => void createRun()}>
          {submitting ? "提交中..." : "发起 R1 Run"}
        </button>
      </div>
      <div className="panel wide">
        <h2>Run 列表</h2>
        {error && <div className="error-banner">{error}</div>}
        <table>
          <thead><tr><th>Run</th><th>状态</th><th>数据集</th><th>分数身份</th><th>创建时间</th><th /></tr></thead>
          <tbody>
            {runs.map(run => (
              <tr key={run.id}>
                <td>{run.id}</td>
                <td><span className={`status ${run.status}`}>{run.status}</span></td>
                <td>{run.sourceRef ?? "-"}</td>
                <td>{run.codeHash}</td>
                <td>{run.createdAt.replace("T", " ").slice(0, 19)}</td>
                <td><button onClick={() => onSelect(`/runs/${run.id}`)}>查看</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
