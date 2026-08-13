import type { WaveformColors } from "../types";

export const THEME_IDS = ["default", "claude", "candyland"] as const;
export const THEME_MODES = ["light", "dark"] as const;

export type ThemeId = (typeof THEME_IDS)[number];
export type ThemeMode = (typeof THEME_MODES)[number];

export const DEFAULT_THEME: ThemeId = "default";
export const DEFAULT_THEME_MODE: ThemeMode = "light";
export const THEME_STORAGE_KEY = "ringwave-theme";
export const THEME_MODE_STORAGE_KEY = "ringwave-theme-mode";

export const THEME_OPTIONS: {
  id: ThemeId;
  name: string;
  swatches: Record<ThemeMode, [string, string, string]>;
}[] = [
  {
    id: "default",
    name: "Default",
    swatches: {
      light: ["oklch(1 0 0)", "oklch(0.205 0 0)", "oklch(0.488 0.243 264.376)"],
      dark: ["oklch(0.145 0 0)", "oklch(0.922 0 0)", "oklch(0.488 0.243 264.376)"],
    },
  },
  {
    id: "claude",
    name: "Claude",
    swatches: {
      light: ["oklch(0.98 0.01 95.1)", "oklch(0.62 0.14 39.04)", "oklch(0.69 0.16 290.41)"],
      dark: ["oklch(0.27 0 106.64)", "oklch(0.67 0.13 38.76)", "oklch(0.69 0.16 290.41)"],
    },
  },
  {
    id: "candyland",
    name: "Candyland",
    swatches: {
      light: ["oklch(0.98 0 228.78)", "oklch(0.87 0.07 7.09)", "oklch(0.97 0.21 109.77)"],
      dark: ["oklch(0.23 0.01 264.29)", "oklch(0.8 0.14 349.23)", "oklch(0.74 0.23 142.85)"],
    },
  },
];

export function isThemeId(value: unknown): value is ThemeId {
  return typeof value === "string" && (THEME_IDS as readonly string[]).includes(value);
}

export function parseThemeId(value: unknown): ThemeId {
  // Amethyst Haze를 사용하던 브라우저는 교체된 Claude 테마로 마이그레이션한다.
  if (value === "amethyst-haze") return "claude";
  if (value === "supabase") return "candyland";
  return isThemeId(value) ? value : DEFAULT_THEME;
}

export function parseThemeMode(value: unknown): ThemeMode {
  return typeof value === "string" && (THEME_MODES as readonly string[]).includes(value)
    ? (value as ThemeMode)
    : DEFAULT_THEME_MODE;
}

export function readStoredTheme(): ThemeId {
  try {
    return parseThemeId(window.localStorage.getItem(THEME_STORAGE_KEY));
  } catch {
    return DEFAULT_THEME;
  }
}

export function persistTheme(theme: ThemeId) {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    /* ignore quota / private mode */
  }
}

export function readStoredThemeMode(): ThemeMode {
  try {
    return parseThemeMode(window.localStorage.getItem(THEME_MODE_STORAGE_KEY));
  } catch {
    return DEFAULT_THEME_MODE;
  }
}

export function persistThemeMode(mode: ThemeMode) {
  try {
    window.localStorage.setItem(THEME_MODE_STORAGE_KEY, mode);
  } catch {
    /* ignore quota / private mode */
  }
}

export function applyThemeToDocument(theme: ThemeId, mode: ThemeMode = DEFAULT_THEME_MODE) {
  const root = document.documentElement;
  root.dataset.theme = theme;
  root.dataset.mode = mode;
  root.classList.toggle("dark", mode === "dark");
  root.style.colorScheme = mode;
}

export type ThemeCanvasColors = {
  plotBg: string;
  palette: string[];
  gapColor: string;
  selectionColor: string;
};

/** RingWave 기존 기본 캔버스/파형 색 — plotBg는 테마 --plot-bg 근사 fallback. */
export const DEFAULT_CANVAS_COLORS: ThemeCanvasColors = {
  plotBg: "#ffffff",
  palette: ["#2563eb", "#4338ca", "#0f766e", "#b45309", "#be185d"],
  gapColor: "#dc2626",
  selectionColor: "#737373",
};

const LIGHT_CANVAS_COLORS: Record<ThemeId, ThemeCanvasColors> = {
  default: DEFAULT_CANVAS_COLORS,
  claude: {
    plotBg: "#faf9f5",
    palette: ["#b45332", "#7c3aed", "#0f766e", "#a16207", "#2563eb"],
    gapColor: "#292724",
    selectionColor: "#5577c7",
  },
  candyland: {
    plotBg: "#f8fafc",
    palette: ["#db2777", "#0284c7", "#65a30d", "#c026d3", "#15803d"],
    gapColor: "#dc2626",
    selectionColor: "#f6a8b7",
  },
};

const DARK_CANVAS_COLORS: Record<ThemeId, ThemeCanvasColors> = {
  default: {
    plotBg: "#303030",
    palette: ["#38bdf8", "#60a5fa", "#5eead4", "#facc15", "#e879f9"],
    gapColor: "#ef4444",
    selectionColor: "#737373",
  },
  claude: {
    plotBg: "#3e3e3b",
    palette: ["#f08c62", "#c4a7e7", "#6fd6bd", "#e8c36a", "#7fb2f0"],
    gapColor: "#ef4444",
    selectionColor: "#5577c7",
  },
  candyland: {
    plotBg: "#34383e",
    palette: ["#df6ba5", "#22c55e", "#8ac9e8", "#e8f500", "#f4c542"],
    gapColor: "#ef4444",
    selectionColor: "#df6ba5",
  },
};

const RGB_COMMA_RE = /rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)/i;
const RGB_SPACE_RE = /rgba?\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)/i;

export function cssColorToHex(cssColor: string, fallback: string): string {
  const s = (cssColor || "").trim();
  if (/^#[0-9a-f]{6}$/i.test(s)) return s.toLowerCase();
  if (/^#[0-9a-f]{3}$/i.test(s)) {
    const h = s.slice(1);
    return `#${h[0]}${h[0]}${h[1]}${h[1]}${h[2]}${h[2]}`.toLowerCase();
  }
  const m = RGB_COMMA_RE.exec(s) || RGB_SPACE_RE.exec(s);
  if (!m) return fallback;
  const hex = [m[1], m[2], m[3]]
    .map((n) =>
      Math.max(0, Math.min(255, Math.round(Number(n))))
        .toString(16)
        .padStart(2, "0"),
    )
    .join("");
  return `#${hex}`;
}

/** CSS 변수(--plot-bg, --card 등)를 WebGL용 #rrggbb로 해석 */
export function readCssVarAsHex(varName: string, fallback: string): string {
  if (typeof document === "undefined") return fallback;
  const name = varName.startsWith("--") ? varName : `--${varName}`;
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  if (raw.startsWith("#") || raw.startsWith("rgb")) return cssColorToHex(raw, fallback);
  const probe = document.createElement("span");
  probe.style.color = raw || `var(${name})`;
  document.documentElement.appendChild(probe);
  const computed = getComputedStyle(probe).color;
  probe.remove();
  if (!computed) return fallback;
  const hex = cssColorToHex(computed, fallback);
  // jsdom/미해석 var()는 종종 순수 검정이 됨 — 테마 fallback 유지
  if (hex === "#000000" && fallback.toLowerCase() !== "#000000") return fallback;
  return hex;
}

export function readPlotBackgroundHex(
  theme: ThemeId = DEFAULT_THEME,
  mode: ThemeMode = DEFAULT_THEME_MODE,
): string {
  const fallback = getThemeCanvasColors(theme, mode).plotBg;
  return readCssVarAsHex("--plot-bg", readCssVarAsHex("--background", fallback));
}

export function getThemeCanvasColors(
  theme: ThemeId,
  mode: ThemeMode = DEFAULT_THEME_MODE,
): ThemeCanvasColors {
  const colors = mode === "dark" ? DARK_CANVAS_COLORS : LIGHT_CANVAS_COLORS;
  return colors[theme] || colors.default;
}

/** 선택 테마의 chart 토큰을 파형 채널 팔레트로 직접 사용한다. */
export function getThemeWaveformColors(
  theme: ThemeId,
  mode: ThemeMode = DEFAULT_THEME_MODE,
): WaveformColors {
  const fallback = getThemeCanvasColors(theme, mode);
  return {
    palette: fallback.palette.map((color, index) =>
      readCssVarAsHex(`--chart-${index + 1}`, color),
    ),
    channelColorMap: {},
    gapColor: readCssVarAsHex("--destructive", fallback.gapColor),
    selectionColor: readCssVarAsHex("--ring", fallback.selectionColor),
  };
}
