import { useEffect, useRef, useState } from "react";
import * as echarts from "echarts";
import { api, type Cell, type TraceScore } from "../api";

interface Props {
  runId: string;
  onSelect: (path: string) => void;
}

interface ScatterDatum {
  value: [number, number];
  traceId: string;
  symbol: string;
  symbolSize: number;
  resultScore: number;
  processScore: number;
  latencyScore: number;
  costScore: number;
  robustnessScore: number;
  isAlert: boolean;
  isAbstain: boolean;
  alertStatus: "alerted" | "candidate" | "suppressed_duplicate" | null;
  itemStyle: {
    color?: string;
    borderColor: string;
    borderWidth: number;
  };
}

const SERIES_COLORS = [
  "#00B4D8",
  "#0A2540",
  "#00A870",
  "#7048E8",
  "#E08A00",
  "#D6336C",
  "#1098AD",
  "#5C7CFA",
];

export default function ClusterScatterView({ runId, onSelect }: Props) {
  const chartRef = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    let dispose: () => void = () => undefined;
    void Promise.all([api.cells(runId), api.traces(runId)])
      .then(([cellResult, traceResult]) => {
        if (!active) return;
        dispose = renderChart(cellResult, traceResult.data);
      })
      .catch(loadError => {
        if (active) setError(String(loadError));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      dispose();
    };
  }, [runId]);

  function renderChart(cellRows: Cell[], traceRows: TraceScore[]): () => void {
    if (!chartRef.current) return () => undefined;
    const chart = echarts.init(chartRef.current);
    const cellById = new Map(cellRows.map(cell => [cell.id, cell]));
    const groups = new Map<string, { name: string; data: ScatterDatum[] }>();

    for (const trace of traceRows) {
      const cell = trace.cellId ? cellById.get(trace.cellId) : undefined;
      const groupName = cell?.cellKey ?? "未归类";
      if (!groups.has(groupName)) {
        groups.set(groupName, { name: groupName, data: [] });
      }
      groups.get(groupName)?.data.push({
        value: [trace.totalScore, trace.resultScore],
        traceId: trace.traceId,
        symbol: trace.alertStatus === "alerted"
          ? "triangle"
          : trace.alertStatus === "suppressed_duplicate" || trace.alertStatus === "candidate"
            ? "rect"
            : trace.isAbstain
              ? "diamond"
              : "circle",
        symbolSize: trace.alertStatus === "alerted"
          ? 14
          : trace.alertStatus === "suppressed_duplicate" || trace.alertStatus === "candidate"
            ? 12
            : 10,
        resultScore: trace.resultScore,
        processScore: trace.processScore,
        latencyScore: trace.latencyScore,
        costScore: trace.costScore,
        robustnessScore: trace.robustnessScore,
        isAlert: trace.isAlert,
        isAbstain: trace.isAbstain,
        alertStatus: trace.alertStatus,
        itemStyle: {
          color: trace.isAbstain ? "#9FB3C8" : undefined,
          borderColor: trace.alertStatus === "alerted"
            ? "#C7000B"
            : trace.isAlert
              ? "#E08A00"
              : "#FFFFFF",
          borderWidth: trace.alertStatus === "alerted" ? 2 : 1,
        },
      });
    }

    const orderedGroups = [...groups.values()].sort((left, right) =>
      left.name.localeCompare(right.name)
    );
    const cellCounts = new Map(cellRows.map(cell => [cell.cellKey, cell.size]));

    chart.setOption({
      color: SERIES_COLORS,
      grid: { left: 70, right: 40, top: 24, bottom: 82 },
      legend: {
        bottom: 0,
        type: "scroll",
        padding: [0, 8, 0, 8],
        formatter: (name: string) => `${name} · ${cellCounts.get(name) ?? 0} 条`,
      },
      tooltip: {
        trigger: "item",
        confine: true,
        formatter: (params: unknown) => {
          const datum = (params as { data: ScatterDatum }).data;
          if (!datum) return "";
          return [
            `<strong>${escapeHtml(datum.traceId)}</strong>`,
            `总分：${datum.value[0].toFixed(2)}`,
            `结果：${datum.resultScore.toFixed(2)}`,
            `过程：${datum.processScore.toFixed(2)}`,
            `时延：${datum.latencyScore.toFixed(2)}`,
            `成本：${datum.costScore.toFixed(2)}`,
            `鲁棒：${datum.robustnessScore.toFixed(2)}`,
            datum.alertStatus === "alerted"
              ? "状态：<strong style=\\\"color:#C7000B\\\">正式告警</strong>"
              : datum.alertStatus === "suppressed_duplicate"
                ? "状态：同组去重"
                : datum.alertStatus === "candidate"
                  ? "状态：预算外候选"
                  : "",
            datum.isAbstain ? "状态：弃权" : "",
          ].filter(Boolean).join("<br/>");
        },
      },
      xAxis: {
        type: "value",
        min: 0,
        max: 100,
        splitNumber: 5,
      },
      yAxis: {
        type: "value",
        min: 0,
        max: 1,
        splitNumber: 5,
      },
      series: orderedGroups.map(group => ({
        name: group.name,
        type: "scatter",
        symbolSize: 10,
        data: group.data,
        emphasis: { focus: "series" },
      })),
    });

    chart.on("click", (params: unknown) => {
      const datum = (params as { data?: ScatterDatum }).data;
      if (datum?.traceId) {
        onSelect(`/runs/${runId}/trace/${datum.traceId}`);
      }
    });

    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    const observer = new ResizeObserver(resize);
    observer.observe(chartRef.current);
    return () => {
      window.removeEventListener("resize", resize);
      observer.disconnect();
      chart.dispose();
    };
  }

  function escapeHtml(value: string) {
    return value
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll("\"", "&quot;");
  }

  return (
    <div>
      {loading && <div className="loading-panel">正在加载聚类散点图...</div>}
      {error && <div className="error-banner">{error}</div>}
      <div ref={chartRef} className="scatter-chart" />
      <p className="scatter-note">
        X 轴为总分 S（0~100，越高越好），Y 轴为结果分 O（0~1，越高越好）；颜色区分聚类 Cell，图例显示各 Cell 轨迹数。
        ▲ = 正式告警，■ = 候选/去重，● = 正常，◆ = 弃权；点击任意点可在提示中查看五维分数。
      </p>
    </div>
  );
}
