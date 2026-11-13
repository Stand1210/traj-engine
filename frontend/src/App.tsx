import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type ProfileInfo, type StartupRecord } from "./api";
import RunLauncher from "./components/RunLauncher";
import RunOverview from "./components/RunOverview";
import ClusterView from "./components/ClusterView";
import TraceWorkbench from "./components/TraceWorkbench";
import TraceDetail from "./components/TraceDetail";
import AlertWorkbench from "./components/AlertWorkbench";
import CalibrationWorkbench from "./components/CalibrationWorkbench";
import LifecycleWorkbench from "./components/LifecycleWorkbench";

type Route =
  | { name: "runs" }
  | { name: "lifecycle" }
  | { name: "run"; runId: string }
  | { name: "cells"; runId: string }
  | { name: "traces"; runId: string; mode: "all" | "alerts" | "abstain" }
  | { name: "alerts"; runId: string }
  | { name: "calibration"; runId: string }
  | { name: "trace"; runId: string; traceId: string };

function parseHash(): Route {
  const parts = window.location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  if (parts[0] === "lifecycle") {
    return { name: "lifecycle" };
  }
  if (parts[0] === "runs" && parts[1] && parts[2] === "cells") {
    return { name: "cells", runId: parts[1] };
  }
  if (parts[0] === "runs" && parts[1] && parts[2] === "traces") {
    const mode = parts[3] === "alerts" || parts[3] === "abstain" ? parts[3] : "all";
    return { name: "traces", runId: parts[1], mode };
  }
  if (parts[0] === "runs" && parts[1] && parts[2] === "alerts") {
    return { name: "alerts", runId: parts[1] };
  }
  if (parts[0] === "runs" && parts[1] && parts[2] === "calibration") {
    return { name: "calibration", runId: parts[1] };
  }
  if (parts[0] === "runs" && parts[1] && parts[2] === "trace" && parts[3]) {
    return { name: "trace", runId: parts[1], traceId: parts[3] };
  }
  if (parts[0] === "runs" && parts[1]) {
    return { name: "run", runId: parts[1] };
  }
  return { name: "runs" };
}

export default function App() {
  const [route, setRoute] = useState<Route>(() => parseHash());
  const [profile, setProfile] = useState<ProfileInfo | null>(null);
  const [startup, setStartup] = useState<StartupRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [runsVersion, setRunsVersion] = useState(0);

  useEffect(() => {
    const handler = () => setRoute(parseHash());
    window.addEventListener("hashchange", handler);
    return () => window.removeEventListener("hashchange", handler);
  }, []);

  useEffect(() => {
    void Promise.all([api.profile(), api.startup()])
      .then(([profileResult, startupResult]) => {
        setProfile(profileResult);
        setStartup(startupResult);
      })
      .catch(error => setError(String(error)));
  }, []);

  const navigate = useCallback((path: string) => {
    window.location.hash = path;
    setRoute(parseHash());
  }, []);

  const refreshRuns = useCallback(() => setRunsVersion(value => value + 1), []);
  const activeRunId = useMemo(
    () => (route.name === "runs" || route.name === "lifecycle" ? null : route.runId),
    [route]
  );

  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <div className="brand">轨迹质量评估平台</div>
          <div className="subtitle">M1 基准闭环 · 聚类 / 异常 / 打分 / 证据</div>
        </div>
        <div className="profile-box">
          <span>Profile：{profile?.profile ?? "..."}</span>
          <span>Langfuse：{startup?.langfuseVersion ?? "未核对"}</span>
          <span>Kernel：2064664e6aa5fb46</span>
        </div>
      </header>
      <nav className="app-nav">
        <button className={route.name === "runs" ? "active" : ""} onClick={() => navigate("/")}>Run 列表</button>
        <button className={route.name === "lifecycle" ? "active" : ""} onClick={() => navigate("/lifecycle")}>生命周期</button>
        {activeRunId && (
          <>
            <button onClick={() => navigate(`/runs/${activeRunId}`)}>Run 概览</button>
            <button onClick={() => navigate(`/runs/${activeRunId}/cells`)}>聚类结果</button>
            <button onClick={() => navigate(`/runs/${activeRunId}/traces`)}>轨迹工作台</button>
            <button onClick={() => navigate(`/runs/${activeRunId}/alerts`)}>告警工作台</button>
            <button onClick={() => navigate(`/runs/${activeRunId}/calibration`)}>校准工作台</button>
          </>
        )}
      </nav>
      <main>
        {error && <div className="error-banner">{error}</div>}
        {route.name === "runs" && (
          <RunLauncher onCreated={refreshRuns} runsVersion={runsVersion} onSelect={navigate} />
        )}
        {route.name === "lifecycle" && <LifecycleWorkbench onSelect={navigate} />}
        {route.name === "run" && <RunOverview runId={route.runId} onSelect={navigate} />}
        {route.name === "cells" && <ClusterView runId={route.runId} onSelect={navigate} />}
        {route.name === "traces" && <TraceWorkbench runId={route.runId} initialMode={route.mode} onSelect={navigate} />}
        {route.name === "alerts" && <AlertWorkbench runId={route.runId} onSelect={navigate} />}
        {route.name === "calibration" && <CalibrationWorkbench runId={route.runId} />}
        {route.name === "trace" && <TraceDetail runId={route.runId} traceId={route.traceId} />}
      </main>
    </div>
  );
}
