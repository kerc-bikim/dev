import { FormEvent, useEffect, useState } from "react";
import { apiGet, apiPost, type Project } from "../api";

export function ProjectHome({ onOpen }: { onOpen: (project: Project) => void }) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [name, setName] = useState("YZ 상시망");
  const [network, setNetwork] = useState("YZ");
  const [operator, setOperator] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    apiGet<{ projects: Project[] }>("/api/projects")
      .then((data) => setProjects(data.projects))
      .catch((err: Error) => setError(err.message));
  }, []);

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const project = await apiPost<Project>("/api/projects", {
        name,
        network_code: network,
        operator: operator || null,
      });
      onOpen(project);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="workbench">
      <h2>프로젝트</h2>
      <p className="hint">관측소 위저드와 NRL 적용은 프로젝트를 연 뒤에 합니다.</p>
      <form className="project-create" onSubmit={onCreate}>
        <label>
          이름
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label>
          네트워크
          <input value={network} onChange={(e) => setNetwork(e.target.value)} maxLength={8} />
        </label>
        <label>
          운영기관
          <input value={operator} onChange={(e) => setOperator(e.target.value)} />
        </label>
        <button type="submit" className="primary" disabled={busy}>
          새 프로젝트
        </button>
      </form>
      {error ? <p className="error">{error}</p> : null}
      <div className="project-grid">
        {projects.map((project) => (
          <button
            key={project.id}
            type="button"
            className="project-card"
            onClick={() => onOpen(project)}
          >
            <strong>{project.name}</strong>
            <span>
              {project.network_code} · {project.station_count} 관측소 · {project.channel_count}{" "}
              채널
            </span>
            <span className="hint">{project.nrl_applied ? "NRL 적용됨" : "응답 없음"}</span>
          </button>
        ))}
      </div>
      {projects.length === 0 ? (
        <p className="hint">아직 프로젝트가 없습니다. 네트워크 코드를 넣고 만드세요.</p>
      ) : null}
    </div>
  );
}
