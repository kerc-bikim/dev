/** 상태바 타임윈도우(초) 프리셋 — 줌인/줌아웃 간격 */
export const TIME_WINDOW_STEPS = [
  15, 30, 60, 120, 180, 240, 300, 600, 900, 1200, 1800, 3600, 7200,
] as const;

export type TimeWindowSec = (typeof TIME_WINDOW_STEPS)[number];

export function formatTimeWindow(sec: number): string {
  if (sec < 60) return `${sec}s`;
  if (sec % 3600 === 0) return `${sec / 3600}h`;
  if (sec % 60 === 0) return `${sec / 60}m`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return s ? `${m}m${s}s` : `${m}m`;
}

export function formatTimeWindowLabel(sec: number): string {
  if (sec < 60) return `${sec}초`;
  if (sec < 3600) return `${sec / 60}분`;
  return `${sec / 3600}시간`;
}

/** 현재 값에 가장 가까운 스텝 인덱스 */
export function nearestTimeWindowIndex(sec: number): number {
  let best = 0;
  let bestDist = Infinity;
  for (let i = 0; i < TIME_WINDOW_STEPS.length; i++) {
    const d = Math.abs(TIME_WINDOW_STEPS[i]! - sec);
    if (d < bestDist) {
      bestDist = d;
      best = i;
    }
  }
  return best;
}

/** 줌아웃 = 더 긴 창, 줌인 = 더 짧은 창 */
export function stepTimeWindow(
  currentSec: number,
  direction: "in" | "out",
): number {
  const idx = nearestTimeWindowIndex(currentSec);
  const exact = TIME_WINDOW_STEPS[idx] === currentSec;
  if (direction === "out") {
    if (!exact && currentSec < TIME_WINDOW_STEPS[idx]!) {
      return TIME_WINDOW_STEPS[idx]!;
    }
    return TIME_WINDOW_STEPS[Math.min(TIME_WINDOW_STEPS.length - 1, idx + 1)]!;
  }
  if (!exact && currentSec > TIME_WINDOW_STEPS[idx]!) {
    return TIME_WINDOW_STEPS[idx]!;
  }
  return TIME_WINDOW_STEPS[Math.max(0, idx - 1)]!;
}

/** 창 길이에 맞는 주요 눈금 간격(초) — 대략 4~8개 */
const TICK_CANDIDATES_SEC = [
  1, 2, 5, 10, 15, 30, 60, 120, 180, 300, 600, 900, 1200, 1800, 3600, 7200,
] as const;

export function chooseTimeTickSec(durationSec: number): number {
  const d = Math.max(1, durationSec);
  const target = d / 6;
  let best: number = TICK_CANDIDATES_SEC[0]!;
  let bestScore = Infinity;
  for (const c of TICK_CANDIDATES_SEC) {
    const n = d / c;
    if (n < 3 || n > 12) {
      const score = Math.abs(c - target) + (n < 3 ? 1e6 : 0) + (n > 12 ? 1e6 : 0);
      if (score < bestScore) {
        bestScore = score;
        best = c;
      }
      continue;
    }
    const score = Math.abs(c - target);
    if (score < bestScore) {
      bestScore = score;
      best = c;
    }
  }
  return best;
}

export type TimeAxisTick = {
  /** 0..1 (왼쪽→오른쪽) */
  x: number;
  ms: number;
  label: string;
  /** 양끝(시작/끝) 라벨과 겹치면 숨김 */
  edge: boolean;
};

/**
 * [windowStart, windowEnd] 구간의 X축 눈금.
 * 벽시계 기준으로 tickSec 배수에 정렬.
 */
export function buildTimeAxisTicks(
  windowStartMs: number,
  windowEndMs: number,
  durationSec: number,
): TimeAxisTick[] {
  const span = Math.max(1, windowEndMs - windowStartMs);
  const tickSec = chooseTimeTickSec(durationSec);
  const tickMs = tickSec * 1000;
  const first = Math.ceil(windowStartMs / tickMs) * tickMs;
  const ticks: TimeAxisTick[] = [];

  for (let t = first; t <= windowEndMs + 0.5; t += tickMs) {
    if (t < windowStartMs - 0.5) continue;
    const x = (t - windowStartMs) / span;
    if (x < -0.001 || x > 1.001) continue;
    const edge = x < 0.04 || x > 0.96;
    ticks.push({
      x: Math.max(0, Math.min(1, x)),
      ms: t,
      label: formatTickLabel(t, tickSec),
      edge,
    });
  }

  // 눈금이 너무 적으면 균등 분할
  if (ticks.length < 2) {
    const n = Math.max(2, Math.round(durationSec / tickSec));
    for (let i = 0; i <= n; i++) {
      const x = i / n;
      const ms = windowStartMs + x * span;
      ticks.push({
        x,
        ms,
        label: formatTickLabel(ms, tickSec),
        edge: i === 0 || i === n,
      });
    }
  }

  return ticks;
}

function formatTickLabel(ms: number, tickSec: number): string {
  const d = new Date(ms);
  const pad = (n: number) => String(n).padStart(2, "0");
  const hh = pad(d.getHours());
  const mm = pad(d.getMinutes());
  const ss = pad(d.getSeconds());
  if (tickSec >= 3600) return `${hh}:${mm}`;
  if (tickSec >= 60) return `${hh}:${mm}`;
  return `${hh}:${mm}:${ss}`;
}
