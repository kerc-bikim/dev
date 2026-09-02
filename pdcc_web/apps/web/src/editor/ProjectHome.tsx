import { ChangeEvent, FormEvent, useEffect, useRef, useState } from "react";
import { apiGet, apiPost, type Project } from "../api";

export function ProjectHome({ onOpen }: { onOpen: (project: Project) => void }) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [name, setName] = useState("YZ 상시망");
  const [network, setNetwork] = useState("YZ");
  const [operator, setOperator] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);

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

  async function onOpenFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const xmlText = await file.text();
      const project = await apiPost<Project>("/api/projects/import", {
        filename: file.name,
        xml_text: xmlText,
        name: name.trim() || undefined,
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
      <p className="hint">StationXML을 열거나 빈 네트워크를 만든 뒤 관측소 위저드를 씁니다.</p>
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
        <button
          type="button"
          id="open-xml-btn"
          disabled={busy}
          onClick={() => fileRef.current?.click()}
        >
          파일 열기
        </button>
        <input
          ref={fileRef}
          id="open-xml-file"
          type="file"
          accept=".xml,text/xml,application/xml"
          hidden
          onChange={onOpenFile}
        />
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
              {project.network_code} · {project.status} · {project.station_count} 관측소 ·{" "}
              {project.channel_count} 채널
            </span>
            <span className="hint">
              {project.updated_at ? project.updated_at.slice(0, 16).replace("T", " ") : ""}
              {project.has_original ? " · 원본 보관" : ""}
              {project.nrl_applied ? " · NRL 적용됨" : " · 응답 없음"}
            </span>
          </button>
        ))}
      </div>
      {projects.length === 0 ? (
        <ul className="empty-hints">
          <li>새 프로젝트로 빈 네트워크를 만드세요.</li>
          <li>파일 열기로 StationXML을 가져오세요.</li>
          <li>관측소 위저드는 프로젝트를 연 뒤에 씁니다.</li>
        </ul>
      ) : null}
    </div>
  );
}
