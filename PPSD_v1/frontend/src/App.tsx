import { useEffect, useState, type ReactNode } from "react";
import { SingleTab } from "./tabs/SingleTab";
import { MultiTab } from "./tabs/MultiTab";
import { CompareStationTab } from "./tabs/CompareStationTab";
import { CompareTimeTab } from "./tabs/CompareTimeTab";
import { SettingsModal } from "./components/SettingsModal";

type TabId = "single" | "multi" | "compare_station" | "compare_time";

const TABS: { id: TabId; label: string }[] = [
  { id: "single", label: "Single" },
  { id: "multi", label: "Multi" },
  { id: "compare_station", label: "Compare Station" },
  { id: "compare_time", label: "Compare Time" },
];

function TabPanel({
  id,
  active,
  children,
}: {
  id: TabId;
  active: boolean;
  children: ReactNode;
}) {
  return (
    <div
      className={`tab-panel${active ? " active" : ""}`}
      role="tabpanel"
      id={`panel-${id}`}
      aria-hidden={!active}
      inert={!active}
    >
      {children}
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState<TabId>("single");
  const [settingsOpen, setSettingsOpen] = useState(false);

  // Hidden panels use display:none, so charts need a resize after showing again.
  useEffect(() => {
    const id = requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        window.dispatchEvent(new Event("resize"));
      });
    });
    return () => cancelAnimationFrame(id);
  }, [tab]);

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <h1>PPSD Viewer</h1>
          <small>FDSNWS · ObsPy</small>
        </div>
        <nav className="tabs" role="tablist">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={tab === t.id}
              aria-controls={`panel-${t.id}`}
              className={`tab ${tab === t.id ? "active" : ""}`}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
          <button
            type="button"
            className="tab settings-tab"
            onClick={() => setSettingsOpen(true)}
            title="설정"
          >
            ⚙ 설정
          </button>
        </nav>
      </header>
      <div className="app">
        <TabPanel id="single" active={tab === "single"}>
          <SingleTab />
        </TabPanel>
        <TabPanel id="multi" active={tab === "multi"}>
          <MultiTab />
        </TabPanel>
        <TabPanel id="compare_station" active={tab === "compare_station"}>
          <CompareStationTab />
        </TabPanel>
        <TabPanel id="compare_time" active={tab === "compare_time"}>
          <CompareTimeTab />
        </TabPanel>
      </div>
      {settingsOpen && <SettingsModal onClose={() => setSettingsOpen(false)} />}
    </div>
  );
}
