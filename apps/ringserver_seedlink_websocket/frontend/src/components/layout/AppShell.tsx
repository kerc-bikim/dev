import { Menu, Settings } from "lucide-react";
import { StreamTree } from "../Sidebar/StreamTree";
import { SettingsPanel } from "../Sidebar/SettingsPanel";
import { WaveformStack } from "../Waveform/WaveformStack";
import { StatusBar } from "../connection/StatusBar";
import { LayoutMenu } from "./LayoutMenu";
import { useAppStore } from "../../store/appStore";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

export function AppShell() {
  const drawerOpen = useAppStore((s) => s.drawerOpen);
  const setDrawerOpen = useAppStore((s) => s.setDrawerOpen);
  const settingsOpen = useAppStore((s) => s.settingsOpen);
  const setSettingsOpen = useAppStore((s) => s.setSettingsOpen);

  return (
    <div className="app-shell">
      <header className="topbar">
        <Button
          type="button"
          variant="outline"
          size="icon"
          className="menu-btn"
          aria-label="메뉴"
          onClick={() => setDrawerOpen(!drawerOpen)}
        >
          <Menu />
        </Button>
        <div className="brand">
          <strong>RingWave</strong>
          <span>ringserver WebGL viewer</span>
        </div>
        <div className="topbar-actions">
          <LayoutMenu />
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                type="button"
                variant="outline"
                size="icon"
                className="tb-icon-btn"
                onClick={() => setSettingsOpen(!settingsOpen)}
                aria-label="설정"
                aria-pressed={settingsOpen}
              >
                <Settings />
              </Button>
            </TooltipTrigger>
            <TooltipContent>설정</TooltipContent>
          </Tooltip>
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
