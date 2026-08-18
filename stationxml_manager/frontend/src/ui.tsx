import type { ReactNode } from "react";
import type { CatalogRow, ChannelRow } from "./api";

export const NEW_EQUIPMENT = "__new__";
export const NRL_DISABLED_HINT =
  "이 장비는 NRL 키가 없습니다. StationXML/SEED로 응답을 가져오거나, 카탈로그에 키를 넣은 뒤 적용하세요.";

export function catalogLabel(row: CatalogRow): string {
  const tag = row.nrl_keys ? "NRL" : "사용자 정의";
  if (row.kind === "datalogger" && row.sample_rate) {
    return `${row.code} (${row.sample_rate} sps, ${tag})`;
  }
  return `${row.code} (${tag})`;
}

export function canApplyNrl(
  row: ChannelRow,
  sensors: CatalogRow[],
  loggers: CatalogRow[]
): boolean {
  const sensor = sensors.find((item) => item.code === row.sensor_id);
  const logger = loggers.find((item) => item.code === row.datalogger_id);
  return Boolean(sensor?.nrl_keys && logger?.nrl_keys);
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="field">
      {label}
      {children}
    </label>
  );
}

export function responseBadge(source?: string | null, hasResponse?: boolean): string {
  if (!hasResponse) return "없음";
  if (source === "imported") return "imported";
  if (source === "nrl") return "nrl";
  if (source === "edited") return "edited";
  return source || "있음";
}
