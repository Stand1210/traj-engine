import { useEffect, useState } from "react";
import { api, type TraceScore } from "../api";

interface Props {
  runId: string;
  initialMode: "all" | "alerts" | "abstain";
  initialCellId: string | null;
  onSelect: (path: string) => void;
}

export default function TraceWorkbench({ runId, initialMode, initialCellId, onSelect }: Props) {
  const [mode, setMode] = useState(initialMode);
  const [cellId] = useState(initialCellId);
  const [rows, setRows] = useState<TraceScore[]>([]);
  const [cellKey, setCellKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    const filters = [
      mode === "alerts" ? "&alertOnly=true" : "",
      mode === "abstain" ? "&abstainOnly=true" : "",
      cellId ? `&cellId=${encodeURIComponent(cellId)}` : ""
    ].join("");
    const promise = api.traces(runId, filters);
    void promise
      .then(result => setRows(result.data))
      .catch(error => setError(String(error)));
  }, [runId, mode, cellId]);

  useEffect(() => {
    if (!cellId) {
      setCellKey(null);
      return;
    }
    void api.cells(runId)
      .then(cells => setCellKey(cells.find(cell => cell.id === cellId)?.cellKey ?? null))
      .catch(() => setCellKey(null));
  }, [runId, cellId]);

  return (
    <section className="panel wide">
      <h2>轨迹工作台{cellId ? ` · Cell ${cellKey ?? "…"}` : ""}</h2>
      <div className="tabs">
        <button className={mode === "alerts" ? "active" : ""} onClick={() => setMode("alerts")}>告警</button>
        <button className={mode === "all" ? "active" : ""} onClick={() => setMode("all")}>全部</button>
        <button className={mode === "abstain" ? "active" : ""} onClick={() => setMode("abstain")}>弃权</button>
      </div>
      {error && <div className="error-banner">{error}</div>}
      <table>
        <thead>
          <tr><th>Trace</th><th>总分</th><th>结果</th><th>过程</th><th>时延</th><th>成本</th><th>鲁棒</th><th>标签</th><th /></tr>
        </thead>
        <tbody>
          {rows.map(row => (
            <tr key={row.id} className={row.isAlert ? "alert-row" : undefined}>
              <td>{row.traceId}</td>
              <td className="score">{row.totalScore.toFixed(2)}</td>
              <td>{row.resultScore.toFixed(2)}</td>
              <td>{row.processScore.toFixed(2)}</td>
              <td>{row.latencyScore.toFixed(2)}</td>
              <td>{row.costScore.toFixed(2)}</td>
              <td>{row.robustnessScore.toFixed(2)}</td>
              <td>{row.isAlert ? "告警" : row.isAbstain ? "弃权" : "正常"}</td>
              <td><button onClick={() => onSelect(`/runs/${runId}/trace/${row.traceId}`)}>下钻</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
