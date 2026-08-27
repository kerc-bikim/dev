import type { GapInterval, SCNL, XAxisRightAnchor } from "../types";
import { scnlKey } from "../types";

const GAP_FACTOR = 1.5;

export type AlignedWindow = {
  samples: Float32Array;
  sampleStartMs: number;
  sampleRate: number;
  windowStartMs: number;
  windowEndMs: number;
};

export class ChannelRingBuffer {
  readonly key: string;
  readonly scnl: SCNL;
  sampleRate = 100;
  private capacity = 0;
  private data: Float32Array = new Float32Array(0);
  private write = 0;
  private count = 0;
  private lastEndMs = 0;
  gaps: GapInterval[] = [];
  sensitivity: number | null = null;
  inputUnits: string | null = null;

  constructor(scnl: SCNL) {
    this.scnl = scnl;
    this.key = scnlKey(scnl);
  }

  ensureCapacity(durationSec: number, sampleRate?: number) {
    if (sampleRate && sampleRate > 0) this.sampleRate = sampleRate;
    const next = Math.max(64, Math.ceil(durationSec * this.sampleRate * 1.05));
    if (next <= this.capacity && this.capacity > 0) return;
    const prev = this.copyRecent(this.count);
    this.capacity = next;
    this.data = new Float32Array(this.capacity);
    this.write = 0;
    this.count = 0;
    if (prev.samples.length) {
      this.appendRaw(prev.samples, prev.startMs, this.sampleRate);
    }
  }

  private appendRaw(samples: ArrayLike<number>, startMs: number, sampleRate: number) {
    if (this.capacity === 0) this.ensureCapacity(300, sampleRate);
    for (let i = 0; i < samples.length; i++) {
      this.data[this.write] = samples[i]!;
      this.write = (this.write + 1) % this.capacity;
      if (this.count < this.capacity) this.count++;
    }
    this.lastEndMs = startMs + (samples.length / sampleRate) * 1000;
  }

  append(samples: ArrayLike<number>, startMs: number, sampleRate: number) {
    if (!samples.length) return;
    if (sampleRate > 0) this.sampleRate = sampleRate;
    if (this.capacity === 0) this.ensureCapacity(300, sampleRate);

    const endMs = startMs + (samples.length / sampleRate) * 1000;
    if (this.count > 0 && this.lastEndMs > 0) {
      const expected = 1000 / sampleRate;
      const delta = startMs - this.lastEndMs;
      if (delta > expected * GAP_FACTOR) {
        this.gaps.push({ startMs: this.lastEndMs, endMs: startMs });
        if (this.gaps.length > 200) this.gaps.splice(0, this.gaps.length - 200);
      }
    }

    for (let i = 0; i < samples.length; i++) {
      this.data[this.write] = samples[i]!;
      this.write = (this.write + 1) % this.capacity;
      if (this.count < this.capacity) this.count++;
    }
    this.lastEndMs = endMs;
    const winStart = this.lastEndMs - (this.count / sampleRate) * 1000;
    this.gaps = this.gaps.filter((g) => g.endMs >= winStart);
  }

  copyRecent(nSamples: number): { samples: Float32Array; startMs: number } {
    if (this.count === 0 || nSamples <= 0) {
      return { samples: new Float32Array(0), startMs: 0 };
    }
    const need = Math.min(this.count, nSamples);
    const out = new Float32Array(need);
    const startIdx = (this.write - need + this.capacity * 4) % this.capacity;
    for (let i = 0; i < need; i++) {
      out[i] = this.data[(startIdx + i) % this.capacity]!;
    }
    const startMs = this.lastEndMs - (need / this.sampleRate) * 1000;
    return { samples: out, startMs };
  }

  copyWindow(durationSec: number): { samples: Float32Array; startMs: number } {
    return this.copyRecent(Math.ceil(durationSec * this.sampleRate));
  }

  /**
   * [windowEnd - duration, windowEnd] 구간에 맞춰 샘플을 자른다.
   * X축 오른쪽 기준(현재시각 / 마지막 데이터)에 사용.
   * 줌으로 과거 구간을 볼 때도 해당 시각 샘플을 포함하도록,
   * lastEnd 기준이 아니라 windowStart까지 거슬러 올라간다.
   */
  copyAlignedWindow(windowEndMs: number, durationSec: number): AlignedWindow {
    const windowStartMs = windowEndMs - Math.max(0.001, durationSec) * 1000;
    const empty: AlignedWindow = {
      samples: new Float32Array(0),
      sampleStartMs: windowStartMs,
      sampleRate: this.sampleRate,
      windowStartMs,
      windowEndMs,
    };
    if (this.count === 0 || !this.lastEndMs) return empty;

    // 버퍼 끝(lastEndMs)에서 windowStart까지 필요한 샘플 수.
    // 줌인 시 window가 lastEnd보다 과거에 있으면 durationSec만으로는 부족하다.
    const lookbackSec = Math.max(
      durationSec,
      (this.lastEndMs - windowStartMs) / 1000,
    );
    const need = Math.min(
      this.count,
      Math.ceil(lookbackSec * this.sampleRate) + Math.ceil(this.sampleRate * 2),
    );
    const recent = this.copyRecent(need);
    if (!recent.samples.length) return empty;

    const sr = this.sampleRate;
    const i0 = Math.max(
      0,
      Math.floor(((windowStartMs - recent.startMs) * sr) / 1000),
    );
    const i1 = Math.min(
      recent.samples.length,
      Math.ceil(((windowEndMs - recent.startMs) * sr) / 1000),
    );
    if (i0 >= i1) return empty;

    const samples = recent.samples.slice(i0, i1);
    const sampleStartMs = recent.startMs + (i0 / sr) * 1000;
    return {
      samples,
      sampleStartMs,
      sampleRate: sr,
      windowStartMs,
      windowEndMs,
    };
  }

  gapsInWindow(durationSec: number, windowEndMs?: number): GapInterval[] {
    const end = windowEndMs ?? this.lastEndMs;
    if (!end) return [];
    const start = end - durationSec * 1000;
    return this.gaps.filter((g) => g.endMs > start && g.startMs < end);
  }

  get endMs() {
    return this.lastEndMs;
  }
}

export class BufferStore {
  private map = new Map<string, ChannelRingBuffer>();

  getOrCreate(scnl: SCNL): ChannelRingBuffer {
    const key = scnlKey(scnl);
    let buf = this.map.get(key);
    if (!buf) {
      buf = new ChannelRingBuffer(scnl);
      this.map.set(key, buf);
    }
    return buf;
  }

  get(key: string) {
    return this.map.get(key);
  }

  remove(key: string) {
    this.map.delete(key);
  }

  clear() {
    this.map.clear();
  }

  keys() {
    return [...this.map.keys()];
  }
}

export const bufferStore = new BufferStore();

/** 패널들의 X축 오른쪽(끝) 시각 */
export function resolveWindowEndMs(
  anchor: XAxisRightAnchor,
  panels: { scnl: SCNL }[],
): number {
  if (anchor === "now") return Date.now();
  let end = 0;
  for (const p of panels) {
    const buf = bufferStore.get(scnlKey(p.scnl));
    if (buf?.endMs) end = Math.max(end, buf.endMs);
  }
  return end || Date.now();
}
