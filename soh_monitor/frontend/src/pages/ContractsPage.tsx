import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api, type MetricDefinitionDto } from "../api/client";

const SEVERITY_LABELS: Record<string, string> = {
  OK: "정상",
  WARNING: "주의",
  CRITICAL: "장애",
  UNKNOWN: "확인 불가",
  DISABLED: "수집 제외",
  MAINTENANCE: "유지보수",
};

function SourceLabel({ source }: { source: string }) {
  const labels: Record<string, string> = {
    adapter: "기록계",
    collector: "수집기",
    data_availability: "데이터 검사",
    health_engine: "판정 엔진",
  };
  return <span className="badge">{labels[source] ?? source}</span>;
}

export function ContractsPage() {
  const catalog = useQuery({ queryKey: ["metric-catalog"], queryFn: api.metricCatalog });
  const adapters = useQuery({ queryKey: ["adapters"], queryFn: api.adapters });
  const readiness = useQuery({ queryKey: ["readiness"], queryFn: api.readiness });

  const [category, setCategory] = useState("all");
  const [keyword, setKeyword] = useState("");

  const metrics: MetricDefinitionDto[] = useMemo(() => {
    const all = catalog.data?.metrics ?? [];
    return all.filter((metric) => {
      const matchesCategory = category === "all" || metric.category === category;
      const needle = keyword.trim().toLowerCase();
      const matchesKeyword =
        needle === "" ||
        metric.key.toLowerCase().includes(needle) ||
        metric.displayName.toLowerCase().includes(needle);
      return matchesCategory && matchesKeyword;
    });
  }, [catalog.data, category, keyword]);

  if (catalog.isLoading) {
    return <p>표준 Metric 카탈로그를 불러오는 중이다.</p>;
  }

  if (catalog.isError) {
    return (
      <div className="notice warn">
        카탈로그를 불러오지 못했다. 백엔드 API 가 떠 있는지 확인한다.
      </div>
    );
  }

  const data = catalog.data!;
  const requiredCount = data.metrics.filter((metric) => metric.required).length;
  const measurements = new Set(data.metrics.map((metric) => metric.measurement));

  return (
    <>
      <h1 className="page-title">표준 Metric</h1>
      <p className="page-subtitle">
        화면은 Metric 목록을 담고 있지 않다. 백엔드가 <code>contracts/metrics/catalog.yaml</code>{" "}
        을 읽어 내려준 것을 그대로 보여 준다. 카탈로그에 Metric 을 추가하면 이 표가 따라온다.
      </p>

      <div className="card">
        <h2>계약 상태</h2>
        <div className="stat-grid">
          <div className="stat">
            <div className="label">카탈로그 버전</div>
            <div className="value">{data.version}</div>
          </div>
          <div className="stat">
            <div className="label">표준 Metric</div>
            <div className="value">{data.metrics.length}</div>
          </div>
          <div className="stat">
            <div className="label">필수 Metric</div>
            <div className="value">{requiredCount}</div>
          </div>
          <div className="stat">
            <div className="label">Measurement</div>
            <div className="value">{measurements.size}</div>
          </div>
          <div className="stat">
            <div className="label">등록된 Adapter</div>
            <div className="value">{adapters.data?.adapters.length ?? 0}</div>
          </div>
          <div className="stat">
            <div className="label">API 준비 상태</div>
            <div className="value">{readiness.data?.ready ? "정상" : "확인 필요"}</div>
          </div>
        </div>
      </div>

      <div className="card">
        <h2>표준 상태 값</h2>
        <div className="severity-legend">
          {data.statuses.map((status) => (
            <span key={status} className={`severity ${status.toLowerCase()}`}>
              {SEVERITY_LABELS[status] ?? status} ({status})
            </span>
          ))}
        </div>
        <p style={{ marginBottom: 0, color: "var(--muted)", fontSize: "0.9rem" }}>
          미지원(장비에 기능이 없음)과 확인 불가(수집 실패로 모름)를 정상으로 접지 않는다.
          이 구분이 알림 신뢰도를 지킨다.
        </p>
      </div>

      {(adapters.data?.adapters.length ?? 0) === 0 && (
        <div className="notice warn" style={{ marginBottom: "1.25rem" }}>
          등록된 기록계 Adapter 가 없다. Centaur CTR Adapter 는 M2 에서 등록되며, 그전까지
          장비 등록은 열리지 않는다.
        </div>
      )}

      <div className="card">
        <h2>Metric 목록</h2>
        <div className="filter-row">
          <select value={category} onChange={(event) => setCategory(event.target.value)}>
            <option value="all">전체 분류</option>
            {data.categories.map((item) => (
              <option key={item.key} value={item.key}>
                {item.displayName}
              </option>
            ))}
          </select>
          <input
            type="search"
            placeholder="Metric 키 또는 이름 검색"
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
          />
          <span style={{ color: "var(--muted)", fontSize: "0.88rem" }}>
            {metrics.length} / {data.metrics.length}
          </span>
        </div>
        <table>
          <thead>
            <tr>
              <th>Metric 키</th>
              <th>이름</th>
              <th>단위</th>
              <th>출처</th>
              <th>차원</th>
              <th>필요 기능</th>
            </tr>
          </thead>
          <tbody>
            {metrics.map((metric) => (
              <tr key={metric.key + metric.dimensions.join(",")}>
                <td>
                  <code>{metric.key}</code>
                  {metric.required && (
                    <>
                      {" "}
                      <span className="badge required">필수</span>
                    </>
                  )}
                </td>
                <td>{metric.displayName}</td>
                <td>{metric.unit ?? "-"}</td>
                <td>
                  <SourceLabel source={metric.source} />
                </td>
                <td>{metric.dimensions.length ? metric.dimensions.join(", ") : "-"}</td>
                <td>{metric.capability ? <code>{metric.capability}</code> : "항상"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
