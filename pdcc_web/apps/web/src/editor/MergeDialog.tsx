import { useState } from "react";
import { apiPost, type FieldDiff } from "../api";

export function MergeDialog({
  projectId,
  fields,
  onDone,
  onCancel,
}: {
  projectId: number;
  fields: FieldDiff[];
  onDone: () => void;
  onCancel: () => void;
}) {
  const [choices, setChoices] = useState<Record<string, string>>(() =>
    Object.fromEntries(fields.map((row) => [row.path, "mine"]))
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onMerge() {
    setBusy(true);
    setError(null);
    try {
      await apiPost(`/api/projects/${projectId}/draft/merge`, { choices });
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="nrl-card wizard">
      <h3>초안 충돌</h3>
      <p className="hint">자동 머지는 하지 않습니다. 필드마다 서버 값 또는 내 값을 고르세요.</p>
      <table className="confirm-table">
        <thead>
          <tr>
            <th>필드</th>
            <th>서버</th>
            <th>내 초안</th>
            <th>선택</th>
          </tr>
        </thead>
        <tbody>
          {fields.map((row) => (
            <tr key={row.path}>
              <td className="mono">{row.path}</td>
              <td>{row.server}</td>
              <td>{row.mine}</td>
              <td>
                <label className="check">
                  <input
                    type="radio"
                    name={row.path}
                    checked={choices[row.path] === "server"}
                    onChange={() => setChoices((prev) => ({ ...prev, [row.path]: "server" }))}
                  />
                  서버
                </label>
                <label className="check">
                  <input
                    type="radio"
                    name={row.path}
                    checked={choices[row.path] === "mine"}
                    onChange={() => setChoices((prev) => ({ ...prev, [row.path]: "mine" }))}
                  />
                  내 값
                </label>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {error ? <p className="error">{error}</p> : null}
      <div className="wizard-nav">
        <button type="button" onClick={onCancel} disabled={busy}>
          취소
        </button>
        <button type="button" className="primary" onClick={onMerge} disabled={busy}>
          머지
        </button>
      </div>
    </div>
  );
}
