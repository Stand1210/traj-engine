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
import LineageView from "./components/LineageView";
import OntologyVersions from "./components/OntologyVersions";
import ProjectOnboarding from "./components/ProjectOnboarding";

type Route =
  | { name: "runs" }
  | { name: "onboarding" }
  | { name: "lifecycle" }
  | { name: "ontologyVersions"; ontologyId: string }
  | { name: "run"; runId: string }
  | { name: "cells"; runId: string }
  | { name: "lineage"; runId: string }
  | { name: "traces"; runId: string; mode: "all" | "alerts" | "abstain"; cellId: string | null }
  | { name: "alerts"; runId: string }
  | { name: "calibration"; runId: string }
  | { name: "trace"; runId: string; traceId: string };

function parseHash(): Route {
  const [hashPath, hashQuery = ""] = window.location.hash.replace(/^#\/?/, "").split("?");
  const parts = hashPath.split("/").filter(Boolean);
  const query = new URLSearchParams(hashQuery);
  if (parts[0] === "lifecycle") {
    return { name: "lifecycle" };
  }
  if (parts[0] === "onboarding") {
    return { name: "onboarding" };
  }
  if (parts[0] === "ontologies" && parts[1] && parts[2] === "versions") {
    return { name: "ontologyVersions", ontologyId: parts[1] };
  }
  if (parts[0] === "runs" && parts[1] && parts[2] === "cells") {
    return { name: "cells", runId: parts[1] };
  }
  if (parts[0] === "runs" && parts[1] && parts[2] === "lineage") {
    return { name: "lineage", runId: parts[1] };
  }
  if (parts[0] === "runs" && parts[1] && parts[2] === "traces") {
    const mode = parts[3] === "alerts" || parts[3] === "abstain" ? parts[3] : "all";
    return { name: "traces", runId: parts[1], mode, cellId: query.get("cellId") };
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
    () => (
      route.name === "runs" || route.name === "onboarding" || route.name === "lifecycle"
      || route.name === "ontologyVersions"
        ? null
        : route.runId
    ),
    [route]
  );

  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <div className="brand">轨迹质量评估平台</div>
      <div className="subtitle">生产接入 · 聚类 / 异常 / 打分 / 证据</div>
        </div>
        <div className="profile-box">
          <span>Profile：{profile?.profile ?? "..."}</span>
          <span title={startup?.note ?? undefined}>
            Langfuse：{startup?.langfuseVersion ?? "版本未获取"}
          </span>
          <span>Kernel：2064664e6aa5fb46</span>
        </div>
      </header>
      <div className="nav-shell">
        <nav className="app-nav" aria-label="主导航">
          <button className={route.name === "runs" ? "active" : ""} onClick={() => navigate("/")}>运行工作台</button>
          <button className={route.name === "onboarding" ? "active" : ""} onClick={() => navigate("/onboarding")}>业务接入</button>
          <button className={route.name === "lifecycle" ? "active" : ""} onClick={() => navigate("/lifecycle")}>生命周期</button>
        </nav>
        {activeRunId && (
          <nav className="run-nav" aria-label="Run 导航">
            <span className="run-nav-label">当前 Run</span>
            <button className={route.name === "run" ? "active" : ""} onClick={() => navigate(`/runs/${activeRunId}`)}>概览</button>
            <button className={route.name === "cells" ? "active" : ""} onClick={() => navigate(`/runs/${activeRunId}/cells`)}>聚类</button>
            <button className={route.name === "lineage" ? "active" : ""} onClick={() => navigate(`/runs/${activeRunId}/lineage`)}>演化</button>
            <button className={route.name === "traces" || route.name === "trace" ? "active" : ""} onClick={() => navigate(`/runs/${activeRunId}/traces`)}>轨迹</button>
            <button className={route.name === "alerts" ? "active" : ""} onClick={() => navigate(`/runs/${activeRunId}/alerts`)}>告警</button>
            <button className={route.name === "calibration" ? "active" : ""} onClick={() => navigate(`/runs/${activeRunId}/calibration`)}>校准</button>
          </nav>
        )}
      </div>
      <main>
        {error && <div className="error-banner">{error}</div>}
        {route.name === "runs" && (
          <RunLauncher onCreated={refreshRuns} runsVersion={runsVersion} onSelect={navigate} />
        )}
        {route.name === "onboarding" && (
          <ProjectOnboarding onRegistered={refreshRuns} onSelect={navigate} />
        )}
        {route.name === "lifecycle" && <LifecycleWorkbench onSelect={navigate} />}
        {route.name === "ontologyVersions" && (
          <OntologyVersions ontologyId={route.ontologyId} onBack={() => navigate("/")} />
        )}
        {route.name === "run" && <RunOverview runId={route.runId} />}
        {route.name === "cells" && <ClusterView runId={route.runId} onSelect={navigate} />}
        {route.name === "lineage" && <LineageView runId={route.runId} onSelect={navigate} />}
        {route.name === "traces" && (
          <TraceWorkbench
            key={`${route.runId}:${route.cellId ?? "all"}:${route.mode}`}
            runId={route.runId}
            initialMode={route.mode}
            initialCellId={route.cellId}
            onSelect={navigate}
          />
        )}
        {route.name === "alerts" && <AlertWorkbench runId={route.runId} onSelect={navigate} />}
        {route.name === "calibration" && <CalibrationWorkbench runId={route.runId} />}
        {route.name === "trace" && <TraceDetail runId={route.runId} traceId={route.traceId} />}
      </main>
    </div>
  );
}
