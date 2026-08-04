import type { SCNL, ConnectionStatus } from "../types";
import { scnlKey } from "../types";
import type { RealtimeClient } from "./types";
import { DataLinkClient } from "./datalinkClient";
import { bufferStore } from "../buffer/ringBuffer";

export type ReconnectCallbacks = {
  onStatus: (status: ConnectionStatus, detail?: string) => void;
  onPacket: (
    scnl: SCNL,
    samples: Float32Array,
    startMs: number,
    sampleRate: number,
  ) => void;
};

function sameChannelSet(a: SCNL[], b: SCNL[]): boolean {
  if (a.length !== b.length) return false;
  const keys = new Set(a.map(scnlKey));
  return b.every((c) => keys.has(scnlKey(c)));
}

/** Ringserver DataLink WebSocket 전용 재접속 컨트롤러 */
export class ReconnectController {
  private client: RealtimeClient | null = null;
  private channels: SCNL[] = [];
  private intentional = false;
  private attempt = 0;
  private timer: number | null = null;
  private cbs: ReconnectCallbacks;
  private durationSec = 300;
  private ringserverUrl: string | null = null;

  constructor(cbs: ReconnectCallbacks) {
    this.cbs = cbs;
    window.addEventListener("online", this.onOnline);
  }

  dispose() {
    window.removeEventListener("online", this.onOnline);
    this.stop(true);
  }

  private onOnline = () => {
    if (!this.intentional && this.channels.length) {
      void this.manualReconnect();
    }
  };

  setDuration(sec: number) {
    this.durationSec = sec;
    this.client?.setDuration?.(sec);
  }

  setRingserverUrl(url: string | null) {
    this.ringserverUrl = url;
  }

  getChannels() {
    return this.channels;
  }

  isConnected() {
    return !!this.client?.isOpen();
  }

  /**
   * DataLink 표출 시작. 세션이 열려 있으면 WebSocket을 유지한 채 구독만 갱신.
   */
  async start(channels: SCNL[], opts?: { forceNew?: boolean }) {
    this.intentional = false;
    this.attempt = 0;

    const canReuse =
      !opts?.forceNew && this.client != null && this.client.isOpen();

    this.channels = channels;

    if (canReuse) {
      this.client!.setDuration?.(this.durationSec);
      await this.resubscribe(channels, /* resetBuffers */ true);
      return;
    }

    await this.connectOnce();
  }

  stop(intentional = true) {
    this.intentional = intentional;
    if (this.timer != null) {
      window.clearTimeout(this.timer);
      this.timer = null;
    }
    this.client?.disconnect(intentional);
    this.client = null;
    if (intentional) this.cbs.onStatus("disconnected", "연결 중지");
  }

  async manualReconnect() {
    this.intentional = false;
    this.attempt = 0;
    if (this.timer != null) {
      window.clearTimeout(this.timer);
      this.timer = null;
    }
    await this.connectOnce();
  }

  async updateChannels(channels: SCNL[]) {
    if (sameChannelSet(this.channels, channels) && this.client?.isOpen()) {
      this.channels = channels;
      return;
    }
    this.channels = channels;
    if (!this.client?.isOpen()) {
      if (channels.length) await this.connectOnce();
      return;
    }
    await this.resubscribe(channels, /* resetBuffers */ false);
  }

  private async resubscribe(channels: SCNL[], resetBuffers: boolean) {
    if (!this.client) return;
    this.cbs.onStatus("connecting", "구독 갱신 중");
    if (resetBuffers) {
      for (const c of channels) {
        bufferStore.remove(scnlKey(c));
        bufferStore.getOrCreate(c).ensureCapacity(this.durationSec);
      }
    } else {
      for (const c of channels) {
        bufferStore.getOrCreate(c).ensureCapacity(this.durationSec);
      }
    }
    try {
      await this.client.subscribe(channels);
      this.attempt = 0;
      this.cbs.onStatus("connected", "실시간 수신 중");
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (this.client?.isOpen()) {
        this.attempt = 0;
        this.cbs.onStatus("connected", "실시간 수신 중");
        console.warn("subscribe warning (session kept):", msg);
        return;
      }
      this.cbs.onStatus("error", msg);
      if (!this.intentional) await this.connectOnce();
    }
  }

  private createClient(): RealtimeClient {
    return new DataLinkClient(this.ringserverUrl, this.durationSec);
  }

  private wireClient(client: RealtimeClient) {
    client.onPacket = (scnl, samples, startMs, sr) => {
      const buf = bufferStore.getOrCreate(scnl);
      buf.ensureCapacity(this.durationSec, sr);
      buf.append(samples, startMs, sr);
      this.cbs.onPacket(scnl, samples, startMs, sr);
    };
    client.onClose = () => {
      if (this.intentional) return;
      this.scheduleReconnect("연결이 끊어졌습니다");
    };
  }

  private async connectOnce() {
    this.client?.disconnect(true);
    this.client = this.createClient();
    this.wireClient(this.client);
    this.cbs.onStatus(
      this.attempt === 0 ? "connecting" : "reconnecting",
      `시도 #${this.attempt + 1}`,
    );
    try {
      await this.client.connect();
      for (const c of this.channels) {
        bufferStore.remove(scnlKey(c));
        bufferStore.getOrCreate(c).ensureCapacity(this.durationSec);
      }
      await this.client.subscribe(this.channels);
      this.attempt = 0;
      this.cbs.onStatus("connected", "실시간 수신 중");
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      this.cbs.onStatus("error", msg);
      if (!this.intentional) this.scheduleReconnect(msg);
    }
  }

  private scheduleReconnect(detail: string) {
    this.cbs.onStatus("reconnecting", detail);
    const delay = Math.min(30000, 1000 * 2 ** Math.min(this.attempt, 5));
    this.attempt += 1;
    if (this.timer != null) window.clearTimeout(this.timer);
    this.timer = window.setTimeout(() => {
      void this.connectOnce();
    }, delay);
  }
}
