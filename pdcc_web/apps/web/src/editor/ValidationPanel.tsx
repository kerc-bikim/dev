import type { ValidationIssue } from "../api";

function groups(issues: ValidationIssue[]) {
  const errors = issues.filter((row) => (row.level || "error") === "error");
  const warnings = issues.filter((row) => row.level === "warning");
  return { errors, warnings };
}

function IssueList({
  items,
  kind,
  onJump,
}: {
  items: ValidationIssue[];
  kind: "error" | "warning";
  onJump: (issue: ValidationIssue) => void;
}) {
  if (items.length === 0) return null;
  return (
    <>
      <h4 className={kind === "error" ? "issue-heading error" : "issue-heading warn"}>
        {kind === "error" ? `오류 ${items.length}` : `경고 ${items.length}`}
      </h4>
      <ul className="issue-list">
        {items.map((issue) => (
          <li key={`${issue.path}-${issue.field}-${issue.code}`}>
            <button
              type="button"
              className={kind === "warning" ? "tree-node issue-row warn" : "tree-node issue-row"}
              onClick={() => onJump(issue)}
            >
              <span>
                {issue.official ? (
                  issue.message
                ) : (
                  <>
                    <code>{issue.code}</code> {issue.message}
                  </>
                )}
                <span className="hint">
                  {" "}
                  {issue.station}
                  {issue.nslc ? ` ${issue.nslc}` : ""}
                </span>
              </span>
              <span className="issue-num">{issue.official || issue.code}</span>
            </button>
          </li>
        ))}
      </ul>
    </>
  );
}

export function ValidationPanel({
  issues,
  source,
  mode,
  validating,
  filename,
  onJump,
}: {
  issues: ValidationIssue[];
  source: string;
  mode?: string;
  validating?: boolean;
  filename?: string | null;
  onJump: (issue: ValidationIssue) => void;
}) {
  const { errors, warnings } = groups(issues);
  return (
    <section className="nrl-card" id="validation-panel">
      <h3>검사</h3>
      <p className="hint">
        {source === "draft" ? "초안 기준" : "서버 버전 기준"}
        {mode === "full" ? " · 공식 검증" : " · 즉시 검사"}
        {filename ? ` · ${filename}` : ""}
        {validating ? " · 검증 중…" : ""}
        . 항목을 누르면 해당 칸으로 이동합니다.
      </p>
      {issues.length === 0 ? (
        <p className="hint">{validating ? "검증 중…" : "오류 없음"}</p>
      ) : (
        <>
          <IssueList items={errors} kind="error" onJump={onJump} />
          <IssueList items={warnings} kind="warning" onJump={onJump} />
        </>
      )}
    </section>
  );
}
