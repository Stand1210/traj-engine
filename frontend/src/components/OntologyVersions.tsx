import { useEffect, useState } from "react";
import { api, type Ontology, type OntologyVersion } from "../api";

interface Props {
  ontologyId: string;
  onBack: () => void;
}

export default function OntologyVersions({ ontologyId, onBack }: Props) {
  const [ontology, setOntology] = useState<Ontology | null>(null);
  const [versions, setVersions] = useState<OntologyVersion[]>([]);
  const [draft, setDraft] = useState("");
  const [activate, setActivate] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void Promise.all([api.ontology(ontologyId), api.ontologyVersions(ontologyId)])
      .then(([ontologyResult, versionPage]) => {
        setOntology(ontologyResult);
        setVersions(versionPage.data);
      })
      .catch(loadError => setError(String(loadError)));
  }, [ontologyId]);

  async function refresh() {
    const [ontologyResult, versionPage] = await Promise.all([
      api.ontology(ontologyId),
      api.ontologyVersions(ontologyId),
    ]);
    setOntology(ontologyResult);
    setVersions(versionPage.data);
  }

  async function copyCurrent() {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const current = await api.currentOntologyVersion(ontologyId);
      const nextVersion = current.version + 1;
      const nextYaml = current.yaml.replace(/^version:\s*\d+\s*$/m, `version: ${nextVersion}`);
      setDraft(nextYaml);
      setMessage(`已复制当前版本，并把版本号改为 ${nextVersion}。请修改业务字段后发布。`);
    } catch (copyError) {
      setError(String(copyError));
    } finally {
      setBusy(false);
    }
  }

  async function publish() {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const published = await api.publishOntologyVersion(ontologyId, draft, activate);
      await refresh();
      setMessage(`已发布版本 ${published.version}${activate ? " 并设为当前版本" : ""}。`);
      setDraft("");
    } catch (publishError) {
      setError(String(publishError));
    } finally {
      setBusy(false);
    }
  }

  async function activateVersion(version: number) {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await api.activateOntologyVersion(ontologyId, version);
      await refresh();
      setMessage(`版本 ${version} 已设为当前版本。`);
    } catch (activateError) {
      setError(String(activateError));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel-grid">
      <div className="panel">
        <h2>本体版本</h2>
        <p>{ontology ? `${ontology.id} · ${ontology.tier} · 当前 v${ontology.currentVersion}` : "..."}</p>
        <div className="button-row">
          <button disabled={busy} onClick={onBack}>返回 Run 列表</button>
          <button disabled={busy} onClick={() => void copyCurrent()}>复制当前版本</button>
        </div>
        <div className="form-grid">
          <label>新版本 YAML
            <textarea value={draft} rows={16} onChange={event => setDraft(event.target.value)} />
          </label>
          <label className="checkbox">
            <input type="checkbox" checked={activate} onChange={event => setActivate(event.target.checked)} />
            发布后立即设为当前版本
          </label>
        </div>
        <button className="primary" disabled={busy || !draft.trim()} onClick={() => void publish()}>
          {busy ? "处理中..." : "发布不可变版本"}
        </button>
        {error && <div className="error-banner">{error}</div>}
        {message && <div className="success-banner">{message}</div>}
      </div>
      <div className="panel wide">
        <h2>版本历史</h2>
        <table>
          <thead>
            <tr><th>版本</th><th>状态</th><th>创建时间</th><th>代码哈希</th><th /></tr>
          </thead>
          <tbody>
            {versions.map(item => (
              <tr key={item.version} className={item.version === ontology?.currentVersion ? "alert-row" : ""}>
                <td>v{item.version}</td>
                <td>{item.version === ontology?.currentVersion ? "当前生效" : "历史版本"}</td>
                <td>{item.createdAt.replace("T", " ").slice(0, 19)}</td>
                <td>{item.codeHash}</td>
                <td>
                  {item.version !== ontology?.currentVersion && (
                    <button disabled={busy} onClick={() => void activateVersion(item.version)}>设为当前</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="scheduler-note">
          发布只新增不可变版本；激活只更新 current_version。历史 Run 继续引用其创建时的版本，不会被改写。
        </p>
      </div>
    </section>
  );
}
