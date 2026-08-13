import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  applyThemeToDocument,
  DEFAULT_THEME,
  DEFAULT_THEME_MODE,
  persistTheme,
  persistThemeMode,
  readStoredTheme,
  readStoredThemeMode,
  type ThemeId,
  type ThemeMode,
} from "./theme";

type ThemeContextValue = {
  theme: ThemeId;
  previewTheme: ThemeId;
  mode: ThemeMode;
  previewMode: ThemeMode;
  setPreviewTheme: (theme: ThemeId) => void;
  setPreviewMode: (mode: ThemeMode) => void;
  commitTheme: (theme?: ThemeId, mode?: ThemeMode) => void;
  revertPreview: () => void;
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const initialMode =
    typeof document === "undefined" ? DEFAULT_THEME_MODE : readStoredThemeMode();
  const [theme, setTheme] = useState<ThemeId>(() => {
    if (typeof document === "undefined") return DEFAULT_THEME;
    const stored = readStoredTheme();
    applyThemeToDocument(stored, initialMode);
    return stored;
  });
  const [mode, setMode] = useState<ThemeMode>(initialMode);
  const [previewTheme, setPreviewThemeState] = useState<ThemeId>(theme);
  const [previewMode, setPreviewModeState] = useState<ThemeMode>(mode);

  const setPreviewTheme = useCallback(
    (next: ThemeId) => {
      setPreviewThemeState(next);
      applyThemeToDocument(next, previewMode);
    },
    [previewMode],
  );

  const setPreviewMode = useCallback(
    (next: ThemeMode) => {
      setPreviewModeState(next);
      applyThemeToDocument(previewTheme, next);
    },
    [previewTheme],
  );

  const commitTheme = useCallback(
    (nextTheme?: ThemeId, nextMode?: ThemeMode) => {
      const resolvedTheme = nextTheme ?? previewTheme;
      const resolvedMode = nextMode ?? previewMode;
      persistTheme(resolvedTheme);
      persistThemeMode(resolvedMode);
      applyThemeToDocument(resolvedTheme, resolvedMode);
      setTheme(resolvedTheme);
      setMode(resolvedMode);
      setPreviewThemeState(resolvedTheme);
      setPreviewModeState(resolvedMode);
    },
    [previewMode, previewTheme],
  );

  const revertPreview = useCallback(() => {
    setPreviewThemeState(theme);
    setPreviewModeState(mode);
    applyThemeToDocument(theme, mode);
  }, [mode, theme]);

  const value = useMemo(
    () => ({
      theme,
      previewTheme,
      mode,
      previewMode,
      setPreviewTheme,
      setPreviewMode,
      commitTheme,
      revertPreview,
    }),
    [
      theme,
      previewTheme,
      mode,
      previewMode,
      setPreviewTheme,
      setPreviewMode,
      commitTheme,
      revertPreview,
    ],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within ThemeProvider");
  return ctx;
}
