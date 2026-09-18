/** 관리 Web → Grafana Deep Link.

대시보드 UID 와 패널 ID 는 `scripts/gen_grafana.py` 의 상수와 같아야 한다.
패널 ID 를 바꾸면 생성기를 먼저 고치고 JSON 을 다시 뽑는다.
*/

export const GRAFANA_BASE = "/grafana";

export const DASHBOARDS = {
  fleet: "01-fleet-overview",
  station: "02-station-detail",
  centaur: "03-centaur-ctr-detail",
  edge: "04-edge-fleet",
  collector: "05-collector-operations",
  quality: "06-data-quality",
  kiosk: "07-kiosk-overview",
} as const;

/** 관측소 상세 탭 → Grafana 패널. 요약은 대시보드 전체. */
export const STATION_PANELS: Record<string, number | undefined> = {
  summary: 1,
  power: 10,
  timing: 20,
  sensor: 30,
  storage: 40,
  data: 50,
  external: 60,
};

const CATEGORY_TAB: Record<string, string> = {
  power: "power",
  timing: "timing",
  gnss: "timing",
  sensor: "sensor",
  storage: "storage",
  archive: "storage",
  acquisition: "data",
  external_soh: "external",
  connectivity: "summary",
  device: "summary",
};

export function tabForCategory(category: string | undefined): string {
  if (!category) return "summary";
  return CATEGORY_TAB[category] ?? category;
}

function dashboardUrl(uid: string, params: Record<string, string | number | undefined> = {}): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === "") continue;
    search.set(key, String(value));
  }
  const query = search.toString();
  return query ? `${GRAFANA_BASE}/d/${uid}?${query}` : `${GRAFANA_BASE}/d/${uid}`;
}

export function stationGrafanaLink(stationCode: string, tab = "summary"): string {
  const panel = STATION_PANELS[tabForCategory(tab)];
  return dashboardUrl(DASHBOARDS.station, {
    "var-station": stationCode,
    viewPanel: panel,
  });
}

export function edgeGrafanaLink(edgeCode: string): string {
  return dashboardUrl(DASHBOARDS.edge, { "var-edge": edgeCode });
}

export function fleetGrafanaLink(): string {
  return dashboardUrl(DASHBOARDS.fleet);
}

export function kioskGrafanaLink(): string {
  return `${dashboardUrl(DASHBOARDS.kiosk)}?kiosk`;
}

export function collectorGrafanaLink(): string {
  return dashboardUrl(DASHBOARDS.collector);
}
