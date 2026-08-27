import FFT from "fft.js";

/** samples.length 이하인 가장 큰 2의 거듭제곱 */
function floorPow2(n: number): number {
  if (n < 2) return 0;
  let p = 1;
  while (p <= n >> 1) p <<= 1;
  return p;
}

export function computeFftDb(
  samples: Float32Array,
  sampleRate: number,
): { freqs: Float32Array; db: Float32Array } {
  if (samples.length < 8 || sampleRate <= 0) {
    return { freqs: new Float32Array(0), db: new Float32Array(0) };
  }

  // fft.js는 크기가 2의 거듭제곱이어야 함 (이전: nextPow2 후 min → 1000 등 비2배수 발생)
  const n = floorPow2(samples.length);
  if (n < 8) {
    return { freqs: new Float32Array(0), db: new Float32Array(0) };
  }

  const start = samples.length - n;
  const fft = new FFT(n);
  const input = fft.createComplexArray();
  const output = fft.createComplexArray();
  // Hann
  for (let i = 0; i < n; i++) {
    const w = 0.5 * (1 - Math.cos((2 * Math.PI * i) / Math.max(1, n - 1)));
    input[i * 2] = samples[start + i]! * w;
    input[i * 2 + 1] = 0;
  }
  fft.transform(output, input);
  const half = n / 2;
  const freqs = new Float32Array(half);
  const db = new Float32Array(half);
  for (let i = 0; i < half; i++) {
    const re = output[i * 2]!;
    const im = output[i * 2 + 1]!;
    const mag = Math.sqrt(re * re + im * im) / n;
    freqs[i] = (i * sampleRate) / n;
    db[i] = 20 * Math.log10(mag + 1e-12);
  }
  return { freqs, db };
}
