import { useEffect, useState } from "react";
import { api, type LineageEdge, type Run } from "../api";

interface Props {
  runId: string;
  onSelect: (path: string) => void;
}

const relationLabels: Record<LineageEdge["relation"], string> = {
  continued: "延续",
  split: "拆分",
  merged: "合并",
  born: "新生",
  died: "消亡"
};

export default function LineageView({ runId, onSelect }: Props) {
  const [run, setRun] = useState<Run | null>(null);
  const [edges, setEdges] = useState<LineageEdge[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void Promise.all([api.run(runId), api.lineage(runId)])
      .then(([runResult, edgeResult]) => {
        if (!active) return;
        setRun(runResult);
        setEdges(edgeResult);
      })
      .catch(loadError => {
        if (active) setError(String(loadError));
      });
    return () => {
      active = false;
    };
  }, [runId]);

  const counts = edges.reduce<Record<string, number>>((result, edge) => {
    result[edge.relation] = (result[edge.relation] ?? 0) + 1;
    return result;
  }, {});

  return (
    <section className="panel-grid">
      <div className="panel">
        <h2>结构演化</h2>
        {error && <div className="error-banner">{error}</div>}
        {run && (
          <div className="metric-grid">
            <div><span>Run 类型</span><strong>{run.runType}</strong></div>
            <div><span>结构版本</span><strong>{run.structureVersion ?? "-"}</strong></div>
            <div><span>关系数</span><strong>{edges.length}</strong></div>
          </div>
        )}
        <div className="lineage-summary">
          {Object.entries(relationLabels).map(([relation, label]) => (
            <span key={relation} className={`relation-pill ${relation}`}>
              {label} {counts[relation] ?? 0}
            </span>
          ))}
        </div>
        <p className="lineage-note">
          R2 会创建新的结构版本，不会改写历史 Run 分数。此表按相同 trace 在新旧 cell
          中的重叠情况解释结构演化：overlap 越接近 1，表示旧 cell 越完整地进入目标 cell。
        </p>
      </div>
      <div className="panel wide">
        <h2>Cell Lineage</h2>
        {edges.length === 0 && !error && <p>当前 Run 没有 lineage。R1 复用结构，只有 R2 会生成。</p>}
        {edges.length > 0 && (
          <table>
            <thead>
              <tr><th>旧 Cell</th><th>关系</th><th>新 Cell</th><th>Overlap</th><th>规模变化</th><th /></tr>
            </thead>
            <tbody>
              {edges.map(edge => (
                <tr key={edge.id}>
                  <td>{edge.oldCellKey ?? edge.oldCellId}</td>
                  <td><span className={`relation-pill ${edge.relation}`}>{relationLabels[edge.relation]}</span></td>
                  <td>{edge.newCellKey ?? edge.newCellId}</td>
                  <td>{(edge.overlap * 100).toFixed(1)}%</td>
                  <td>{edge.oldCellSize ?? "-"} → {edge.newCellSize ?? "-"}</td>
                  <td><button onClick={() => onSelect(`/runs/${runId}/cells`)}>查看新结构</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}

