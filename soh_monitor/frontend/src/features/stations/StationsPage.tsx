import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError, api } from "../../api/client";
import { useAuth } from "../../auth/AuthProvider";
import { SeverityBadge } from "../../components/SeverityBadge";

const LIST_CATEGORIES = [
  { key: "connectivity", label: "통신" },
  { key: "power", label: "전원" },
  { key: "timing", label: "시각" },
  { key: "sensor", label: "센서" },
  { key: "storage", label: "저장소" },
  { key: "acquisition", label: "데이터" },
];

export function StationsPage() {
  const { can } = useAuth();
  const queryClient = useQueryClient();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [severity, setSeverity] = useState("");
  const [importResult, setImportResult] = useState<string | null>(null);
  const [importError, setImportError] = useState<string | null>(null);

  const stations = useQuery({
    queryKey: ["stations", status, q],
    queryFn: () => api.stations({ status: status || undefined, q: q || undefined }),
    refetchInterval: 15_000,
    placeholderData: keepPreviousData,
  });

  const retire = useMutation({
    mutationFn: api.retireStation,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["stations"] }),
  });

  const filtered = useMemo(() => {
    const rows = stations.data?.stations ?? [];
    if (!severity) return rows;
    return rows.filter((row) => (row.worstSeverity ?? "UNKNOWN") === severity);
  }, [stations.data, severity]);

  async function onImport(file: File) {
    setImportError(null);
    setImportResult(null);
    try {
      const result = await api.importStations(file);
      setImportResult(`${result.imported}곳 등록, ${result.failed}행 실패`);
      await queryClient.invalidateQueries({ queryKey: ["stations"] });
    } catch (error) {
      setImportError(error instanceof ApiError ? error.message : "가져오지 못했다");
    }
  }

  return (
    <>
      <h1 className="page-title">관측소</h1>
      <p className="page-subtitle">분류별 상태는 판정 엔진 결과다. 미지원과 확인 불가를 정상으로 접지 않는다.</p>

      <div className="toolbar">
        <input
          type="search"
          placeholder="코드·이름 검색"
          value={q}
          onChange={(event) => setQ(event.target.value)}
        />
        <select value={status} onChange={(event) => setStatus(event.target.value)}>
          <option value="">모든 생애주기</option>
          <option value="ACTIVE">ACTIVE</option>
          <option value="PLANNED">PLANNED</option>
          <option value="SUSPENDED">SUSPENDED</option>
          <option value="RETIRED">RETIRED</option>
        </select>
        <select value={severity} onChange={(event) => setSeverity(event.target.value)}>
          <option value="">모든 상태</option>
          <option value="OK">정상</option>
          <option value="WARNING">주의</option>
          <option value="CRITICAL">장애</option>
          <option value="UNKNOWN">확인 불가</option>
        </select>
        {can("configure") && (
          <>
            <Link className="btn primary" to="/stations/new">
              관측소 등록
            </Link>
            <label className="btn ghost">
              CSV 가져오기
              <input
                type="file"
                accept=".csv,text/csv"
                hidden
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void onImport(file);
                  event.target.value = "";
                }}
              />
            </label>
          </>
        )}
      </div>
      {importResult && <div className="notice">{importResult}</div>}
      {importError && <div className="notice warn">{importError}</div>}

      <div className="card">
        <table>
          <thead>
            <tr>
              <th>코드</th>
              <th>이름</th>
              <th>종합</th>
              {LIST_CATEGORIES.map((category) => (
                <th key={category.key}>{category.label}</th>
              ))}
              <th>수집</th>
              <th>마지막 성공</th>
              {can("configure") && <th></th>}
            </tr>
          </thead>
          <tbody>
            {filtered.map((station) => (
              <tr key={station.id}>
                <td>
                  <Link to={`/stations/${station.id}`}>
                    {station.networkCode}.{station.stationCode}
                  </Link>
                </td>
                <td>{station.name}</td>
                <td>
                  <SeverityBadge severity={station.worstSeverity} />
                </td>
                {LIST_CATEGORIES.map((category) => (
                  <td key={category.key}>
                    {station.categories[category.key] ? (
                      <SeverityBadge severity={station.categories[category.key]} />
                    ) : (
                      <span className="muted" title="미수집 또는 미지원">
                        —
                      </span>
                    )}
                  </td>
                ))}
                <td>
                  {station.edgeUnreachable ? (
                    <span title="기록계 장애가 아니라 Edge 가 응답하지 않는다">
                      EDGE UNREACHABLE
                    </span>
                  ) : (
                    (station.collectionMode ?? "—")
                  )}
                </td>
                <td>{station.lastSuccessAt?.replace("T", " ").slice(0, 19) ?? "—"}</td>
                {can("configure") && (
                  <td>
                    {station.status !== "RETIRED" && (
                      <button className="btn ghost" type="button" onClick={() => retire.mutate(station.id)}>
                        폐기
                      </button>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
        {filtered.length === 0 && <p className="muted">조건에 맞는 관측소가 없다.</p>}
      </div>
    </>
  );
}
