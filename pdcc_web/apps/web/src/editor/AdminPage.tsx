import { FormEvent, useEffect, useState } from "react";
import {
  apiGet,
  apiPost,
  apiPut,
  type MemberInfo,
  type OrgInfo,
  type Project,
  type UserInfo,
} from "../api";

const ROLE_LABEL: Record<string, string> = {
  viewer: "조회자",
  editor: "편집자",
  admin: "관리자",
};

export function AdminPage({ onHome }: { onHome: () => void }) {
  const [orgs, setOrgs] = useState<OrgInfo[]>([]);
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [members, setMembers] = useState<MemberInfo[]>([]);
  const [orgName, setOrgName] = useState("");
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("editor");
  const [orgId, setOrgId] = useState<number | "">("");
  const [projectId, setProjectId] = useState<number | "">("");
  const [memberUserId, setMemberUserId] = useState<number | "">("");
  const [memberRole, setMemberRole] = useState("viewer");
  const [resetId, setResetId] = useState<number | null>(null);
  const [resetPassword, setResetPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    const [orgData, userData, projectData] = await Promise.all([
      apiGet<{ orgs: OrgInfo[] }>("/api/admin/orgs"),
      apiGet<{ users: UserInfo[] }>("/api/admin/users"),
      apiGet<{ projects: Project[] }>("/api/projects"),
    ]);
    setOrgs(orgData.orgs);
    setUsers(userData.users);
    setProjects(projectData.projects);
    if (orgId === "" && orgData.orgs[0]) setOrgId(orgData.orgs[0].id);
  }

  useEffect(() => {
    refresh().catch((err: Error) => setError(err.message));
  }, []);

  useEffect(() => {
    if (projectId === "") {
      setMembers([]);
      return;
    }
    apiGet<{ members: MemberInfo[] }>(`/api/projects/${projectId}/members`)
      .then((data) => setMembers(data.members))
      .catch((err: Error) => setError(err.message));
  }, [projectId]);

  async function onCreateOrg(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await apiPost("/api/admin/orgs", { name: orgName });
      setOrgName("");
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function onCreateUser(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await apiPost("/api/admin/users", {
        username,
        password,
        role,
        display_name: displayName || username,
        org_id: orgId === "" ? null : orgId,
      });
      setUsername("");
      setDisplayName("");
      setPassword("");
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function toggleActive(user: UserInfo) {
    setBusy(true);
    setError(null);
    try {
      const path = user.active
        ? `/api/admin/users/${user.id}/deactivate`
        : `/api/admin/users/${user.id}/activate`;
      await apiPost(path);
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function onResetPassword(event: FormEvent) {
    event.preventDefault();
    if (resetId == null) return;
    setBusy(true);
    setError(null);
    try {
      await apiPost(`/api/admin/users/${resetId}/password`, { password: resetPassword });
      setResetId(null);
      setResetPassword("");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function onAddMember(event: FormEvent) {
    event.preventDefault();
    if (projectId === "" || memberUserId === "") return;
    setBusy(true);
    setError(null);
    try {
      await apiPut(`/api/projects/${projectId}/members`, {
        user_id: memberUserId,
        role: memberRole,
      });
      const data = await apiGet<{ members: MemberInfo[] }>(`/api/projects/${projectId}/members`);
      setMembers(data.members);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="workbench admin-page">
      <div className="editor-top">
        <button type="button" onClick={onHome}>
          프로젝트 목록
        </button>
        <h2>관리자</h2>
      </div>
      <p className="hint">기관·사용자·역할을 만들고, 프로젝트 멤버를 여기서도 바꿉니다.</p>
      {error ? <p className="error">{error}</p> : null}

      <section className="nrl-card">
        <h3>기관</h3>
        <form className="project-create" onSubmit={onCreateOrg}>
          <label>
            이름
            <input value={orgName} onChange={(e) => setOrgName(e.target.value)} required />
          </label>
          <button type="submit" className="primary" disabled={busy}>
            기관 추가
          </button>
        </form>
        <table className="confirm-table">
          <thead>
            <tr>
              <th>기관</th>
              <th>사용자</th>
            </tr>
          </thead>
          <tbody>
            {orgs.map((org) => (
              <tr key={org.id}>
                <td>{org.name}</td>
                <td>{org.user_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="nrl-card">
        <h3>사용자</h3>
        <form className="project-create" onSubmit={onCreateUser}>
          <label>
            아이디
            <input value={username} onChange={(e) => setUsername(e.target.value)} required />
          </label>
          <label>
            이름
            <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
          </label>
          <label>
            비밀번호
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
          <label>
            역할
            <select value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="viewer">조회자</option>
              <option value="editor">편집자</option>
              <option value="admin">관리자</option>
            </select>
          </label>
          <label>
            기관
            <select
              value={orgId}
              onChange={(e) => setOrgId(e.target.value ? Number(e.target.value) : "")}
            >
              {orgs.map((org) => (
                <option key={org.id} value={org.id}>
                  {org.name}
                </option>
              ))}
            </select>
          </label>
          <button type="submit" className="primary" disabled={busy} id="admin-create-user">
            사용자 생성
          </button>
        </form>
        <table className="confirm-table" id="admin-user-table">
          <thead>
            <tr>
              <th>아이디</th>
              <th>이름</th>
              <th>역할</th>
              <th>기관</th>
              <th>상태</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {users.map((user) => (
              <tr key={user.id}>
                <td>{user.username}</td>
                <td>{user.display_name}</td>
                <td>{ROLE_LABEL[user.role] || user.role}</td>
                <td>{user.org_name || "—"}</td>
                <td>{user.active ? "활성" : "비활성"}</td>
                <td className="wizard-nav">
                  <button type="button" disabled={busy} onClick={() => toggleActive(user)}>
                    {user.active ? "비활성" : "활성"}
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => {
                      setResetId(user.id);
                      setResetPassword("");
                    }}
                  >
                    비밀번호
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {resetId != null ? (
          <form className="project-create" onSubmit={onResetPassword}>
            <label>
              새 비밀번호
              <input
                type="password"
                value={resetPassword}
                onChange={(e) => setResetPassword(e.target.value)}
                required
              />
            </label>
            <button type="submit" className="primary" disabled={busy}>
              재설정
            </button>
            <button type="button" onClick={() => setResetId(null)}>
              취소
            </button>
          </form>
        ) : null}
      </section>

      <section className="nrl-card">
        <h3>프로젝트 멤버</h3>
        <form className="project-create" onSubmit={onAddMember}>
          <label>
            프로젝트
            <select
              value={projectId}
              onChange={(e) => setProjectId(e.target.value ? Number(e.target.value) : "")}
            >
              <option value="">선택</option>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name} ({project.network_code})
                </option>
              ))}
            </select>
          </label>
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
          <button type="submit" className="primary" disabled={busy} id="admin-add-member">
            멤버 추가
          </button>
        </form>
        <table className="confirm-table">
          <thead>
            <tr>
              <th>사용자</th>
              <th>역할</th>
            </tr>
          </thead>
          <tbody>
            {members.map((row) => (
              <tr key={row.user_id}>
                <td>
                  {row.display_name} ({row.username})
                </td>
                <td>{ROLE_LABEL[row.role] || row.role}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
