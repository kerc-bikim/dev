import {
  interpolateViridis,
  interpolatePlasma,
  interpolateInferno,
  interpolateMagma,
  interpolateCividis,
  interpolateTurbo,
} from "d3-scale-chromatic";

type Interp = (t: number) => string;

const clamp01 = (v: number) => Math.max(0, Math.min(1, v));

/** matplotlib "hot" colormap: black -> red -> yellow -> white. */
function interpolateHot(t: number): string {
  const r = clamp01(t / 0.365079);
  const g = clamp01((t - 0.365079) / (0.746032 - 0.365079));
  const b = clamp01((t - 0.746032) / (1 - 0.746032));
  return `rgb(${Math.round(r * 255)},${Math.round(g * 255)},${Math.round(
    b * 255
  )})`;
}

/** Classic MATLAB/matplotlib "jet" colormap (blue -> cyan -> yellow -> red). */
function interpolateJet(t: number): string {
  const r = clamp01(Math.min(4 * t - 1.5, -4 * t + 4.5));
  const g = clamp01(Math.min(4 * t - 0.5, -4 * t + 3.5));
  const b = clamp01(Math.min(4 * t + 0.5, -4 * t + 2.5));
  return `rgb(${Math.round(r * 255)},${Math.round(g * 255)},${Math.round(
    b * 255
  )})`;
}

/**
 * ObsPy / PQLX PPSD colormap (`obspy.imaging.cm.pqlx`).
 * Sampled from ObsPy's pqlx.npz (white → magenta → blue → cyan → green → yellow → red).
 */
const PQLX_STOPS: ReadonlyArray<readonly [number, number, number]> = [
  [255, 255, 255],
  [255, 175, 255],
  [255, 95, 255],
  [255, 15, 255],
  [233, 0, 255],
  [207, 0, 255],
  [180, 0, 255],
  [153, 0, 255],
  [127, 0, 255],
  [100, 0, 255],
  [73, 0, 255],
  [47, 0, 255],
  [20, 0, 255],
  [0, 5, 255],
  [0, 25, 255],
  [0, 45, 255],
  [0, 65, 255],
  [0, 85, 255],
  [0, 105, 255],
  [0, 125, 255],
  [0, 145, 255],
  [0, 165, 255],
  [0, 185, 255],
  [0, 205, 255],
  [0, 225, 255],
  [0, 245, 255],
  [0, 255, 245],
  [0, 255, 225],
  [0, 255, 205],
  [0, 255, 185],
  [0, 255, 165],
  [0, 255, 145],
  [0, 255, 125],
  [0, 255, 105],
  [0, 255, 85],
  [0, 255, 65],
  [0, 255, 45],
  [0, 255, 25],
  [0, 255, 5],
  [15, 255, 0],
  [35, 255, 0],
  [55, 255, 0],
  [75, 255, 0],
  [95, 255, 0],
  [115, 255, 0],
  [135, 255, 0],
  [155, 255, 0],
  [175, 255, 0],
  [195, 255, 0],
  [215, 255, 0],
  [235, 255, 0],
  [255, 255, 0],
  [255, 235, 0],
  [255, 215, 0],
  [255, 195, 0],
  [255, 175, 0],
  [255, 155, 0],
  [255, 135, 0],
  [255, 115, 0],
  [255, 95, 0],
  [255, 75, 0],
  [255, 55, 0],
  [255, 35, 0],
  [255, 15, 0],
  [255, 0, 0],
];

function interpolatePqlx(t: number): string {
  const x = clamp01(t) * (PQLX_STOPS.length - 1);
  const i0 = Math.floor(x);
  const i1 = Math.min(PQLX_STOPS.length - 1, i0 + 1);
  const f = x - i0;
  const c0 = PQLX_STOPS[i0];
  const c1 = PQLX_STOPS[i1];
  const r = Math.round(c0[0] + (c1[0] - c0[0]) * f);
  const g = Math.round(c0[1] + (c1[1] - c0[1]) * f);
  const b = Math.round(c0[2] + (c1[2] - c0[2]) * f);
  return `rgb(${r},${g},${b})`;
}

const INTERPOLATORS: Record<string, Interp> = {
  viridis: interpolateViridis,
  plasma: interpolatePlasma,
  inferno: interpolateInferno,
  magma: interpolateMagma,
  cividis: interpolateCividis,
  turbo: interpolateTurbo,
  hot: interpolateHot,
  jet: interpolateJet,
  pqlx: interpolatePqlx,
  gray: (t: number) => {
    const v = Math.round(255 * (1 - t));
    return `rgb(${v},${v},${v})`;
  },
  grey: (t: number) => {
    const v = Math.round(255 * (1 - t));
    return `rgb(${v},${v},${v})`;
  },
};

const LUT_SIZE = 256;

function parseRgb(s: string): [number, number, number] {
  const m = s.match(/rgba?\(([^)]+)\)/i);
  if (m) {
    const parts = m[1].split(",").map((v) => parseFloat(v));
    return [parts[0], parts[1], parts[2]];
  }
  if (s.startsWith("#")) {
    const hex = s.slice(1);
    return [
      parseInt(hex.slice(0, 2), 16),
      parseInt(hex.slice(2, 4), 16),
      parseInt(hex.slice(4, 6), 16),
    ];
  }
  return [0, 0, 0];
}

/**
 * Build a 256 x 3 float LUT (0..1 per channel) for the given matplotlib-style
 * colormap name. Falls back to viridis for unknown names.
 */
export function buildColormapLut(name: string): Float32Array {
  const interp = INTERPOLATORS[name?.toLowerCase()] ?? interpolateViridis;
  const lut = new Float32Array(LUT_SIZE * 3);
  for (let i = 0; i < LUT_SIZE; i++) {
    const t = i / (LUT_SIZE - 1);
    const [r, g, b] = parseRgb(interp(t));
    lut[i * 3 + 0] = r / 255;
    lut[i * 3 + 1] = g / 255;
    lut[i * 3 + 2] = b / 255;
  }
  return lut;
}

/** Sample a color string "rgb(r,g,b)" from a LUT at normalized t (0..1). */
export function sampleLut(lut: Float32Array, t: number): string {
  const clamped = Math.max(0, Math.min(1, t));
  const idx = Math.round(clamped * (LUT_SIZE - 1));
  const r = Math.round(lut[idx * 3 + 0] * 255);
  const g = Math.round(lut[idx * 3 + 1] * 255);
  const b = Math.round(lut[idx * 3 + 2] * 255);
  return `rgb(${r},${g},${b})`;
}

export const COLORMAP_LUT_SIZE = LUT_SIZE;
