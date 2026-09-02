import type { ValidationIssue } from "../api";

export function ValidationPanel({
  issues,
  source,
  onJump,
}: {
  issues: ValidationIssue[];
  source: string;
  onJump: (issue: ValidationIssue) => void;
}) {
  return (
    <section className="nrl-card" id="validation-panel">
      <h3>검사</h3>
      <p className="hint">
        {source === "draft" ? "초안 기준" : "서버 버전 기준"} · 오류를 누르면 해당 칸으로 이동합니다.
      </p>
      {issues.length === 0 ? (
        <p className="hint">오류 없음</p>
      ) : (
        <ul className="issue-list">
          {issues.map((issue) => (
            <li key={`${issue.path}-${issue.field}-${issue.code}`}>
              <button type="button" className="tree-node" onClick={() => onJump(issue)}>
                <code>{issue.code}</code> {issue.message}
                <span className="hint">
                  {" "}
                  {issue.station}
                  {issue.nslc ? ` ${issue.nslc}` : ""} · {issue.field}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
