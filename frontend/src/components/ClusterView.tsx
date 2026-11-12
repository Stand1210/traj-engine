import { useEffect, useRef, useState } from "react";
import * as echarts from "echarts";
import { api, type Cell } from "../api";

interface Props {
  runId: string;
  onSelect: (path: string) => void;
}

export default function ClusterView({ runId, onSelect }: Props) {
  const [cells, setCells] = useState<Cell[]>([]);
  const [error, setError] = useState<string | null>(null);
  const chartRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void api.cells(runId)
      .then(setCells)
      .catch(error => setError(String(error)));
  }, [runId]);

  useEffect(() => {
    if (!chartRef.current || cells.length === 0) return;
    const chart = echarts.init(chartRef.current);
    chart.setOption({
      color: ["#00B4D8"],
      tooltip: { trigger: "axis" },
      grid: { left: 50, right: 20, top: 30, bottom: 55 },
      xAxis: { type: "category", data: cells.map(cell => cell.cellKey), axisLabel: { rotate: 30 } },
      yAxis: { type: "value", name: "轨迹数" },
      series: [{ type: "bar", data: cells.map(cell => cell.size), barMaxWidth: 52 }]
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [cells]);

  return (
    <section className="panel-grid">
      <div className="panel wide">
        <h2>聚类结果</h2>
        {error && <div className="error-banner">{error}</div>}
        <div ref={chartRef} className="chart" />
        <table>
          <thead><tr><th>Cell</th><th>轨迹数</th><th>结构版本</th><th /></tr></thead>
          <tbody>
            {cells.map(cell => (
              <tr key={cell.id}>
                <td>{cell.cellKey}</td>
                <td>{cell.size}</td>
                <td>-</td>
                <td><button onClick={() => onSelect(`/runs/${runId}/traces`)}>查看轨迹</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
