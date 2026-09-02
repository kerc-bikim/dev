import { FormEvent, useEffect, useState } from "react";
import {
  apiDelete,
  apiDownload,
  apiGet,
  apiPost,
  apiPut,
  type AdminDashboard,
  type AdminJob,
  type AdminLock,
  type AdminSystem,
  type AuditLogInfo,
  type AuditLogPage,
  type MemberInfo,
  type NrlAliasRule,
  type NrlExcludedRule,
  type NrlLibraryStatus,
  type NrlTestResult,
  type OrgInfo,
  type Project,
  type UserInfo,
} from "../api";
import { AdminHelpLink } from "../help/AdminManual";

const ROLE_LABEL: Record<string, string> = {
  viewer: "조회자",
  editor: "편집자",
  admin: "관리자",
};

const ACTION_LABEL: Record<string, string> = {
  create: "생성",
  import: "가져오기",
  clone: "복제",
  nrl: "NRL 적용",
  restore: "버전 복원",
  save: "저장",
  merge: "머지",
  undo: "실행 취소",
  member: "멤버 변경",
  member_remove: "멤버 해제",
  unlock: "잠금 해제",
  org_create: "기관 생성",
  user_create: "사용자 생성",
  user_deactivate: "사용자 비활성",
  user_activate: "사용자 활성",
  user_password: "비밀번호 재설정",
  user_role: "역할 변경",
  nrl_alias_create: "NRL 별칭 생성",
  nrl_alias_update: "NRL 별칭 수정",
  nrl_alias_delete: "NRL 별칭 삭제",
  nrl_excluded_create: "NRL 제외 장비 생성",
  nrl_excluded_update: "NRL 제외 장비 수정",
  nrl_excluded_delete: "NRL 제외 장비 삭제",
  project_archive: "프로젝트 보관",
  project_restore: "프로젝트 복원",
  job_cancel: "작업 취소",
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

function Dashboard({
  data,
  busy,
  unlockReason,
  onReason,
  onUnlock,
}: {
  data: AdminDashboard;
  busy: boolean;
  unlockReason: string;
  onReason: (value: string) => void;
  onUnlock: (stationPath: string) => void;
}) {
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
      <p className="hint">
        운영 상태만 봅니다. 빨간 배지는 API 5xx, NRL 장애·연속 실패, 실패 작업, 디스크 90%
        이상입니다.
      </p>
      <div className="dash-badges" id="admin-dash-badges">
        {data.badges.api_5xx ? (
          <span className="badge bad" id="dash-badge-api-5xx">
            API 5xx
          </span>
        ) : null}
        {data.badges.nrl ? (
          <span className="badge bad" id="dash-badge-nrl">
            {data.nrl.source === "offline" ? "NRL 장애" : "NRL 연속 실패"}
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
        {!data.badges.api_5xx &&
        !data.badges.nrl &&
        !data.badges.failed_jobs &&
        !data.badges.disk ? (
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
        <div id="dash-backup-status">
          <span>
            마지막 백업 성공 <AdminHelpLink chapter={7} label="백업과 복구 확인" />
          </span>
          <strong>{data.backup.confirmed ? formatWhen(data.backup.last_success_at) : "확인 기록 없음"}</strong>
        </div>
      </div>
      <p className="hint">
        백업 성공 시각은 데이터베이스 덤프 검증을 마친 운영 절차가 기록한 값입니다.
      </p>
      <h4>운영 알림</h4>
      <table className="confirm-table" id="dash-monitoring-alerts" aria-live="polite">
        <thead>
          <tr>
            <th>종류</th>
            <th>상태</th>
            <th>마지막 발생</th>
          </tr>
        </thead>
        <tbody>
          {data.alerts.length === 0 ? (
            <tr>
              <td colSpan={3}>활성 알림이 없습니다</td>
            </tr>
          ) : (
            data.alerts.map((alert) => (
              <tr key={alert.kind}>
                <td>
                  <span className="badge bad">{alert.title}</span>
                </td>
                <td>
                  {alert.message}
                  {alert.kind === "api_5xx" && data.monitoring.api_5xx.last_path ? (
                    <span className="hint">
                      {" "}
                      · {data.monitoring.api_5xx.last_method} {data.monitoring.api_5xx.last_path} ·{" "}
                      {data.monitoring.api_5xx.last_status}
                    </span>
                  ) : null}
                </td>
                <td>{formatWhen(alert.last_at)}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
      <div className="dash-nrl" id="dash-nrl">
        <p>
          NRL <AdminHelpLink chapter={4} label="NRL 연결과 캐시" />{" "}
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
            {data.nrl.cache_count ?? 0}개 · 연속 실패 {data.monitoring.nrl.consecutive_failures}회
            (알림 기준 {data.monitoring.nrl.threshold}회)
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
      <h4>
        실패한 작업 최근 10개 <AdminHelpLink chapter={9} label="실패 작업 대응" />
      </h4>
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
      <h4>
        잠금이 10분 이상 남은 관측소 <AdminHelpLink chapter={8} label="잠금 강제 해제" />
      </h4>
      <table className="confirm-table" id="dash-long-locks">
        <thead>
            <tr>
              <th>관측소</th>
              <th>편집자</th>
              <th>남은 시간</th>
              <th>강제 해제</th>
            </tr>
        </thead>
        <tbody>
          {data.locks.length === 0 ? (
            <tr>
              <td colSpan={4}>해당 잠금이 없습니다</td>
            </tr>
          ) : (
            data.locks.map((lock) => (
              <tr key={lock.station_path}>
                <td>{lock.station_path}</td>
                <td>{lock.username}</td>
                <td>{formatRemain(lock.remaining_sec)}</td>
                <td>
                  <div className="wizard-nav">
                    <input
                      aria-label={`${lock.station_path} 강제 해제 사유`}
                      placeholder="사유"
                      value={unlockReason}
                      onChange={(event) => onReason(event.target.value)}
                    />
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => onUnlock(lock.station_path)}
                    >
                      강제 해제
                    </button>
                  </div>
                </td>
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
  const [auditLogs, setAuditLogs] = useState<AuditLogInfo[]>([]);
  const [auditTotal, setAuditTotal] = useState(0);
  const [auditProjectId, setAuditProjectId] = useState<number | "">("");
  const [nrlLibrary, setNrlLibrary] = useState<NrlLibraryStatus | null>(null);
  const [orgs, setOrgs] = useState<OrgInfo[]>([]);
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [members, setMembers] = useState<MemberInfo[]>([]);
  const [aliases, setAliases] = useState<NrlAliasRule[]>([]);
  const [excluded, setExcluded] = useState<NrlExcludedRule[]>([]);
  const [aliasQuery, setAliasQuery] = useState("");
  const [aliasManufacturer, setAliasManufacturer] = useState("");
  const [aliasModel, setAliasModel] = useState("");
  const [excludedQuery, setExcludedQuery] = useState("");
  const [excludedName, setExcludedName] = useState("");
  const [excludedMessage, setExcludedMessage] = useState("");
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
  const [unlockReason, setUnlockReason] = useState("");
  const [nrlTest, setNrlTest] = useState<string | null>(null);
  const [jobs, setJobs] = useState<AdminJob[]>([]);
  const [liveLocks, setLiveLocks] = useState<AdminLock[]>([]);
  const [unlockPath, setUnlockPath] = useState("");
  const [jobProjectId, setJobProjectId] = useState<number | "">("");
  const [jobKind, setJobKind] = useState("");
  const [jobStatus, setJobStatus] = useState("");
  const [system, setSystem] = useState<AdminSystem | null>(null);

  async function refresh() {
    const [
      dashData,
      libraryData,
      aliasData,
      excludedData,
      orgData,
      userData,
      projectData,
      systemData,
      lockData,
    ] = await Promise.all([
      apiGet<AdminDashboard>("/api/admin/dashboard"),
      apiGet<NrlLibraryStatus>("/api/nrl/library"),
      apiGet<{ aliases: NrlAliasRule[] }>("/api/admin/nrl/aliases"),
      apiGet<{ excluded: NrlExcludedRule[] }>("/api/admin/nrl/excluded"),
      apiGet<{ orgs: OrgInfo[] }>("/api/admin/orgs"),
      apiGet<{ users: UserInfo[] }>("/api/admin/users"),
      apiGet<{ projects: Project[] }>("/api/projects"),
      apiGet<AdminSystem>("/api/admin/system"),
      apiGet<{ locks: AdminLock[] }>("/api/admin/locks"),
    ]);
    setDashboard(dashData);
    setNrlLibrary(libraryData);
    setAliases(aliasData.aliases);
    setExcluded(excludedData.excluded);
    setOrgs(orgData.orgs);
    setUsers(userData.users);
    setProjects(projectData.projects);
    setSystem(systemData);
    setLiveLocks(lockData.locks);
    if (orgId === "" && orgData.orgs[0]) setOrgId(orgData.orgs[0].id);
  }

  async function refreshJobs(
    project: number | "" = jobProjectId,
    kind: string = jobKind,
    status: string = jobStatus
  ) {
    const params = new URLSearchParams();
    if (project !== "") params.set("project_id", String(project));
    if (kind) params.set("kind", kind);
    if (status) params.set("status", status);
    const query = params.toString() ? `?${params.toString()}` : "";
    const data = await apiGet<{ jobs: AdminJob[] }>(`/api/admin/jobs${query}`);
    setJobs(data.jobs);
  }

  async function refreshAudit(project: number | "" = auditProjectId) {
    const query = project === "" ? "" : `?project_id=${project}`;
    const data = await apiGet<AuditLogPage>(`/api/admin/audit-logs${query}`);
    setAuditLogs(data.audit_logs);
    setAuditTotal(data.total);
  }

  useEffect(() => {
    refresh().catch((err: Error) => setError(err.message));
    refreshAudit().catch((err: Error) => setError(err.message));
    refreshJobs().catch((err: Error) => setError(err.message));
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

  async function refreshNrlRules() {
    const [aliasData, excludedData] = await Promise.all([
      apiGet<{ aliases: NrlAliasRule[] }>("/api/admin/nrl/aliases"),
      apiGet<{ excluded: NrlExcludedRule[] }>("/api/admin/nrl/excluded"),
    ]);
    setAliases(aliasData.aliases);
    setExcluded(excludedData.excluded);
  }

  async function onCreateAlias(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await apiPost("/api/admin/nrl/aliases", {
        query: aliasQuery,
        manufacturer: aliasManufacturer,
        model: aliasModel,
      });
      setAliasQuery("");
      setAliasManufacturer("");
      setAliasModel("");
      await refreshNrlRules();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function saveAlias(row: NrlAliasRule) {
    setBusy(true);
    setError(null);
    try {
      await apiPut(`/api/admin/nrl/aliases/${row.id}`, row);
      await refreshNrlRules();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function deleteAlias(id: number) {
    setBusy(true);
    setError(null);
    try {
      await apiDelete(`/api/admin/nrl/aliases/${id}`);
      await refreshNrlRules();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function onCreateExcluded(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await apiPost("/api/admin/nrl/excluded", {
        query: excludedQuery,
        name: excludedName,
        message: excludedMessage,
      });
      setExcludedQuery("");
      setExcludedName("");
      setExcludedMessage("");
      await refreshNrlRules();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function saveExcluded(row: NrlExcludedRule) {
    setBusy(true);
    setError(null);
    try {
      await apiPut(`/api/admin/nrl/excluded/${row.id}`, row);
      await refreshNrlRules();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function deleteExcluded(id: number) {
    setBusy(true);
    setError(null);
    try {
      await apiDelete(`/api/admin/nrl/excluded/${id}`);
      await refreshNrlRules();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

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

  async function testNrl() {
    setBusy(true);
    setError(null);
    try {
      const data = await apiPost<NrlTestResult>("/api/nrl/test");
      const sample = (data.elements || []).slice(0, 6).join(", ");
      const cache = data.ok
        ? ""
        : data.last_ok_at
          ? ` · 최근 성공 캐시 ${formatWhen(data.last_ok_at)}`
          : " · 최근 성공 캐시 없음";
      setNrlTest(
        `${data.ok ? "성공" : "실패"} HTTP ${data.status_code} · ${data.elapsed_ms} ms · ${data.url}` +
          (sample ? ` · element ${sample}` : "") +
          cache
      );
      await refresh();
    } catch (err) {
      setNrlTest((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function refreshCatalog() {
    setBusy(true);
    setError(null);
    try {
      const data = await apiPost<{ elements: string[]; prefix_count: number }>(
        "/api/nrl/catalog/refresh"
      );
      setNrlTest(
        `카탈로그 새로고침 · element ${data.elements.join(", ") || "없음"} · prefix ${data.prefix_count}`
      );
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function forceUnlock(stationPath: string) {
    if (!unlockReason.trim()) {
      setError("강제 해제 사유를 입력하세요");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await apiPost("/api/admin/locks/unlock", {
        station_path: stationPath,
        reason: unlockReason.trim(),
      });
      setUnlockReason("");
      setUnlockPath("");
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function downloadJobLog(jobId: string) {
    try {
      const { filename, blob } = await apiDownload(`/api/admin/jobs/${jobId}/log`);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename || `job-${jobId}.log`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function cancelAdminJob(jobId: string) {
    setBusy(true);
    setError(null);
    try {
      await apiPost(`/api/admin/jobs/${jobId}/cancel`);
      await refreshJobs();
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
        <h2>
          관리자 <AdminHelpLink chapter={1} label="관리자 운영" />
        </h2>
      </div>
      <p className="hint">운영 대시보드와 기관·사용자·역할을 여기서 봅니다. 관리자가 아니면 홈으로 돌아갑니다.</p>
      {error ? <p className="error">{error}</p> : null}
      {dashboard ? (
        <Dashboard
          data={dashboard}
          busy={busy}
          unlockReason={unlockReason}
          onReason={setUnlockReason}
          onUnlock={forceUnlock}
        />
      ) : (
        <p className="hint">대시보드를 불러오는 중…</p>
      )}

      <section className="nrl-card" id="admin-audit-logs">
        <div className="section-heading">
          <div>
            <h3>감사 로그</h3>
            <p className="hint">
              최근 기록 {auditLogs.length}건 / 전체 {auditTotal}건 · NRL 적용 기록은 instconfig를
              함께 보관합니다.
            </p>
          </div>
          <div className="wizard-nav">
            <label>
              프로젝트
              <select
                id="audit-project-filter"
                value={auditProjectId}
                onChange={(event) => {
                  const next = event.target.value ? Number(event.target.value) : "";
                  setAuditProjectId(next);
                  refreshAudit(next).catch((err: Error) => setError(err.message));
                }}
              >
                <option value="">전체</option>
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name} ({project.network_code})
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              onClick={() => refreshAudit().catch((err: Error) => setError(err.message))}
            >
              새로고침
            </button>
          </div>
        </div>
        <div className="table-scroll">
          <table className="confirm-table audit-table">
            <thead>
              <tr>
                <th>시각</th>
                <th>프로젝트</th>
                <th>사용자</th>
                <th>작업</th>
                <th>내용</th>
              </tr>
            </thead>
            <tbody>
              {auditLogs.length === 0 ? (
                <tr>
                  <td colSpan={5}>감사 기록이 없습니다</td>
                </tr>
              ) : (
                auditLogs.map((row) => (
                  <tr key={row.id}>
                    <td>{formatWhen(row.created_at)}</td>
                    <td>{row.project_name || "시스템"}</td>
                    <td>{row.actor}</td>
                    <td>{ACTION_LABEL[row.action] || row.action}</td>
                    <td>
                      <strong>{row.summary}</strong>
                      {row.target ? <span className="audit-target">대상: {row.target}</span> : null}
                      {row.details ? (
                        <code className="audit-details">
                          {row.details.replace(/^instconfig=/, "instconfig: ")}
                        </code>
                      ) : null}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="nrl-card" id="admin-nrl-offline">
        <h3>
          NRL 전체 zip 오프라인 <AdminHelpLink chapter={4} label="NRL 오프라인 zip" />
        </h3>
        <p className="hint">
          {nrlLibrary?.available
            ? `${nrlLibrary.responses}개 응답 · ${formatBytes(nrlLibrary.bytes)} · ${nrlLibrary.path}`
            : nrlLibrary?.error || "서버에 전체 zip이 없습니다."}
        </p>
        <div className="wizard-nav">
          <button type="button" disabled={busy} onClick={testNrl}>
            연결 테스트
          </button>
          <button type="button" disabled={busy} onClick={refreshCatalog}>
            카탈로그 새로고침
          </button>
          <button type="button" disabled={busy} onClick={downloadNrlLibrary}>
            전체 라이브러리 받기
          </button>
          <button
            type="button"
            className={dashboard?.nrl.mode === "online" ? "primary" : ""}
            disabled={busy}
            onClick={() => setNrlMode("online")}
          >
            온라인
          </button>
          <button
            type="button"
            className={dashboard?.nrl.mode === "cache-first" ? "primary" : ""}
            disabled={busy}
            onClick={() => setNrlMode("cache-first")}
          >
            캐시 우선
          </button>
          <button
            type="button"
            className={dashboard?.nrl.mode === "offline" ? "primary" : ""}
            disabled={busy}
            onClick={() => setNrlMode("offline")}
          >
            오프라인
          </button>
        </div>
        {nrlTest ? <p className="hint" id="admin-nrl-test-result">{nrlTest}</p> : null}
      </section>

      <section className="nrl-card" id="admin-jobs">
        <h3>
          작업 목록 <AdminHelpLink chapter={9} label="실패 작업 대응" />
        </h3>
        <p className="hint">프로젝트·유형·상태로 필터하고, 실패 로그를 받거나 대기 작업을 취소합니다.</p>
        <div className="wizard-nav">
          <label>
            프로젝트
            <select
              id="admin-job-project"
              value={jobProjectId}
              onChange={(event) => {
                const next = event.target.value ? Number(event.target.value) : "";
                setJobProjectId(next);
                refreshJobs(next, jobKind, jobStatus).catch((err: Error) => setError(err.message));
              }}
            >
              <option value="">전체</option>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name} ({project.network_code})
                </option>
              ))}
            </select>
          </label>
          <label>
            유형
            <select
              id="admin-job-kind"
              value={jobKind}
              onChange={(event) => {
                setJobKind(event.target.value);
                refreshJobs(jobProjectId, event.target.value, jobStatus).catch((err: Error) =>
                  setError(err.message)
                );
              }}
            >
              <option value="">전체</option>
              <option value="validate">검증</option>
              <option value="dataless">SEED</option>
              <option value="resp">RESP</option>
            </select>
          </label>
          <label>
            상태
            <select
              id="admin-job-status"
              value={jobStatus}
              onChange={(event) => {
                setJobStatus(event.target.value);
                refreshJobs(jobProjectId, jobKind, event.target.value).catch((err: Error) =>
                  setError(err.message)
                );
              }}
            >
              <option value="">전체</option>
              <option value="queued">대기</option>
              <option value="running">진행</option>
              <option value="succeeded">완료</option>
              <option value="failed">실패</option>
              <option value="cancelled">취소</option>
            </select>
          </label>
        </div>
        <div className="table-scroll">
          <table className="confirm-table" id="admin-job-table">
            <thead>
              <tr>
                <th>시각</th>
                <th>프로젝트</th>
                <th>유형</th>
                <th>상태</th>
                <th>사용자</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {jobs.length === 0 ? (
                <tr>
                  <td colSpan={6}>작업이 없습니다</td>
                </tr>
              ) : (
                jobs.map((job) => (
                  <tr key={job.id}>
                    <td>{formatWhen(job.created_at)}</td>
                    <td>{job.project_name || job.project_id}</td>
                    <td>{job.kind}</td>
                    <td>{job.status}</td>
                    <td>{job.username}</td>
                    <td className="wizard-nav">
                      <button type="button" onClick={() => downloadJobLog(job.id)}>
                        실패 로그
                      </button>
                      {job.status === "queued" ? (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => cancelAdminJob(job.id)}
                        >
                          취소
                        </button>
                      ) : null}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="nrl-card" id="admin-locks">
        <h3>
          현재 잠금 <AdminHelpLink chapter={8} label="잠금 강제 해제" />
        </h3>
        <p className="hint">
          기본 잠금은 5분입니다. 대시보드의 10분 이상 목록과 달리 여기서 모든 활성 잠금을 해제할 수
          있습니다. 사유는 필수이며 초안은 유지됩니다.
        </p>
        <form
          className="project-create"
          onSubmit={(event) => {
            event.preventDefault();
            forceUnlock(unlockPath);
          }}
        >
          <label>
            관측소 경로
            <input
              id="admin-unlock-path"
              value={unlockPath}
              onChange={(event) => setUnlockPath(event.target.value)}
              placeholder="sta:1:YZ.TEST1#2009-04-10T00:00:00"
              required
            />
          </label>
          <label>
            사유
            <input
              id="admin-unlock-reason"
              aria-label="강제 해제 사유"
              value={unlockReason}
              onChange={(event) => setUnlockReason(event.target.value)}
              placeholder="사유"
              required
            />
          </label>
          <button type="submit" className="primary" disabled={busy} id="admin-unlock-submit">
            강제 해제
          </button>
        </form>
        <div className="table-scroll">
          <table className="confirm-table" id="admin-lock-table">
            <thead>
              <tr>
                <th>관측소</th>
                <th>편집자</th>
                <th>남은 시간</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {liveLocks.length === 0 ? (
                <tr>
                  <td colSpan={4}>활성 잠금이 없습니다</td>
                </tr>
              ) : (
                liveLocks.map((lock) => (
                  <tr key={lock.station_path}>
                    <td>{lock.station_path}</td>
                    <td>{lock.username}</td>
                    <td>{formatRemain(lock.remaining_sec)}</td>
                    <td>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => forceUnlock(lock.station_path)}
                      >
                        강제 해제
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="nrl-card" id="admin-nrl-aliases">
        <h3>
          NRL 검색 별칭 <AdminHelpLink chapter={5} label="NRL 검색 별칭" />
        </h3>
        <p className="hint">저장한 별칭은 다음 NRL 검색부터 즉시 적용됩니다.</p>
        <form className="project-create" onSubmit={onCreateAlias}>
          <label>
            검색어
            <input
              value={aliasQuery}
              onChange={(event) => setAliasQuery(event.target.value)}
              placeholder="예: metrozet"
              required
            />
          </label>
          <label>
            NRL 제조사
            <input
              value={aliasManufacturer}
              onChange={(event) => setAliasManufacturer(event.target.value)}
              placeholder="예: EQMet"
              required
            />
          </label>
          <label>
            모델(선택)
            <input value={aliasModel} onChange={(event) => setAliasModel(event.target.value)} />
          </label>
          <button type="submit" className="primary" disabled={busy}>
            별칭 추가
          </button>
        </form>
        <div className="table-scroll">
          <table className="confirm-table rule-table">
            <thead>
              <tr>
                <th>검색어</th>
                <th>NRL 제조사</th>
                <th>모델</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {aliases.map((row) => (
                <tr key={row.id}>
                  <td>
                    <input
                      aria-label={`${row.query} 별칭 검색어`}
                      value={row.query}
                      onChange={(event) =>
                        setAliases((current) =>
                          current.map((item) =>
                            item.id === row.id ? { ...item, query: event.target.value } : item
                          )
                        )
                      }
                    />
                  </td>
                  <td>
                    <input
                      aria-label={`${row.query} NRL 제조사`}
                      value={row.manufacturer}
                      onChange={(event) =>
                        setAliases((current) =>
                          current.map((item) =>
                            item.id === row.id
                              ? { ...item, manufacturer: event.target.value }
                              : item
                          )
                        )
                      }
                    />
                  </td>
                  <td>
                    <input
                      aria-label={`${row.query} 모델`}
                      value={row.model}
                      onChange={(event) =>
                        setAliases((current) =>
                          current.map((item) =>
                            item.id === row.id ? { ...item, model: event.target.value } : item
                          )
                        )
                      }
                    />
                  </td>
                  <td>
                    <div className="wizard-nav">
                      <button type="button" disabled={busy} onClick={() => saveAlias(row)}>
                        저장
                      </button>
                      <button type="button" disabled={busy} onClick={() => deleteAlias(row.id)}>
                        삭제
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="nrl-card" id="admin-nrl-excluded">
        <h3>
          NRL 제외 장비 <AdminHelpLink chapter={5} label="NRL 제외 장비" />
        </h3>
        <p className="hint">
          저장한 장비는 다음 검색부터 NRL 결과 대신 아래 안내를 표시합니다.
        </p>
        <form className="project-create" onSubmit={onCreateExcluded}>
          <label>
            검색어
            <input
              value={excludedQuery}
              onChange={(event) => setExcludedQuery(event.target.value)}
              placeholder="예: certimus"
              required
            />
          </label>
          <label>
            장비명
            <input
              value={excludedName}
              onChange={(event) => setExcludedName(event.target.value)}
              required
            />
          </label>
          <label>
            검색 안내
            <input
              value={excludedMessage}
              onChange={(event) => setExcludedMessage(event.target.value)}
              required
            />
          </label>
          <button type="submit" className="primary" disabled={busy}>
            제외 장비 추가
          </button>
        </form>
        <div className="table-scroll">
          <table className="confirm-table rule-table">
            <thead>
              <tr>
                <th>검색어</th>
                <th>장비명</th>
                <th>검색 안내</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {excluded.map((row) => (
                <tr key={row.id}>
                  <td>
                    <input
                      aria-label={`${row.query} 제외 검색어`}
                      value={row.query}
                      onChange={(event) =>
                        setExcluded((current) =>
                          current.map((item) =>
                            item.id === row.id ? { ...item, query: event.target.value } : item
                          )
                        )
                      }
                    />
                  </td>
                  <td>
                    <input
                      aria-label={`${row.query} 장비명`}
                      value={row.name}
                      onChange={(event) =>
                        setExcluded((current) =>
                          current.map((item) =>
                            item.id === row.id ? { ...item, name: event.target.value } : item
                          )
                        )
                      }
                    />
                  </td>
                  <td>
                    <input
                      aria-label={`${row.query} 검색 안내`}
                      value={row.message}
                      onChange={(event) =>
                        setExcluded((current) =>
                          current.map((item) =>
                            item.id === row.id ? { ...item, message: event.target.value } : item
                          )
                        )
                      }
                    />
                  </td>
                  <td>
                    <div className="wizard-nav">
                      <button type="button" disabled={busy} onClick={() => saveExcluded(row)}>
                        저장
                      </button>
                      <button type="button" disabled={busy} onClick={() => deleteExcluded(row.id)}>
                        삭제
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="nrl-card">
        <h3>
          기관 <AdminHelpLink chapter={3} label="기관 관리" />
        </h3>
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
        <h3>
          사용자 <AdminHelpLink chapter={3} label="사용자와 역할 관리" />
        </h3>
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
        <h3>
          프로젝트 멤버 <AdminHelpLink chapter={3} label="프로젝트 역할 관리" />
        </h3>
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
      <section className="nrl-card" id="admin-system">
        <h3>
          시스템 <AdminHelpLink chapter={6} label="변환기 설정" />
        </h3>
        {system ? (
          <>
            <dl className="manual-fields" id="admin-system-limits">
              <div>
                <dt>업로드 한도</dt>
                <dd>{formatBytes(system.upload.max_upload_bytes)}</dd>
              </div>
              <div>
                <dt>zip 한도</dt>
                <dd>
                  {formatBytes(system.upload.max_zip_bytes)} · 항목 {system.upload.max_zip_members}개
                </dd>
              </div>
              <div>
                <dt>변환 타임아웃</dt>
                <dd>
                  converter {system.timeouts.converter_sec}s · validator {system.timeouts.validator_sec}s ·
                  NRL {system.timeouts.nrl_sec}s
                </dd>
              </div>
              <div>
                <dt>SEED --organization / --label</dt>
                <dd>
                  {system.seed.organization || "(프로젝트 운영기관)"} /{" "}
                  {system.seed.label || "(네트워크 코드)"}
                </dd>
              </div>
              <div>
                <dt>세션 만료</dt>
                <dd>{Math.round(system.session_ttl_sec / 3600)}시간</dd>
              </div>
              <div>
                <dt>마지막 백업 성공</dt>
                <dd>
                  {system.backup.confirmed ? formatWhen(system.backup.last_success_at) : "확인 기록 없음"}
                </dd>
              </div>
            </dl>
            <h4>라이선스·인용</h4>
            <ul className="empty-hints" id="admin-citations">
              {system.citations.map((row) => (
                <li key={row.name}>
                  {row.name}: {row.text}
                  {row.doi ? ` · DOI ${row.doi}` : ""}
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="hint">시스템 값을 불러오는 중…</p>
        )}
      </section>
    </div>
  );
}
