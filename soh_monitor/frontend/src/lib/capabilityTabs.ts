/** 관측소 상세 탭을 Capability 로 숨기거나 미지원 표시한다.

미지원 기능을 빈 표로 두면 운영자가 장애로 오인한다. Adapter 가 선언하지 않았거나
탐지 결과가 UNSUPPORTED 이면 탭을 눌러도 값이 오지 않아야 한다.
*/

export const STATION_TABS = [
  { id: "summary", label: "요약", always: true, capabilities: [] as string[] },
  { id: "power", label: "전원", always: false, capabilities: ["power.input_voltage", "power.current"] },
  { id: "timing", label: "시각·GNSS", always: false, capabilities: ["timing.status", "timing.quality", "gnss.receiver"] },
  { id: "sensor", label: "센서", always: false, capabilities: ["sensor.status", "sensor.control_lines", "sensor.mass_position"] },
  { id: "storage", label: "저장소", always: false, capabilities: ["storage.internal", "storage.removable", "archive.continuous", "archive.event"] },
  { id: "data", label: "데이터", always: false, capabilities: ["acquisition.data_check"] },
  { id: "external", label: "외부 SOH", always: false, capabilities: ["external_soh.analog"] },
  { id: "history", label: "수집 이력", always: true, capabilities: [] as string[] },
  { id: "settings", label: "설정", always: true, capabilities: [] as string[] },
  { id: "incidents", label: "장애", always: true, capabilities: [] as string[] },
] as const;

export type StationTabId = (typeof STATION_TABS)[number]["id"];

export interface CapabilityHint {
  key: string;
  supportState?: string | null;
  dimension?: string | null;
}

export interface TabVisibility {
  id: StationTabId;
  label: string;
  unsupported: boolean;
}

function matchesCapability(declared: string, candidate: string): boolean {
  return candidate === declared || candidate.startsWith(`${declared}[`);
}

function relatedStates(capabilities: CapabilityHint[], keys: readonly string[]): CapabilityHint[] {
  return capabilities.filter((item) => keys.some((key) => matchesCapability(key, item.key)));
}

export function tabUnsupported(
  tab: (typeof STATION_TABS)[number],
  detected: CapabilityHint[] | undefined,
  adapterCapabilities: string[] | undefined,
): boolean {
  if (tab.always) return false;

  if (detected && detected.length > 0) {
    const related = relatedStates(detected, tab.capabilities);
    if (related.length === 0) return true;
    return related.every((item) => item.supportState === "UNSUPPORTED");
  }

  if (adapterCapabilities && adapterCapabilities.length > 0) {
    return !tab.capabilities.some((key) => adapterCapabilities.includes(key));
  }

  return false;
}

export function stationTabVisibility(
  detected: CapabilityHint[] | undefined,
  adapterCapabilities: string[] | undefined,
): TabVisibility[] {
  return STATION_TABS.map((tab) => ({
    id: tab.id,
    label: tab.label,
    unsupported: tabUnsupported(tab, detected, adapterCapabilities),
  }));
}
