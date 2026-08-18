import { useCallback, useEffect, useRef, useState } from "react";
import { downloadFile, uploadFile, type Mode } from "./api";
import { CatalogPage } from "./CatalogPage";
import { HelpPage } from "./HelpPage";
import { HistoryPage } from "./HistoryPage";
import { Workspace } from "./Workspace";

const MODES: { id: Mode; label: string }[] = [
  { id: "workspace", label: "작업 공간" },
  { id: "catalog", label: "장비 카탈로그" },
  { id: "history", label: "변경이력" },
  { id: "help", label: "도움말" },
];

const EXPORTS = [
  { path: "/api/export/stationxml", name: "inventory.xml", label: "StationXML" },
  { path: "/api/export/dataless", name: "inventory.dataless", label: "Dataless SEED" },
  { path: "/api/export/xlsx", name: "inventory.xlsx", label: "엑셀" },
  { path: "/api/template.xlsx", name: "stationxml_template.xlsx", label: "엑셀 템플릿" },
];

function parseMode(hash: string): Mode {
  const value = hash.replace(/^#/, "");
  if (value === "catalog" || value === "history") return value;
  if (value === "help" || value.startsWith("help-")) return "help";
  return "workspace";
}

function useHashMode(): [Mode, (mode: Mode) => void] {
  const [mode, setModeState] = useState<Mode>(() => parseMode(window.location.hash));
  useEffect(() => {
    const onHash = () => setModeState(parseMode(window.location.hash));
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const setMode = useCallback((next: Mode) => {
    window.location.hash = next === "workspace" ? "workspace" : next;
    setModeState(next);
  }, []);
  return [mode, setMode];
}

function useActor() {
  const [actor, setActor] = useState(() => localStorage.getItem("sxm-actor") || "");
  useEffect(() => {
    localStorage.setItem("sxm-actor", actor);
  }, [actor]);
  return [actor, setActor] as const;
}

function useApiKey() {
  const [apiKey, setApiKey] = useState(() => localStorage.getItem("sxm-api-key") || "");
  const updateApiKey = useCallback((value: string) => {
    localStorage.setItem("sxm-api-key", value);
    setApiKey(value);
  }, []);
  return [apiKey, updateApiKey] as const;
}

export default function App() {
  const [mode, setMode] = useHashMode();
  const [actor, setActor] = useActor();
  const [apiKey, setApiKey] = useApiKey();
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [importMessage, setImportMessage] = useState<string | null>(null);
  const [importWarnings, setImportWarnings] = useState<string[]>([]);
  const [exportWarnings, setExportWarnings] = useState<string[]>([]);
  const [replaceAll, setReplaceAll] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const bump = () => setReloadToken((n) => n + 1);

  useEffect(() => {
    if (!exportOpen) return;
    const close = () => setExportOpen(false);
    window.addEventListener("click", close);
    return () => window.removeEventListener("click", close);
  }, [exportOpen]);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand-block">
          <h1 className="brand">StationXML 메타데이터 관리</h1>
          <span className="muted brand-sub">관측망 워크벤치</span>
        </div>
        <nav className="tabs">
          {MODES.map((item) => (
            <button
              key={item.id}
              className={`tab ${mode === item.id ? "active" : ""}`}
              onClick={() => setMode(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>
        <label className="actor">
          작업자
          <input
            value={actor}
            onChange={(e) => setActor(e.target.value)}
            placeholder="이름(선택)"
          />
        </label>
        <label className="actor">
          API 키
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="원격 접속 시"
          />
        </label>
        <label className="replace-check">
          <input
            type="checkbox"
            checked={replaceAll}
            onChange={(e) => setReplaceAll(e.target.checked)}
          />
          기존 목록 교체
        </label>
        <input
          ref={fileRef}
          type="file"
          hidden
          accept=".xlsx,.xml,.stationxml,.seed,.dataless,.dlsv"
          onChange={async (e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (!file) return;
            if (
              replaceAll &&
              !confirm("현재 네트워크·관측소·채널 목록을 모두 교체합니다. 계속할까요?")
            ) {
              return;
            }
            try {
              const result = await uploadFile(file, replaceAll, actor);
              setImportMessage(`가져오기 완료: 추가 ${result.created}, 수정 ${result.updated}`);
              setImportWarnings(result.warnings || []);
              setExportWarnings([]);
              setError(null);
              bump();
              setMode("workspace");
            } catch (err) {
              setError(err instanceof Error ? err.message : String(err));
            }
          }}
        />
        <button className="secondary" onClick={() => fileRef.current?.click()}>
          가져오기
        </button>
        <div className="export-wrap" onClick={(e) => e.stopPropagation()}>
          <button className="secondary" onClick={() => setExportOpen((v) => !v)}>
            내보내기 ▾
          </button>
          {exportOpen && (
            <div className="export-menu">
              {EXPORTS.map((item) => (
                <button
                  key={item.path}
                  className="export-item"
                  onClick={() => {
                    setExportOpen(false);
                    void downloadFile(item.path, item.name)
                      .then((items) => {
                        setExportWarnings(items);
                        setError(null);
                      })
                      .catch((err) =>
                        setError(err instanceof Error ? err.message : String(err))
                      );
                  }}
                >
                  {item.label}
                </button>
              ))}
            </div>
          )}
        </div>
      </header>
      {error && <div className="error banner">{error}</div>}
      <main className={`content ${mode === "workspace" ? "workspace-content" : ""} ${mode === "help" ? "help-content" : ""}`}>
        {mode === "workspace" && (
          <Workspace
            actor={actor}
            onError={setError}
            reloadToken={reloadToken}
            importMessage={importMessage}
            importWarnings={importWarnings}
            exportWarnings={exportWarnings}
            onOpenHelp={() => setMode("help")}
          />
        )}
        {mode === "catalog" && <CatalogPage actor={actor} onError={setError} />}
        {mode === "history" && <HistoryPage onError={setError} />}
        {mode === "help" && <HelpPage onGoWorkspace={() => setMode("workspace")} />}
      </main>
    </div>
  );
}
