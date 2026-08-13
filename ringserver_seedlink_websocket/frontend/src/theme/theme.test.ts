import { afterEach, describe, expect, it } from "vitest";
import {
  applyThemeToDocument,
  cssColorToHex,
  DEFAULT_CANVAS_COLORS,
  DEFAULT_THEME,
  DEFAULT_THEME_MODE,
  getThemeCanvasColors,
  getThemeWaveformColors,
  parseThemeId,
  parseThemeMode,
  persistTheme,
  persistThemeMode,
  readPlotBackgroundHex,
  readStoredTheme,
  readStoredThemeMode,
  THEME_MODE_STORAGE_KEY,
  THEME_STORAGE_KEY,
} from "./theme";

describe("parseThemeId", () => {
  it("accepts known theme ids", () => {
    expect(parseThemeId("default")).toBe("default");
    expect(parseThemeId("claude")).toBe("claude");
    expect(parseThemeId("candyland")).toBe("candyland");
  });

  it("falls back to default for invalid values", () => {
    expect(parseThemeId("light")).toBe(DEFAULT_THEME);
    expect(parseThemeId(null)).toBe(DEFAULT_THEME);
    expect(parseThemeId(12)).toBe(DEFAULT_THEME);
  });

  it("migrates the retired Amethyst Haze id to Claude", () => {
    expect(parseThemeId("amethyst-haze")).toBe("claude");
  });

  it("migrates the retired Supabase id to Candyland", () => {
    expect(parseThemeId("supabase")).toBe("candyland");
  });

  it("parses the light and dark modes", () => {
    expect(parseThemeMode("light")).toBe("light");
    expect(parseThemeMode("dark")).toBe("dark");
    expect(parseThemeMode("system")).toBe(DEFAULT_THEME_MODE);
  });
});

describe("theme persistence", () => {
  afterEach(() => {
    window.localStorage.removeItem(THEME_STORAGE_KEY);
    window.localStorage.removeItem(THEME_MODE_STORAGE_KEY);
    document.documentElement.removeAttribute("data-theme");
    document.documentElement.removeAttribute("data-mode");
    document.documentElement.classList.remove("dark");
  });

  it("stores and restores a valid theme", () => {
    persistTheme("candyland");
    persistThemeMode("dark");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("candyland");
    expect(window.localStorage.getItem(THEME_MODE_STORAGE_KEY)).toBe("dark");
    expect(readStoredTheme()).toBe("candyland");
    expect(readStoredThemeMode()).toBe("dark");
  });

  it("falls back when localStorage is corrupt", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "not-a-theme");
    expect(readStoredTheme()).toBe(DEFAULT_THEME);
  });

  it("applies theme and mode on the document root", () => {
    applyThemeToDocument("claude", "dark");
    expect(document.documentElement.dataset.theme).toBe("claude");
    expect(document.documentElement.dataset.mode).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(document.documentElement.style.colorScheme).toBe("dark");
  });
});

describe("theme canvas colors", () => {
  it("uses a high-contrast palette on the light default canvas", () => {
    expect(getThemeCanvasColors("default")).toEqual(DEFAULT_CANVAS_COLORS);
    expect(getThemeCanvasColors("default").palette[0]).toBe("#2563eb");
    expect(getThemeCanvasColors("default").plotBg).toBe("#ffffff");
  });

  it("uses distinct palettes and plot backgrounds per theme", () => {
    const def = getThemeCanvasColors("default");
    const claude = getThemeCanvasColors("claude");
    const candyland = getThemeCanvasColors("candyland");
    expect(claude.plotBg).not.toBe(def.plotBg);
    expect(candyland.plotBg).not.toBe(def.plotBg);
    expect(claude.palette[0]).not.toBe(def.palette[0]);
    expect(candyland.palette[0]).not.toBe(def.palette[0]);
    expect(getThemeCanvasColors("candyland", "dark").plotBg).not.toBe(candyland.plotBg);
  });

  it("uses bright channel palettes for Default and Claude dark canvases", () => {
    expect(getThemeCanvasColors("default", "dark").palette).toEqual([
      "#38bdf8",
      "#60a5fa",
      "#5eead4",
      "#facc15",
      "#e879f9",
    ]);
    expect(getThemeCanvasColors("claude", "dark").palette).toEqual([
      "#f08c62",
      "#c4a7e7",
      "#6fd6bd",
      "#e8c36a",
      "#7fb2f0",
    ]);
  });

  it("uses darker channel palettes on light canvases", () => {
    expect(getThemeCanvasColors("default", "light").palette).toEqual([
      "#2563eb",
      "#4338ca",
      "#0f766e",
      "#b45309",
      "#be185d",
    ]);
    expect(getThemeCanvasColors("claude", "light").palette).toEqual([
      "#b45332",
      "#7c3aed",
      "#0f766e",
      "#a16207",
      "#2563eb",
    ]);
    expect(getThemeCanvasColors("candyland", "light").palette).toEqual([
      "#db2777",
      "#0284c7",
      "#65a30d",
      "#c026d3",
      "#15803d",
    ]);
  });

  it("builds the channel palette directly from chart tokens", () => {
    const root = document.documentElement;
    ["#111111", "#222222", "#333333", "#444444", "#555555"].forEach((color, i) =>
      root.style.setProperty(`--chart-${i + 1}`, color),
    );
    root.style.setProperty("--destructive", "#aa0000");
    root.style.setProperty("--ring", "#0066cc");

    const colors = getThemeWaveformColors("default");
    expect(colors.palette).toEqual(["#111111", "#222222", "#333333", "#444444", "#555555"]);
    expect(colors.channelColorMap).toEqual({});
    expect(colors.gapColor).toBe("#aa0000");
    expect(colors.selectionColor).toBe("#0066cc");

    for (let i = 1; i <= 5; i++) root.style.removeProperty(`--chart-${i}`);
    root.style.removeProperty("--destructive");
    root.style.removeProperty("--ring");
  });

  it("converts css colors to hex for WebGL", () => {
    expect(cssColorToHex("#232030", "#000")).toBe("#232030");
    expect(cssColorToHex("#abc", "#000")).toBe("#aabbcc");
    expect(cssColorToHex("rgb(35, 32, 48)", "#000")).toBe("#232030");
    expect(cssColorToHex("rgb(35 32 48)", "#000")).toBe("#232030");
    expect(cssColorToHex("not-a-color", "#1c1c1c")).toBe("#1c1c1c");
  });

  it("reads --plot-bg when it is a concrete hex", () => {
    document.documentElement.style.setProperty("--plot-bg", "#232030");
    expect(readPlotBackgroundHex("claude")).toBe("#232030");
    document.documentElement.style.removeProperty("--plot-bg");
    expect(readPlotBackgroundHex("claude")).toBe("#faf9f5");
  });
});
