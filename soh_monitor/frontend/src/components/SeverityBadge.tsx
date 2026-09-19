const LABELS: Record<string, string> = {
  OK: "정상",
  WARNING: "주의",
  CRITICAL: "장애",
  UNKNOWN: "확인 불가",
  DISABLED: "수집 제외",
  MAINTENANCE: "유지보수",
  UNSUPPORTED: "미지원",
};

const ICONS: Record<string, string> = {
  OK: "●",
  WARNING: "◆",
  CRITICAL: "▲",
  UNKNOWN: "■",
  DISABLED: "○",
  MAINTENANCE: "○",
  UNSUPPORTED: "–",
};

export function severityLabel(severity: string | null | undefined): string {
  if (!severity) return "—";
  return LABELS[severity] ?? severity;
}

export function SeverityBadge({ severity }: { severity: string | null | undefined }) {
  const key = (severity ?? "UNKNOWN").toLowerCase();
  return (
    <span className={`severity ${key}`} title={severity ?? "UNKNOWN"}>
      <span aria-hidden="true">{ICONS[severity ?? "UNKNOWN"] ?? "■"}</span>
      {severityLabel(severity)}
    </span>
  );
}
