import { miniseed } from "seisplotjs";
import type { SCNL } from "../types";
import { scnlKey } from "../types";
import type { PacketHandler, RealtimeClient, StatusHandler } from "./types";
import { ringserverWsUrl } from "./wsUrl";

/**
 * ringserver DataLink는 WebSocket 위에서도 TCP와 동일하게
 * pre-header `DL` + uint8(len) + command 바이너리 패킷을 요구한다.
 * (텍스트 `ID ...\\r\\n` 은 sequence bytes (ID) 오류를 낸다.)
 */

export function buildMatchPattern(channels: SCNL[]): string {
  const alts: string[] = [];
  for (const c of channels) {
    const loc = !c.location || c.location === "--" ? "" : c.location;
    const ch = c.channel;
    if (ch.length >= 3) {
      alts.push(`FDSN:${c.network}_${c.station}_${loc}_${ch[0]}_${ch[1]}_${ch[2]}`);
      alts.push(
        `FDSN:${c.network}_${c.station}_${loc}_${ch[0]}_${ch[1]}_${ch[2]}/MSEED`,
      );
    }
    alts.push(`${c.network}_${c.station}_${loc}_${ch}`);
    if (!loc) alts.push(`${c.network}_${c.station}__${ch}`);
  }
  return alts.map((p) => p.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|");
}

/** seisplotjs encodeDL 과 동일한 wire format */
export function encodeDL(header: string, data?: Uint8Array): ArrayBuffer {
  let cmdLen = header.length;
  let len = 3 + header.length;
  let lenStr = "";

  if (data && data.length > 0) {
    lenStr = String(data.length);
    len += lenStr.length + 1;
    cmdLen += lenStr.length + 1;
    len += data.length;
  }

  const rawPacket = new ArrayBuffer(len);
  const binaryPacket = new Uint8Array(rawPacket);
  const packet = new DataView(rawPacket);
  packet.setUint8(0, 0x44); // D
  packet.setUint8(1, 0x4c); // L
  packet.setUint8(2, cmdLen);
  let i = 3;
  for (let hi = 0; hi < header.length; hi++) {
    packet.setUint8(i++, header.charCodeAt(hi));
  }
  if (data && data.length > 0) {
    packet.setUint8(i++, 0x20); // space
    for (let li = 0; li < lenStr.length; li++) {
      packet.setUint8(i++, lenStr.charCodeAt(li));
    }
    binaryPacket.set(data, i);
  }
  return rawPacket;
}

export class DataLinkClient implements RealtimeClient {
  readonly protocol = "datalink" as const;
  onPacket: PacketHandler | null = null;
  onStatus: StatusHandler | null = null;
  onClose: ((ev: CloseEvent | Event) => void) | null = null;

  private ws: WebSocket | null = null;
  private intentionalClose = false;
  private channels: SCNL[] = [];
  private ringserverHttpUrl: string | null;
  private durationSec: number;
  private pending:
    | { resolve: (v: string) => void; reject: (e: Error) => void }
    | null = null;

  constructor(ringserverHttpUrl?: string | null, durationSec = 300) {
    this.ringserverHttpUrl = ringserverHttpUrl ?? null;
    this.durationSec = Math.max(1, durationSec);
  }

  setDuration(sec: number) {
    this.durationSec = Math.max(1, sec);
  }

  isOpen(): boolean {
    return !!this.ws && this.ws.readyState === WebSocket.OPEN;
  }

  async connect(): Promise<void> {
    this.intentionalClose = false;
    // 이미 열린 세션이 있으면 재사용 (끊지 않음)
    if (this.isOpen()) {
      this.onStatus?.("connected", "DataLink session reused");
      return;
    }
    if (this.ws) this.disconnect(true);

    const url = ringserverWsUrl("/datalink", this.ringserverHttpUrl);
    await new Promise<void>((resolve, reject) => {
      const ws = new WebSocket(url, ["DataLink1.0", "DataLink1.1"]);
      this.ws = ws;
      ws.binaryType = "arraybuffer";

      const timer = window.setTimeout(() => {
        reject(new Error("DataLink connect timeout"));
      }, 10000);

      ws.onopen = () => {
        void this.sendCommand(
          `ID WaveViewer:browser:${Math.floor(Math.random() * 30000) + 1}:web`,
        )
          .then((id) => {
            window.clearTimeout(timer);
            this.onStatus?.(
              "connected",
              id || `DataLink ${ws.protocol || "binary"}`,
            );
            resolve();
          })
          .catch((e) => {
            window.clearTimeout(timer);
            reject(e);
          });
      };
      ws.onerror = () => {
        window.clearTimeout(timer);
        reject(new Error("DataLink WebSocket error"));
      };
      ws.onclose = (ev) => {
        this.onClose?.(ev);
        if (!this.intentionalClose) this.onStatus?.("disconnected", "DataLink closed");
        if (this.pending) {
          this.pending.reject(new Error("socket closed"));
          this.pending = null;
        }
      };
      ws.onmessage = (ev) => this.handleMessage(ev);
    });
  }

  disconnect(intentional = true): void {
    this.intentionalClose = intentional;
    try {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(encodeDL("ENDSTREAM"));
      }
    } catch {
      /* ignore */
    }
    try {
      this.ws?.close();
    } catch {
      /* ignore */
    }
    this.ws = null;
    this.pending = null;
  }

  async subscribe(channels: SCNL[]): Promise<void> {
    this.channels = channels;
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      await this.connect();
    }
    if (!channels.length) return;

    // 스트리밍 중이면 query 모드로 복귀 (응답 없을 수 있음)
    await this.sendCommand("ENDSTREAM", undefined, { optionalReply: true });

    const pattern = buildMatchPattern(channels);
    const patternBytes = new TextEncoder().encode(pattern);
    const matchResp = await this.sendCommand("MATCH", patternBytes);
    if (/^ERROR/i.test(matchResp)) {
      throw new Error(`MATCH 실패: ${matchResp}`);
    }

    // Duration 창만큼 과거부터 (hptime = epoch microseconds)
    const hpAfter = Math.floor((Date.now() - this.durationSec * 1000) * 1000);
    try {
      await this.sendCommand(`POSITION AFTER ${hpAfter}`);
    } catch {
      try {
        await this.sendCommand("POSITION SET EARLIEST");
      } catch {
        /* optional */
      }
    }

    // STREAM은 OK 없이 바로 PACKET을 보내는 서버가 많음 → 응답 대기하지 않음
    this.sendRaw("STREAM");
    this.onStatus?.(
      "streaming",
      `DataLink ${channels.map(scnlKey).join(", ")}`,
    );
  }

  private sendRaw(cmd: string, data?: Uint8Array) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error("ws closed");
    }
    this.ws.send(encodeDL(cmd, data));
  }

  private sendCommand(
    cmd: string,
    data?: Uint8Array,
    opts?: { optionalReply?: boolean; timeoutMs?: number },
  ): Promise<string> {
    return new Promise((resolve, reject) => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
        reject(new Error("ws closed"));
        return;
      }
      if (this.pending) {
        reject(new Error("another command in flight"));
        return;
      }
      const optional = !!opts?.optionalReply || cmd.startsWith("ENDSTREAM");
      const timeoutMs = opts?.timeoutMs ?? (optional ? 1500 : 8000);
      const timer = window.setTimeout(() => {
        this.pending = null;
        if (optional) resolve("OK");
        else reject(new Error(`DataLink timeout: ${cmd}`));
      }, timeoutMs);

      this.pending = {
        resolve: (v) => {
          window.clearTimeout(timer);
          this.pending = null;
          resolve(v);
        },
        reject: (e) => {
          window.clearTimeout(timer);
          this.pending = null;
          reject(e);
        },
      };

      this.sendRaw(cmd, data);
    });
  }

  private handleMessage(ev: MessageEvent) {
    if (typeof ev.data === "string") {
      this.handleText(ev.data);
      return;
    }
    if (!(ev.data instanceof ArrayBuffer)) return;

    const buf = ev.data;
    const u8 = new Uint8Array(buf);

    // DL envelope
    if (u8[0] === 0x44 && u8[1] === 0x4c && u8.length > 3) {
      const hdrLen = u8[2]!;
      const header = new TextDecoder().decode(u8.subarray(3, 3 + hdrLen));
      const dataStart = 3 + hdrLen;

      if (header.startsWith("PACKET")) {
        // STREAM 직후 OK 없이 PACKET이 오면 대기를 성공으로 종료
        if (this.pending) this.pending.resolve("OK");
        const parts = header.trim().split(/\s+/);
        const sizeTok = parts[parts.length - 1];
        const size = Number(sizeTok);
        if (Number.isFinite(size) && size > 0 && dataStart + size <= buf.byteLength) {
          this.emitMiniseed(buf.slice(dataStart, dataStart + size));
        } else if (dataStart < buf.byteLength) {
          this.emitMiniseed(buf.slice(dataStart));
        }
        return;
      }

      if (this.pending) {
        if (/^ERROR/i.test(header)) this.pending.reject(new Error(header));
        else this.pending.resolve(header);
      }
      return;
    }

    // ringserver may send response without re-wrapping (rare) or raw mseed
    if (buf.byteLength < 512 && this.looksLikeAscii(u8)) {
      this.handleText(new TextDecoder().decode(buf));
      return;
    }
    if (this.pending) this.pending.resolve("OK");
    this.emitMiniseed(buf);
  }

  private looksLikeAscii(u8: Uint8Array): boolean {
    if (u8.length === 0) return false;
    for (let i = 0; i < Math.min(u8.length, 80); i++) {
      const c = u8[i]!;
      if (c === 9 || c === 10 || c === 13) continue;
      if (c < 32 || c > 126) return false;
    }
    return true;
  }

  private handleText(text: string) {
    const cleaned = text.replace(/\0/g, "").trim();
    if (!cleaned || !this.pending) return;
    if (/^ERROR/i.test(cleaned)) this.pending.reject(new Error(cleaned));
    else this.pending.resolve(cleaned);
  }

  private emitMiniseed(buf: ArrayBuffer) {
    let records: miniseed.DataRecord[] = [];
    try {
      records = miniseed.parseDataRecords(buf);
    } catch {
      try {
        records = [miniseed.parseSingleDataRecord(new DataView(buf))];
      } catch {
        return;
      }
    }
    for (const rec of records) {
      const samplesRaw = rec.decompress();
      const samples = new Float32Array(samplesRaw.length);
      for (let i = 0; i < samplesRaw.length; i++) samples[i] = Number(samplesRaw[i]);
      const scnl: SCNL = {
        network: rec.header.netCode.trim(),
        station: rec.header.staCode.trim(),
        location: (rec.header.locCode || "").trim() || "--",
        channel: rec.header.chanCode.trim(),
      };
      if (this.channels.length) {
        const ok = this.channels.some(
          (c) =>
            c.network === scnl.network &&
            c.station === scnl.station &&
            c.channel === scnl.channel,
        );
        if (!ok) continue;
      }
      this.onPacket?.(
        scnl,
        samples,
        rec.header.startTime.toMillis(),
        rec.header.sampleRate || 100,
      );
    }
  }
}
