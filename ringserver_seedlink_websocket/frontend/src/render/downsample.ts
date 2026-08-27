/** One Y per X column — avoids leftover vertices that spike to the edge. */
export function columnDownsample(
  samples: Float32Array,
  outY: Float32Array,
  outX: Float32Array,
  widthPoints: number,
): number {
  const n = samples.length;
  if (n === 0 || widthPoints <= 0) return 0;
  if (n === 1) {
    outX[0] = 0;
    outY[0] = samples[0]!;
    return 1;
  }
  const cols = Math.min(widthPoints, Math.max(1, n));
  for (let c = 0; c < cols; c++) {
    const start = Math.floor((c / cols) * n);
    const end = Math.max(start + 1, Math.floor(((c + 1) / cols) * n));
    let min = Infinity;
    let max = -Infinity;
    for (let i = start; i < end; i++) {
      const v = samples[i]!;
      if (v < min) min = v;
      if (v > max) max = v;
    }
    // peak-preserving mid of envelope (stable, no unused verts)
    outY[c] = (min + max) / 2;
    outX[c] = cols === 1 ? 0 : c / (cols - 1);
  }
  return cols;
}

/** Min/max envelope: 2 points per column. out length must be >= widthPoints*2. */
export function minMaxDownsample(
  samples: Float32Array,
  outY: Float32Array,
  outX: Float32Array,
  widthPoints: number,
): number {
  const n = samples.length;
  if (n === 0 || widthPoints <= 0) return 0;
  const maxOut = Math.floor(outX.length);
  const buckets = Math.min(Math.floor(widthPoints / 2), n);
  if (buckets <= 0) return 0;
  if (n <= buckets) {
    for (let i = 0; i < n; i++) {
      outX[i] = i / Math.max(1, n - 1);
      outY[i] = samples[i]!;
    }
    return n;
  }
  const bucketSize = n / buckets;
  let o = 0;
  for (let b = 0; b < buckets && o < maxOut; b++) {
    const start = Math.floor(b * bucketSize);
    const end = Math.min(n, Math.floor((b + 1) * bucketSize));
    let min = Infinity;
    let max = -Infinity;
    let minI = start;
    let maxI = start;
    for (let i = start; i < end; i++) {
      const v = samples[i]!;
      if (v < min) {
        min = v;
        minI = i;
      }
      if (v > max) {
        max = v;
        maxI = i;
      }
    }
    const firstI = minI <= maxI ? minI : maxI;
    const firstV = minI <= maxI ? min : max;
    const secondI = minI <= maxI ? maxI : minI;
    const secondV = minI <= maxI ? max : min;
    outX[o] = firstI / (n - 1);
    outY[o] = firstV;
    o++;
    if (o < maxOut && secondI !== firstI) {
      outX[o] = secondI / (n - 1);
      outY[o] = secondV;
      o++;
    }
  }
  return o;
}

/**
 * 시간축에 맞춘 min/max 다운샘플.
 * outX는 창 [windowStart, windowEnd] 기준 0..1.
 * 데이터가 없는 버킷은 건너뛴다(호출측에서 빈 구간을 채움).
 */
export function minMaxDownsampleTimed(
  samples: Float32Array,
  sampleStartMs: number,
  sampleRate: number,
  windowStartMs: number,
  windowEndMs: number,
  outY: Float32Array,
  outX: Float32Array,
  widthPoints: number,
): number {
  const n = samples.length;
  const duration = windowEndMs - windowStartMs;
  if (n === 0 || widthPoints <= 0 || duration <= 0 || sampleRate <= 0) return 0;

  const maxOut = Math.floor(outX.length);
  const buckets = Math.max(1, Math.min(Math.floor(widthPoints / 2), n));
  let o = 0;

  for (let b = 0; b < buckets && o < maxOut; b++) {
    const t0 = windowStartMs + (b / buckets) * duration;
    const t1 = windowStartMs + ((b + 1) / buckets) * duration;
    let i0 = Math.floor(((t0 - sampleStartMs) * sampleRate) / 1000);
    let i1 = Math.ceil(((t1 - sampleStartMs) * sampleRate) / 1000);
    i0 = Math.max(0, Math.min(n, i0));
    i1 = Math.max(0, Math.min(n, i1));
    if (i0 >= i1) continue;

    let min = Infinity;
    let max = -Infinity;
    let minI = i0;
    let maxI = i0;
    for (let i = i0; i < i1; i++) {
      const v = samples[i]!;
      if (v < min) {
        min = v;
        minI = i;
      }
      if (v > max) {
        max = v;
        maxI = i;
      }
    }
    if (!Number.isFinite(min) || !Number.isFinite(max)) continue;

    const pushAt = (sampleIndex: number, value: number) => {
      if (o >= maxOut) return;
      const t = sampleStartMs + (sampleIndex / sampleRate) * 1000;
      outX[o] = Math.max(0, Math.min(1, (t - windowStartMs) / duration));
      outY[o] = value;
      o++;
    };

    if (minI === maxI) {
      pushAt(minI, min);
    } else if (minI < maxI) {
      pushAt(minI, min);
      pushAt(maxI, max);
    } else {
      pushAt(maxI, max);
      pushAt(minI, min);
    }
  }
  return o;
}

export function hexToRgba(hex: string, a = 1): { r: number; g: number; b: number; a: number } {
  const h = hex.replace("#", "");
  const full = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
  const n = parseInt(full, 16);
  return {
    r: ((n >> 16) & 255) / 255,
    g: ((n >> 8) & 255) / 255,
    b: (n & 255) / 255,
    a,
  };
}
