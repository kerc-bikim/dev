export type Protocol = "datalink";
export type AmplitudeMode = "raw" | "physical";
/** Y축: 패널별 자동 스케일 | 최대 진폭 패널 기준 공통 스케일 */
export type YScaleMode = "auto" | "uniform";
/** X축 오른쪽(최신) 기준: 현재 시각 | 수신된 마지막 데이터 시각 */
export type XAxisRightAnchor = "now" | "lastData";
export type ConnectionStatus =
  | "connecting"
  | "connected"
  | "reconnecting"
  | "disconnected"
  | "error";

export type SCNL = {
  network: string;
  station: string;
  location: string;
  channel: string;
};

export type WaveformColors = {
  palette: string[];
  channelColorMap: Record<string, string>;
  gapColor: string;
  selectionColor: string;
};

export type AppSettings = {
  ringserverUrl: string;
  fdsnwsUrl: string;
  protocol: Protocol;
  durationSec: number;
  refreshIntervalMs: number;
  maxPanels: number;
  amplitudeMode: AmplitudeMode;
  /** Y축 스케일 모드 */
  yScaleMode: YScaleMode;
  /** X축 오른쪽 끝 기준 */
  xAxisRightAnchor: XAxisRightAnchor;
  waveformColors: WaveformColors;
};

export type LayoutPayload = {
  channels: SCNL[];
  durationSec?: number;
  refreshIntervalMs?: number;
  amplitudeMode?: AmplitudeMode;
  yScaleMode?: YScaleMode;
  xAxisRightAnchor?: XAxisRightAnchor;
  waveformColors?: WaveformColors;
};

export type LayoutItem = {
  id: number;
  name: string;
  createdAt: string;
  updatedAt: string;
  payload: LayoutPayload;
};

export type GapInterval = { startMs: number; endMs: number };

export function scnlKey(s: SCNL): string {
  const loc = s.location && s.location !== "" ? s.location : "--";
  return `${s.network}.${s.station}.${loc}.${s.channel}`;
}

export function scnlLabel(s: SCNL): string {
  return scnlKey(s);
}
