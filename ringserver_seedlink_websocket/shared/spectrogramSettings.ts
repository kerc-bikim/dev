export type SpectrogramHopDivisor = 2 | 4 | 8;

export type SpectrogramSettings = {
  /** STFT 창 길이(초). 길수록 주파수 해상도 ↑ */
  windowSec: number;
  /** nFFT 상한 (2의 거듭제곱) */
  nfftMax: number;
  /** 시간 축 최대 열 수 */
  maxFrames: number;
  /** hop = nfft / hopDivisor → 2=50%, 4=75%, 8=87.5% 겹침 */
  hopDivisor: SpectrogramHopDivisor;
};

/** 다중 스트림 성능과 선명도의 타협값 */
export const DEFAULT_SPECTROGRAM: SpectrogramSettings = {
  windowSec: 2,
  nfftMax: 512,
  maxFrames: 320,
  hopDivisor: 4,
};

export const SPECTROGRAM_NFFT_OPTIONS = [128, 256, 512, 1024] as const;
export const SPECTROGRAM_WINDOW_SEC_OPTIONS = [1, 2, 4] as const;
export const SPECTROGRAM_HOP_OPTIONS: { value: SpectrogramHopDivisor; label: string }[] = [
  { value: 2, label: "50%" },
  { value: 4, label: "75%" },
  { value: 8, label: "87.5%" },
];

function clampNum(n: number, min: number, max: number, fallback: number): number {
  if (!Number.isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, n));
}

function nearestPow2(n: number, min: number, max: number, fallback: number): number {
  if (!Number.isFinite(n) || n <= 0) return fallback;
  let p = 1;
  while (p < n) p <<= 1;
  const lo = p >> 1;
  const pick = n - lo < p - n && lo >= min ? lo : p;
  return Math.min(max, Math.max(min, pick));
}

export function sanitizeSpectrogramSettings(raw: unknown): SpectrogramSettings {
  const d = DEFAULT_SPECTROGRAM;
  const o = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const hopRaw = Number(o.hopDivisor);
  const hopDivisor: SpectrogramHopDivisor =
    hopRaw === 2 || hopRaw === 4 || hopRaw === 8 ? hopRaw : d.hopDivisor;
  return {
    windowSec: clampNum(Number(o.windowSec), 1, 8, d.windowSec),
    nfftMax: nearestPow2(Number(o.nfftMax), 128, 1024, d.nfftMax),
    maxFrames: Math.round(clampNum(Number(o.maxFrames), 64, 1024, d.maxFrames)),
    hopDivisor,
  };
}
