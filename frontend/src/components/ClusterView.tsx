import { useEffect, useState } from "react";
import { api, type Cell } from "../api";
import ClusterScatterView from "./ClusterScatterView";

interface Props {
  runId: string;
  onSelect: (path: string) => void;
}

export default function ClusterView({ runId, onSelect }: Props) {
  const [cells, setCells] = useState<Cell[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void api.cells(runId)
      .then(setCells)
      .catch(error => setError(String(error)));
  }, [runId]);

  return (
    <section className="panel-grid">
      <div className="panel wide">
        <h2>聚类结果</h2>
        {error && <div className="error-banner">{error}</div>}
        <ClusterScatterView runId={runId} onSelect={onSelect} />
        <table>
          <thead><tr><th>Cell</th><th>轨迹数</th><th>结构版本</th><th /></tr></thead>
          <tbody>
            {cells.map(cell => (
              <tr key={cell.id}>
                <td>{cell.cellKey}</td>
                <td>{cell.size}</td>
                <td>-</td>
                <td>
                  <button onClick={() => onSelect(`/runs/${runId}/traces?cellId=${cell.id}`)}>
                    查看轨迹
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
