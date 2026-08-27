import { FormEvent, useMemo, useState } from "react";
import { apiPost, type Project, type StationSummary } from "../api";

export type CloneRow = {
  code: string;
  site_name: string;
  latitude: string;
  longitude: string;
  elevation: string;
  start: string;
  end: string;
  comment: string;
  serial: string;
};

const COLUMNS: { key: keyof CloneRow; label: string }[] = [
  { key: "code", label: "관측소 코드" },
  { key: "site_name", label: "사이트명" },
  { key: "latitude", label: "위도" },
  { key: "longitude", label: "경도" },
  { key: "elevation", label: "고도" },
  { key: "start", label: "시작" },
  { key: "end", label: "종료" },
  { key: "comment", label: "채널 코멘트" },
  { key: "serial", label: "시리얼" },
];

const HEADERS: Record<string, keyof CloneRow> = {
  code: "code",
  station: "code",
  sta: "code",
  관측소: "code",
  관측소코드: "code",
  코드: "code",
  site: "site_name",
  sitename: "site_name",
  name: "site_name",
  사이트: "site_name",
  사이트명: "site_name",
  lat: "latitude",
  latitude: "latitude",
  위도: "latitude",
  lon: "longitude",
  longitude: "longitude",
  lng: "longitude",
  경도: "longitude",
  elev: "elevation",
  elevation: "elevation",
  고도: "elevation",
  start: "start",
  starttime: "start",
  시작: "start",
  end: "end",
  endtime: "end",
  종료: "end",
  comment: "comment",
  comments: "comment",
  코멘트: "comment",
  채널코멘트: "comment",
  serial: "serial",
  sn: "serial",
  시리얼: "serial",
};

function emptyRow(): CloneRow {
  return {
    code: "",
    site_name: "",
    latitude: "",
    longitude: "",
    elevation: "",
    start: "",
    end: "",
    comment: "",
    serial: "",
  };
}

export function parseClonePaste(text: string): CloneRow[] {
  const raw = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n").replace(/^\n+|\n+$/g, "");
  if (!raw.trim()) return [];
  const lines = raw.split("\n");
  const delimiter = lines.some((line) => line.includes("\t")) ? "\t" : ",";
  const cells = lines.map((line) => line.split(delimiter).map((part) => part.trim()));
  const first = cells[0] ?? [];
  const headerMap: Record<number, keyof CloneRow> = {};
  let hasHeader = false;
  first.forEach((part, index) => {
    const token = part.toLowerCase().replace(/[\s_]/g, "");
    const key = HEADERS[token] ?? HEADERS[part];
    if (key) {
      headerMap[index] = key;
      hasHeader = true;
    }
  });
  const start = hasHeader ? 1 : 0;
  const mapping = hasHeader
    ? headerMap
    : Object.fromEntries(COLUMNS.map((col, index) => [index, col.key])) as Record<number, keyof CloneRow>;
  const rows: CloneRow[] = [];
  for (const parts of cells.slice(start)) {
    if (!parts.some(Boolean)) continue;
    const row = emptyRow();
    parts.forEach((value, index) => {
      const key = mapping[index];
      if (key) row[key] = value;
    });
    rows.push(row);
  }
  return rows;
}

function padRows(rows: CloneRow[], min = 5): CloneRow[] {
  const next = rows.length ? [...rows] : [];
  while (next.length < min) next.push(emptyRow());
  return next;
}

export function CloneTable({
  project,
  source,
  onDone,
  onCancel,
}: {
  project: Project;
  source: StationSummary;
  onDone: (project: Project) => void;
  onCancel: () => void;
}) {
  const [rows, setRows] = useState<CloneRow[]>(() => padRows([]));
  const [paste, setPaste] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const planned = useMemo(() => rows.filter((row) => row.code.trim()), [rows]);
  const ignored = rows.length - planned.length;

  function applyPaste(text: string) {
    const parsed = parseClonePaste(text);
    if (!parsed.length) return;
    setRows(padRows(parsed));
    setPaste(text);
  }

  function update(index: number, key: keyof CloneRow, value: string) {
    setRows((prev) => prev.map((row, i) => (i === index ? { ...row, [key]: value } : row)));
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await apiPost<{ project: Project; created: { code: string }[]; skipped: unknown[] }>(
        `/api/projects/${project.id}/clone-stations`,
        {
          source_station: source.code,
          source_start: source.start,
          rows: rows.map((row) => ({
            code: row.code.trim() || null,
            site_name: row.site_name.trim() || null,
            latitude: row.latitude.trim() ? Number(row.latitude) : null,
            longitude: row.longitude.trim() ? Number(row.longitude) : null,
            elevation: row.elevation.trim() ? Number(row.elevation) : null,
            start: row.start.trim() || null,
            end: row.end.trim() || null,
            comment: row.comment.trim() || null,
            serial: row.serial.trim() || null,
          })),
        }
      );
      onDone(result.project);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="nrl-card clone-card" onSubmit={onSubmit}>
      <h3>관측소 복제</h3>
      <p className="hint">
        1행은 원본 {project.network_code}.{source.code} 입니다. 엑셀에서 복사한 행을 붙여넣으면 표가
        채워집니다. 코드가 비어 있는 행은 만들지 않습니다. 빈 칸은 원본 값을 쓰고, 종료를 비우면 현재
        운영입니다.
      </p>
      <label>
        엑셀 붙여넣기
        <textarea
          id="clone-paste"
          value={paste}
          rows={5}
          placeholder={"TST2\tSite Two\t76.36\t-41.85\t81\n\t\nTST3\tSite Three\t76.37\t-41.86\t82"}
          onChange={(e) => setPaste(e.target.value)}
          onPaste={(e) => {
            const text = e.clipboardData.getData("text/plain");
            if (text.includes("\t") || text.includes("\n")) {
              e.preventDefault();
              applyPaste(text);
            }
          }}
        />
      </label>
      <div className="wizard-nav">
        <button
          type="button"
          id="clone-parse-btn"
          onClick={() => applyPaste(paste)}
          disabled={busy || !paste.trim()}
        >
          표에 넣기
        </button>
        <button type="button" onClick={() => setRows((prev) => [...prev, emptyRow()])} disabled={busy}>
          행 추가
        </button>
      </div>
      <div
        className="clone-table-wrap"
        onPaste={(e) => {
          const text = e.clipboardData.getData("text/plain");
          if (text.includes("\t") || text.split("\n").length > 1) {
            e.preventDefault();
            applyPaste(text);
          }
        }}
      >
        <table className="confirm-table clone-table">
          <thead>
            <tr>
              {COLUMNS.map((col) => (
                <th key={col.key}>{col.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr className="clone-source">
              <td>{source.code}</td>
              <td>{source.site_name}</td>
              <td>{source.latitude}</td>
              <td>{source.longitude}</td>
              <td>{source.elevation}</td>
              <td>{source.start}</td>
              <td>{source.end || "현재"}</td>
              <td className="muted">원본</td>
              <td></td>
            </tr>
            {rows.map((row, index) => (
              <tr key={index}>
                {COLUMNS.map((col) => (
                  <td key={col.key}>
                    <input
                      aria-label={`${index + 1}행 ${col.label}`}
                      value={row[col.key]}
                      maxLength={col.key === "code" ? 5 : col.key === "serial" ? 30 : undefined}
                      onChange={(e) => update(index, col.key, e.target.value)}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="hint" id="clone-preview">
        코드 있는 {planned.length}개 생성, 빈 코드 {ignored}개 무시
        {planned.length ? ` · ${planned.map((row) => row.code.trim().toUpperCase()).join(", ")}` : ""}
      </p>
      {error ? <p className="error">{error}</p> : null}
      <div className="wizard-nav">
        <button type="button" onClick={onCancel} disabled={busy}>
          취소
        </button>
        <button type="submit" className="primary" id="clone-run-btn" disabled={busy || planned.length === 0}>
          복제 실행
        </button>
      </div>
    </form>
  );
}
