import { StreamTree } from "../Sidebar/StreamTree";
import { SettingsPanel } from "../Sidebar/SettingsPanel";
import { WaveformStack } from "../Waveform/WaveformStack";
import { StatusBar } from "../connection/StatusBar";
import { LayoutMenu } from "./LayoutMenu";
import { useAppStore } from "../../store/appStore";

export function AppShell() {
  const drawerOpen = useAppStore((s) => s.drawerOpen);
  const setDrawerOpen = useAppStore((s) => s.setDrawerOpen);
  const settingsOpen = useAppStore((s) => s.settingsOpen);
  const setSettingsOpen = useAppStore((s) => s.setSettingsOpen);

  return (
    <div className="app-shell">
      <header className="topbar">
        <button
          type="button"
          className="menu-btn"
          aria-label="메뉴"
          onClick={() => setDrawerOpen(!drawerOpen)}
        >
          ☰
        </button>
        <div className="brand">
          <strong>RingWave</strong>
          <span>ringserver WebGL viewer</span>
        </div>
        <div className="topbar-actions">
          <LayoutMenu />
          <button
            type="button"
            className="tb-icon-btn"
            onClick={() => setSettingsOpen(!settingsOpen)}
            title="설정"
            aria-label="설정"
            aria-pressed={settingsOpen}
          >
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
              <path
                fill="currentColor"
                d="M19.14 12.94c.04-.31.06-.63.06-.94s-.02-.63-.06-.94l2.03-1.58a.49.49 0 0 0 .12-.61l-1.92-3.32a.49.49 0 0 0-.59-.22l-2.39.96a7.07 7.07 0 0 0-1.62-.94l-.36-2.54a.48.48 0 0 0-.48-.41h-3.84a.48.48 0 0 0-.48.41l-.36 2.54c-.57.23-1.11.54-1.62.94l-2.39-.96a.49.49 0 0 0-.59.22L2.77 8.87a.48.48 0 0 0 .12.61l2.03 1.58c-.04.31-.06.63-.06.94s.02.63.06.94l-2.03 1.58a.49.49 0 0 0-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.4 1.05.72 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.48-.41l.36-2.54c.57-.22 1.11-.54 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32a.49.49 0 0 0-.12-.61l-2.03-1.58zM12 15.6A3.6 3.6 0 1 1 15.6 12 3.61 3.61 0 0 1 12 15.6z"
              />
            </svg>
          </button>
        </div>
      </header>
      <StatusBar />
      <div className="main">
        <aside className={`sidebar ${drawerOpen ? "open" : ""}`}>
          <StreamTree />
        </aside>
        {drawerOpen && (
          <button
            type="button"
            className="drawer-backdrop"
            aria-label="닫기"
            onClick={() => setDrawerOpen(false)}
          />
        )}
        <section className="content">
          <WaveformStack />
        </section>
      </div>
      <SettingsPanel />
    </div>
  );
}
