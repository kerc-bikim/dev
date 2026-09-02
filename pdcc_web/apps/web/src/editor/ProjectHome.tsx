import { ChangeEvent, FormEvent, MouseEvent, useEffect, useRef, useState } from "react";
import { apiGet, apiPost, apiPut, apiUpload, type Me, type MemberInfo, type Project, type UserInfo } from "../api";

const ROLE_LABEL: Record<string, string> = {
  viewer: "조회자",
  editor: "편집자",
  admin: "관리자",
};

export function ProjectHome({
  onOpen,
  me,
}: {
  onOpen: (project: Project) => void;
  me?: Me;
}) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [name, setName] = useState("YZ 상시망");
  const [network, setNetwork] = useState("YZ");
  const [operator, setOperator] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [memberProject, setMemberProject] = useState<Project | null>(null);
  const [members, setMembers] = useState<MemberInfo[]>([]);
  const [memberUserId, setMemberUserId] = useState<number | "">("");
  const [memberRole, setMemberRole] = useState("viewer");
  const fileRef = useRef<HTMLInputElement | null>(null);
  const canCreate = me?.role !== "viewer";
  const isAdmin = me?.role === "admin";

  useEffect(() => {
    apiGet<{ projects: Project[] }>("/api/projects")
      .then((data) => setProjects(data.projects))
      .catch((err: Error) => setError(err.message));
    if (isAdmin) {
      apiGet<{ users: UserInfo[] }>("/api/admin/users")
        .then((data) => setUsers(data.users))
        .catch(() => undefined);
    }
  }, [isAdmin]);

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
      const form = new FormData();
      form.append("file", file);
      if (name.trim()) form.append("name", name.trim());
      if (operator) form.append("operator", operator);
      const project = await apiUpload<Project>("/api/projects/import-file", form);
      onOpen(project);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function openMembers(event: MouseEvent, project: Project) {
    event.stopPropagation();
    setError(null);
    setMemberProject(project);
    try {
      const data = await apiGet<{ members: MemberInfo[] }>(`/api/projects/${project.id}/members`);
      setMembers(data.members);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function addMember(event: FormEvent) {
    event.preventDefault();
    if (!memberProject || memberUserId === "") return;
    setBusy(true);
    setError(null);
    try {
      await apiPut(`/api/projects/${memberProject.id}/members`, {
        user_id: memberUserId,
        role: memberRole,
      });
      const data = await apiGet<{ members: MemberInfo[] }>(
        `/api/projects/${memberProject.id}/members`
      );
      setMembers(data.members);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="workbench">
      <h2>프로젝트</h2>
      <p className="hint">
        {canCreate
          ? "StationXML, dataless SEED, RESP를 열거나 빈 네트워크를 만든 뒤 관측소 위저드를 씁니다."
          : "조회자는 속한 프로젝트만 보고 StationXML을 받을 수 있습니다."}
      </p>
      {canCreate ? (
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
          accept=".xml,.seed,.dataless,.resp,.RESP,text/xml,application/xml,text/plain"
          hidden
          onChange={onOpenFile}
        />
      </form>
      ) : null}
      {error ? <p className="error">{error}</p> : null}
      <div className="project-grid">
        {projects.map((project) => (
          <div key={project.id} className="project-card-wrap">
          <button
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
              {project.has_original
                ? project.original_kind === "dataless"
                  ? " · 원본 dataless 보관"
                  : project.original_kind === "resp"
                    ? " · 원본 RESP 보관"
                    : " · 원본 보관"
                : ""}
              {project.nrl_applied ? " · NRL 적용됨" : " · 응답 없음"}
              {project.my_role ? ` · ${ROLE_LABEL[project.my_role] || project.my_role}` : ""}
            </span>
          </button>
          {isAdmin ? (
            <button type="button" className="member-btn" onClick={(e) => openMembers(e, project)}>
              멤버
            </button>
          ) : null}
          </div>
        ))}
      </div>
      {memberProject ? (
        <section className="nrl-card">
          <h3>{memberProject.name} 멤버</h3>
          <form className="project-create" onSubmit={addMember}>
            <label>
              사용자
              <select
                value={memberUserId}
                onChange={(e) => setMemberUserId(e.target.value ? Number(e.target.value) : "")}
              >
                <option value="">선택</option>
                {users.map((user) => (
                  <option key={user.id} value={user.id}>
                    {user.display_name} ({user.username})
                  </option>
                ))}
              </select>
            </label>
            <label>
              역할
              <select value={memberRole} onChange={(e) => setMemberRole(e.target.value)}>
                <option value="viewer">조회자</option>
                <option value="editor">편집자</option>
                <option value="admin">관리자</option>
              </select>
            </label>
            <button type="submit" className="primary" disabled={busy}>
              추가
            </button>
            <button type="button" onClick={() => setMemberProject(null)}>
              닫기
            </button>
          </form>
          <ul className="empty-hints">
            {members.map((row) => (
              <li key={row.user_id}>
                {row.display_name} ({row.username}) · {ROLE_LABEL[row.role] || row.role}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {projects.length === 0 ? (
        <ul className="empty-hints">
          <li>새 프로젝트로 빈 네트워크를 만드세요.</li>
          <li>파일 열기로 StationXML, dataless SEED 또는 RESP를 가져오세요.</li>
          <li>관측소 위저드는 프로젝트를 연 뒤에 씁니다.</li>
        </ul>
      ) : null}
    </div>
  );
}
