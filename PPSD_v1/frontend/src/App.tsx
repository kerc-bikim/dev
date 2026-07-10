import { useState } from "react";
import { SingleTab } from "./tabs/SingleTab";
import { MultiTab } from "./tabs/MultiTab";
import { CompareStationTab } from "./tabs/CompareStationTab";
import { CompareTimeTab } from "./tabs/CompareTimeTab";

type TabId = "single" | "multi" | "compare_station" | "compare_time";

const TABS: { id: TabId; label: string }[] = [
  { id: "single", label: "Single" },
  { id: "multi", label: "Multi" },
  { id: "compare_station", label: "Compare Station" },
  { id: "compare_time", label: "Compare Time" },
];

export default function App() {
  const [tab, setTab] = useState<TabId>("single");

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <h1>PPSD Viewer</h1>
          <small>FDSNWS · ObsPy</small>
        </div>
        <nav className="tabs">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              className={`tab ${tab === t.id ? "active" : ""}`}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </header>
      <div className="app">
        {tab === "single" && <SingleTab />}
        {tab === "multi" && <MultiTab />}
        {tab === "compare_station" && <CompareStationTab />}
        {tab === "compare_time" && <CompareTimeTab />}
      </div>
    </div>
  );
}
