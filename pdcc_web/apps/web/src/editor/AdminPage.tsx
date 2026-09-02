import { FormEvent, useEffect, useState } from "react";
import {
  apiGet,
  apiPost,
  apiPut,
  type AdminDashboard,
  type MemberInfo,
  type NrlLibraryStatus,
  type OrgInfo,
  type Project,
  type UserInfo,
} from "../api";

const ROLE_LABEL: Record<string, string> = {
  viewer: "조회자",
  editor: "편집자",
  admin: "관리자",
};

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  return `${(value / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

function formatWhen(value: string | null | undefined): string {
  if (!value) return "없음";
  return value.replace("T", " ").replace("Z", " UTC");
}

function formatRemain(sec: number): string {
  const minutes = Math.max(0, Math.round(sec / 60));
  if (minutes < 60) return `${minutes}분 남음`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours}시간 ${rest}분 남음` : `${hours}시간 남음`;
}

function Dashboard({ data }: { data: AdminDashboard }) {
  const nrlLabel =
    data.nrl.badge ||
    (data.nrl.source === "online"
      ? "온라인"
      : data.nrl.source === "cache"
        ? "캐시 사용"
        : data.nrl.source === "offline"
          ? "NRL 장애"
          : "아직 없음");
  return (
    <section className="nrl-card" id="admin-dashboard">
      <h3>대시보드</h3>
      <p className="hint">운영 상태만 봅니다. 빨간 배지는 NRL 장애, 실패 작업, 디스크 90% 이상입니다.</p>
      <div className="dash-badges" id="admin-dash-badges">
        {data.badges.nrl ? (
          <span className="badge bad" id="dash-badge-nrl">
            NRL 장애
          </span>
        ) : null}
        {data.badges.failed_jobs ? (
          <span className="badge bad" id="dash-badge-jobs">
            실패 작업
          </span>
        ) : null}
        {data.badges.disk ? (
          <span className="badge bad" id="dash-badge-disk">
            디스크 90% 이상
          </span>
        ) : null}
        {!data.badges.nrl && !data.badges.failed_jobs && !data.badges.disk ? (
          <span className="hint">빨간 배지 없음</span>
        ) : null}
      </div>
      <div className="dash-stats">
        <div>
          <span>사용자</span>
          <strong id="dash-user-count">{data.user_count}</strong>
        </div>
        <div>
          <span>프로젝트</span>
          <strong id="dash-project-count">{data.project_count}</strong>
        </div>
        <div>
          <span>오늘 내보내기</span>
          <strong id="dash-export-count">{data.export_count_today}</strong>
        </div>
      </div>
      <div className="dash-nrl" id="dash-nrl">
        <p>
          NRL{" "}
          <span
            className={
              "badge " +
              (data.nrl.source === "online" || data.nrl.source === "zip"
                ? "ok"
                : data.nrl.source === "cache"
                  ? "warn"
                  : data.nrl.source === "offline"
                    ? "bad"
                    : "")
            }
          >
            {nrlLabel}
          </span>
          <span className="hint">
            {" "}
            · 모드 {data.nrl.mode} · 마지막 동기화 {formatWhen(data.nrl.last_ok_at)} · 캐시된 응답{" "}
            {data.nrl.cache_count ?? 0}개
          </span>
        </p>
      </div>
      <table className="confirm-table" id="dash-disk-table">
        <thead>
          <tr>
            <th>디스크</th>
            <th>크기</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>원본 파일</td>
            <td>{formatBytes(data.disk.originals_bytes)}</td>
          </tr>
          <tr>
            <td>export</td>
            <td>{formatBytes(data.disk.exports_bytes)}</td>
          </tr>
          <tr>
            <td>NRL zip</td>
            <td>{formatBytes(data.disk.nrl_zip_bytes)}</td>
          </tr>
          <tr>
            <td>볼륨 사용</td>
            <td>
              {data.disk.percent}% ({formatBytes(data.disk.used_bytes)} / {formatBytes(data.disk.total_bytes)})
            </td>
          </tr>
        </tbody>
      </table>
      <h4>실패한 작업 최근 10개</h4>
      <table className="confirm-table" id="dash-failed-jobs">
        <thead>
          <tr>
            <th>시각</th>
            <th>유형</th>
            <th>사용자</th>
            <th>오류</th>
          </tr>
        </thead>
        <tbody>
          {data.failed_jobs.length === 0 ? (
            <tr>
              <td colSpan={4}>실패한 작업이 없습니다</td>
            </tr>
          ) : (
            data.failed_jobs.map((job) => (
              <tr key={job.id}>
                <td>{formatWhen(job.finished_at || job.created_at)}</td>
                <td>{job.kind}</td>
                <td>{job.username}</td>
                <td>{job.error || job.message}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
      <h4>잠금이 10분 이상 남은 관측소</h4>
      <table className="confirm-table" id="dash-long-locks">
        <thead>
          <tr>
            <th>관측소</th>
            <th>편집자</th>
            <th>남은 시간</th>
          </tr>
        </thead>
        <tbody>
          {data.locks.length === 0 ? (
            <tr>
              <td colSpan={3}>해당 잠금이 없습니다</td>
            </tr>
          ) : (
            data.locks.map((lock) => (
              <tr key={lock.station_path}>
                <td>{lock.station_path}</td>
                <td>{lock.username}</td>
                <td>{formatRemain(lock.remaining_sec)}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </section>
  );
}

export function AdminPage({ onHome }: { onHome: () => void }) {
  const [dashboard, setDashboard] = useState<AdminDashboard | null>(null);
  const [nrlLibrary, setNrlLibrary] = useState<NrlLibraryStatus | null>(null);
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
    const [dashData, libraryData, orgData, userData, projectData] = await Promise.all([
      apiGet<AdminDashboard>("/api/admin/dashboard"),
      apiGet<NrlLibraryStatus>("/api/nrl/library"),
      apiGet<{ orgs: OrgInfo[] }>("/api/admin/orgs"),
      apiGet<{ users: UserInfo[] }>("/api/admin/users"),
      apiGet<{ projects: Project[] }>("/api/projects"),
    ]);
    setDashboard(dashData);
    setNrlLibrary(libraryData);
    setOrgs(orgData.orgs);
    setUsers(userData.users);
    setProjects(projectData.projects);
    if (orgId === "" && orgData.orgs[0]) setOrgId(orgData.orgs[0].id);
  }

  useEffect(() => {
    refresh().catch((err: Error) => setError(err.message));
    const id = window.setInterval(() => {
      apiGet<AdminDashboard>("/api/admin/dashboard")
        .then(setDashboard)
        .catch((err: Error) => setError(err.message));
    }, 15000);
    return () => window.clearInterval(id);
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

  async function downloadNrlLibrary() {
    setBusy(true);
    setError(null);
    try {
      const result = await apiPost<NrlLibraryStatus>("/api/nrl/library/download");
      setNrlLibrary(result);
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function setNrlMode(mode: string) {
    setBusy(true);
    setError(null);
    try {
      await apiPost("/api/nrl/mode", { mode });
      await refresh();
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
      <p className="hint">운영 대시보드와 기관·사용자·역할을 여기서 봅니다. 관리자가 아니면 홈으로 돌아갑니다.</p>
      {error ? <p className="error">{error}</p> : null}
      {dashboard ? <Dashboard data={dashboard} /> : <p className="hint">대시보드를 불러오는 중…</p>}

      <section className="nrl-card" id="admin-nrl-offline">
        <h3>NRL 전체 zip 오프라인</h3>
        <p className="hint">
          {nrlLibrary?.available
            ? `${nrlLibrary.responses}개 응답 · ${formatBytes(nrlLibrary.bytes)} · ${nrlLibrary.path}`
            : nrlLibrary?.error || "서버에 전체 zip이 없습니다."}
        </p>
        <div className="wizard-nav">
          <button type="button" disabled={busy} onClick={downloadNrlLibrary}>
            EarthScope에서 전체 zip 받기
          </button>
          <button
            type="button"
            className={dashboard?.nrl.mode === "offline" ? "primary" : ""}
            disabled={busy}
            onClick={() => setNrlMode("offline")}
          >
            오프라인 사용
          </button>
          <button
            type="button"
            className={dashboard?.nrl.mode !== "offline" ? "primary" : ""}
            disabled={busy}
            onClick={() => setNrlMode("online")}
          >
            온라인 사용
          </button>
        </div>
      </section>

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
