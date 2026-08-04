import type { Protocol, SCNL } from "../types";

export type PacketHandler = (
  scnl: SCNL,
  samples: Float32Array,
  startMs: number,
  sampleRate: number,
) => void;

export type StatusHandler = (status: string, detail?: string) => void;

export interface RealtimeClient {
  readonly protocol: Protocol;
  connect(): Promise<void>;
  disconnect(intentional?: boolean): void;
  subscribe(channels: SCNL[]): Promise<void>;
  /** WebSocket이 열려 있는지 (세션 재사용 판단) */
  isOpen(): boolean;
  setDuration?(sec: number): void;
  onPacket: PacketHandler | null;
  onStatus: StatusHandler | null;
  onClose: ((ev: CloseEvent | Event) => void) | null;
}
