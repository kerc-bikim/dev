import { useEffect, useState } from "react";
import { apiGet, apiPost, type FieldDiff, type VersionInfo } from "../api";

export function VersionPanel({
  projectId,
  disabled,
  onRestored,
}: {
  projectId: number;
  disabled?: boolean;
  onRestored?: () => void;
}) {
  const [versions, setVersions] = useState<VersionInfo[]>([]);
  const [diff, setDiff] = useState<FieldDiff[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  function load() {
    apiGet<{ versions: VersionInfo[] }>(`/api/projects/${projectId}/versions`)
      .then((data) => setVersions(data.versions))
      .catch((err: Error) => setError(err.message));
  }

  useEffect(() => {
    load();
  }, [projectId]);

  async function showDiff(left: VersionInfo, right: VersionInfo) {
    setError(null);
    try {
      const data = await apiGet<{ fields: FieldDiff[] }>(
        `/api/projects/${projectId}/versions/${left.id}/diff/${right.id}`
      );
      setDiff(data.fields);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function restore(row: VersionInfo) {
    if (disabled) return;
    if (!window.confirm(`버전 ${row.number}을 복원할까요? 새 버전이 생깁니다.`)) return;
    setError(null);
    try {
      await apiPost(`/api/projects/${projectId}/versions/${row.id}/restore`);
      onRestored?.();
      load();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <section className="nrl-card">
      <h3>버전</h3>
      {versions.length === 0 ? <p className="hint">저장된 버전이 없습니다.</p> : null}
      <ul className="version-list">
        {versions.map((row, idx) => (
          <li key={row.id}>
            <span>
              v{row.number} {row.summary} · {row.actor}
            </span>
            <button type="button" disabled={disabled} onClick={() => restore(row)}>
              되돌리기
            </button>
            {idx < versions.length - 1 ? (
              <button type="button" onClick={() => showDiff(row, versions[idx + 1])}>
                이전과 비교
              </button>
            ) : null}
          </li>
        ))}
      </ul>
      {diff ? (
        <table className="confirm-table">
          <thead>
            <tr>
              <th>필드</th>
              <th>이 버전</th>
              <th>비교</th>
            </tr>
          </thead>
          <tbody>
            {diff.map((row) => (
              <tr key={row.path}>
                <td className="mono">{row.path}</td>
                <td>{row.a}</td>
                <td>{row.b}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {error ? <p className="error">{error}</p> : null}
    </section>
  );
}
