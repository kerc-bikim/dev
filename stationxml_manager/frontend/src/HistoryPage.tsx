import { useCallback, useEffect, useMemo, useState } from "react";
import { apiGet, type HistoryRow } from "./api";

export function HistoryPage({ onError }: { onError: (e: string | null) => void }) {
  const [rows, setRows] = useState<HistoryRow[]>([]);
  const [filter, setFilter] = useState("");
  const [detail, setDetail] = useState<HistoryRow | null>(null);
  const reload = useCallback(async () => {
    try {
      const q = filter ? `?nslc=${encodeURIComponent(filter)}` : "";
      setRows(await apiGet(`/api/history${q}`));
      onError(null);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  }, [filter, onError]);
  useEffect(() => {
    void reload();
  }, [reload]);
  const pretty = useMemo(() => {
    if (!detail) return "";
    try {
      return JSON.stringify(
        {
          before: detail.before_json ? JSON.parse(detail.before_json) : null,
          after: detail.after_json ? JSON.parse(detail.after_json) : null,
        },
        null,
        2
      );
    } catch {
      return "이력 상세 JSON을 읽을 수 없습니다.";
    }
  }, [detail]);
  return (
    <div className="page-pad">
      <div className="toolbar">
        <input
          placeholder="NSLC 필터"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <button className="secondary" onClick={() => void reload()}>
          새로고침
        </button>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>시각</th>
              <th>작업</th>
              <th>대상</th>
              <th>NSLC</th>
              <th>출처</th>
              <th>작업자</th>
              <th>요약</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="selectable" onClick={() => setDetail(r)}>
                <td>{r.created_at}</td>
                <td>{r.action}</td>
                <td>{r.entity_type}</td>
                <td>{r.nslc}</td>
                <td>{r.source}</td>
                <td>{r.actor}</td>
                <td>{r.summary}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {detail && <pre className="history-detail">{pretty}</pre>}
    </div>
  );
}
