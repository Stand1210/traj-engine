import { useEffect, useMemo, useState } from "react";
import {
  api,
  type LangfuseConnectionCheck,
  type OnboardingResult,
  type Ontology,
  type ProfileInfo,
  type Tenant,
} from "../api";

interface Props {
  onRegistered: () => void;
  onSelect: (path: string) => void;
}

interface FormState {
  displayName: string;
  orgId: string;
  projectId: string;
  publicKey: string;
  secretKey: string;
  ontologyDisplayName: string;
  maxTracesPerRun: string;
}

const EMPTY_FORM: FormState = {
  displayName: "",
  orgId: "",
  projectId: "",
  publicKey: "",
  secretKey: "",
  ontologyDisplayName: "",
  maxTracesPerRun: "",
};

export default function ProjectOnboarding({ onRegistered, onSelect }: Props) {
  const [profile, setProfile] = useState<ProfileInfo | null>(null);
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [ontologies, setOntologies] = useState<Ontology[]>([]);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [checking, setChecking] = useState(false);
  const [registering, setRegistering] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checkResult, setCheckResult] = useState<LangfuseConnectionCheck | null>(null);
  const [registered, setRegistered] = useState<OnboardingResult | null>(null);

  function loadProjects() {
    void Promise.all([api.profile(), api.tenants(), api.ontologies()])
      .then(([profileResult, tenantPage, ontologyPage]) => {
        setProfile(profileResult);
        setTenants(tenantPage.data);
        setOntologies(ontologyPage.data);
      })
      .catch(loadError => setError(String(loadError)));
  }

  useEffect(loadProjects, []);

  const ontologyByTenant = useMemo(() => {
    const map = new Map<string, Ontology>();
    ontologies.forEach(item => map.set(item.tenantId, item));
    return map;
  }, [ontologies]);
  const canCheck = Boolean(form.projectId && form.publicKey && form.secretKey) && !checking && !registering;
  const canRegister = canCheck && Boolean(form.displayName && form.orgId && form.ontologyDisplayName) && !registered;

  function updateField(field: keyof FormState, value: string) {
    setForm(current => ({ ...current, [field]: value }));
    setCheckResult(null);
    setRegistered(null);
  }

  async function checkConnection() {
    setChecking(true);
    setError(null);
    setRegistered(null);
    try {
      const result = await api.checkLangfuseConnection({
        projectId: form.projectId,
        publicKey: form.publicKey,
        secretKey: form.secretKey,
      });
      setCheckResult(result);
    } catch (checkError) {
      setCheckResult(null);
      setError(String(checkError));
    } finally {
      setChecking(false);
    }
  }

  async function registerProject() {
    setRegistering(true);
    setError(null);
    try {
      const result = await api.registerProject({
        displayName: form.displayName,
        orgId: form.orgId,
        projectId: form.projectId,
        publicKey: form.publicKey,
        secretKey: form.secretKey,
        ontologyDisplayName: form.ontologyDisplayName,
        maxTracesPerRun: form.maxTracesPerRun ? Number(form.maxTracesPerRun) : undefined,
      });
      setRegistered(result);
      setForm(current => ({ ...current, publicKey: "", secretKey: "" }));
      setCheckResult(null);
      loadProjects();
      onRegistered();
    } catch (registerError) {
      setError(String(registerError));
    } finally {
      setRegistering(false);
    }
  }

  return (
    <section className="panel-grid">
      <div className="panel">
        <h2>新业务接入</h2>
        <div className="step-list">
          <div className="step-item">1. 在 Langfuse 创建独立 Project，并获取该 Project 的 API Keys。</div>
          <div className="step-item">2. 校验 Key 与 Project 的对应关系。</div>
          <div className="step-item">3. 注册租户，并自动创建 Tier 0 本体。</div>
          <div className="step-item">4. 在生命周期页启用 R2 冷启动训练，后续进入 R1 周期刷新。</div>
        </div>
        <div className="form-grid">
          <label>Profile<span>{profile ? `${profile.profile} · ${profile.baseUrl}` : "..."}</span></label>
          <label>业务显示名
            <input value={form.displayName} onChange={event => updateField("displayName", event.target.value)} />
          </label>
          <label>Langfuse Org ID
            <input value={form.orgId} onChange={event => updateField("orgId", event.target.value)} />
          </label>
          <label>Langfuse Project ID
            <input value={form.projectId} onChange={event => updateField("projectId", event.target.value)} />
          </label>
          <label>Public Key
            <input value={form.publicKey} onChange={event => updateField("publicKey", event.target.value)} />
          </label>
          <label>Secret Key
            <input type="password" value={form.secretKey} onChange={event => updateField("secretKey", event.target.value)} />
          </label>
          <label>本体显示名
            <input
              value={form.ontologyDisplayName}
              placeholder="例如：网元告警研判 Agent"
              onChange={event => updateField("ontologyDisplayName", event.target.value)}
            />
          </label>
          <label>单 Run 最大轨迹数
            <input
              value={form.maxTracesPerRun}
              placeholder="留空使用平台默认值"
              onChange={event => updateField("maxTracesPerRun", event.target.value)}
            />
          </label>
        </div>
        <div className="button-row">
          <button disabled={!canCheck} onClick={() => void checkConnection()}>
            {checking ? "校验中..." : "校验连接"}
          </button>
          <button className="primary" disabled={!canRegister} onClick={() => void registerProject()}>
            {registering ? "注册中..." : "注册业务 Project"}
          </button>
        </div>
        {checkResult && (
          <div className="success-banner">
            连接成功：Langfuse {checkResult.langfuseVersion ?? "-"} · Project {checkResult.project.name ?? checkResult.project.id}
          </div>
        )}
        {registered && (
          <div className="success-banner">
            接入完成：{registered.tenant.displayName} · {registered.ontology.id}
            <div className="onboarding-next">
              下一步请进入生命周期页，为该本体启用 R2 冷启动训练。
              <button onClick={() => onSelect("/lifecycle")}>配置生命周期</button>
            </div>
          </div>
        )}
        {error && <div className="error-banner">{error}</div>}
      </div>
      <div className="panel wide">
        <h2>已接入业务</h2>
        <table>
          <thead>
            <tr><th>业务</th><th>Org / Project</th><th>本体</th><th>单 Run 上限</th><th /></tr>
          </thead>
          <tbody>
            {tenants.map(tenant => {
              const ontology = ontologyByTenant.get(tenant.id);
              return (
                <tr key={tenant.id}>
                  <td>{tenant.displayName}</td>
                  <td>{tenant.orgId} / {tenant.projectId}</td>
                  <td>{ontology ? `${ontology.id} · Tier ${ontology.tier.replace("tier", "")}` : "未创建"}</td>
                  <td>{tenant.maxTracesPerRun.toLocaleString()}</td>
                  <td>
                    {ontology && (
                      <button onClick={() => onSelect(`/ontologies/${ontology.id}/versions`)}>本体版本</button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
