import { useEffect, useRef, useState } from "react";
import { useAppStore } from "../../store/appStore";
import {
  TIME_WINDOW_STEPS,
  formatTimeWindow,
  formatTimeWindowLabel,
  stepTimeWindow,
} from "../../realtime/timeWindow";
import {
  BUILTIN_BANDPASS_PRESETS,
  clampBandPassToNyquist,
  mergeBandPassPresets,
  type BandPassPreset,
} from "../../realtime/bandPassPresets";
import { bufferStore } from "../../buffer/ringBuffer";
import { scnlKey } from "../../types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

const labels: Record<string, string> = {
  connecting: "연결 중",
  connected: "연결됨",
  reconnecting: "재연결 중",
  disconnected: "끊김",
  error: "오류",
};

function fmtBand(p: BandPassPreset): string {
  return `${p.fminHz}–${p.fmaxHz} Hz`;
}

export function StatusBar() {
  const status = useAppStore((s) => s.connectionStatus);
  const detail = useAppStore((s) => s.connectionDetail);
  const globalPaused = useAppStore((s) => s.globalPaused);
  const setGlobalPaused = useAppStore((s) => s.setGlobalPaused);
  const settings = useAppStore((s) => s.settings);
  const saveSettings = useAppStore((s) => s.saveSettings);
  const panels = useAppStore((s) => s.panels);
  const clearAllPanels = useAppStore((s) => s.clearAllPanels);
  const [windowModalOpen, setWindowModalOpen] = useState(false);
  const [draftWindow, setDraftWindow] = useState(300);
  const [filterOpen, setFilterOpen] = useState(false);
  const [addingCustom, setAddingCustom] = useState(false);
  const [customName, setCustomName] = useState("");
  const [customFmin, setCustomFmin] = useState("0.5");
  const [customFmax, setCustomFmax] = useState("5");
  const [filterMsg, setFilterMsg] = useState("");
  const [closeAllOpen, setCloseAllOpen] = useState(false);
  const [deletePresetId, setDeletePresetId] = useState<string | null>(null);
  const filterRootRef = useRef<HTMLDivElement>(null);

  const durationSec = settings?.durationSec ?? 300;
  const amplitudeMode = settings?.amplitudeMode || "raw";
  const isPhysical = amplitudeMode === "physical";
  const yScaleMode = settings?.yScaleMode || "auto";
  const isUniformScale = yScaleMode === "uniform";
  const bandPassEnabled = !!settings?.bandPassEnabled;
  const bandPassPresetId = settings?.bandPassPresetId ?? null;
  const presets = mergeBandPassPresets(
    settings?.bandPassPresets || BUILTIN_BANDPASS_PRESETS,
  );
  const activePreset = bandPassEnabled
    ? presets.find((p) => p.id === bandPassPresetId)
    : null;

  useEffect(() => {
    if (windowModalOpen) setDraftWindow(durationSec);
  }, [windowModalOpen, durationSec]);

  useEffect(() => {
    if (!filterOpen) return;
    const onDoc = (e: MouseEvent) => {
      if (!filterRootRef.current?.contains(e.target as Node)) {
        setFilterOpen(false);
        setAddingCustom(false);
        setFilterMsg("");
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setFilterOpen(false);
        setAddingCustom(false);
        setFilterMsg("");
      }
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [filterOpen]);

  const setDuration = (sec: number) => {
    void saveSettings({ durationSec: sec });
  };

  const toggleAmplitude = () => {
    void saveSettings({
      amplitudeMode: isPhysical ? "raw" : "physical",
    });
  };

  const toggleYScale = () => {
    void saveSettings({
      yScaleMode: isUniformScale ? "auto" : "uniform",
    });
  };

  const closeAllStreams = () => {
    if (!panels.length) return;
    setCloseAllOpen(true);
  };

  const selectFilterOff = () => {
    void saveSettings({ bandPassEnabled: false, bandPassPresetId: null });
    setFilterOpen(false);
    setAddingCustom(false);
  };

  const selectPreset = (id: string) => {
    void saveSettings({ bandPassEnabled: true, bandPassPresetId: id });
    setFilterOpen(false);
    setAddingCustom(false);
  };

  const addCustomPreset = () => {
    const name = customName.trim() || "Custom BP";
    const fmin = Number(customFmin);
    const fmax = Number(customFmax);
    if (!(fmin > 0)) {
      setFilterMsg("Min Frequency는 0보다 커야 합니다.");
      return;
    }
    if (!(fmax > fmin)) {
      setFilterMsg("Max Frequency는 Min보다 커야 합니다.");
      return;
    }
    if (minSampleRate > 0) {
      const nyq = minSampleRate / 2;
      const clamped = clampBandPassToNyquist(fmin, fmax, minSampleRate);
      if (!clamped) {
        setFilterMsg(
          `밴드가 현재 채널 Nyquist(${nyq.toFixed(2)} Hz)를 벗어나 적용할 수 없습니다.`,
        );
        return;
      }
      if (clamped.clamped) {
        setFilterMsg(
          `Nyquist(${nyq.toFixed(2)} Hz) 안으로 잘라 ${clamped.fminHz.toPrecision(3)}–${clamped.fmaxHz.toPrecision(3)} Hz로 적용합니다.`,
        );
      }
    }
    const id = `custom-${Date.now().toString(36)}`;
    const next: BandPassPreset = {
      id,
      name: name.slice(0, 64),
      fminHz: fmin,
      fmaxHz: fmax,
      group: "custom",
      builtin: false,
    };
    const merged = mergeBandPassPresets([...presets, next]);
    void saveSettings({
      bandPassPresets: merged,
      bandPassEnabled: true,
      bandPassPresetId: id,
    });
    setCustomName("");
    setCustomFmin("0.5");
    setCustomFmax("5");
    setAddingCustom(false);
    setFilterMsg("");
    setFilterOpen(false);
  };

  const deleteCustomPreset = (id: string) => {
    const target = presets.find((p) => p.id === id);
    if (!target || target.builtin || target.group !== "custom") return;
    const next = presets.filter((p) => p.id !== id);
    const patch: {
      bandPassPresets: BandPassPreset[];
      bandPassEnabled?: boolean;
      bandPassPresetId?: string | null;
    } = { bandPassPresets: mergeBandPassPresets(next) };
    if (bandPassPresetId === id) {
      patch.bandPassEnabled = false;
      patch.bandPassPresetId = null;
    }
    void saveSettings(patch);
  };

  const applyWindowModal = () => {
    setDuration(draftWindow);
    setWindowModalOpen(false);
  };

  const atMin = durationSec <= TIME_WINDOW_STEPS[0]!;
  const atMax = durationSec >= TIME_WINDOW_STEPS[TIME_WINDOW_STEPS.length - 1]!;

  const minSampleRate = panels.reduce((minSr, p) => {
    const sr = bufferStore.get(scnlKey(p.scnl))?.sampleRate || 0;
    if (!(sr > 0)) return minSr;
    return minSr === 0 ? sr : Math.min(minSr, sr);
  }, 0);
  const activeNyquist =
    activePreset && minSampleRate > 0
      ? clampBandPassToNyquist(activePreset.fminHz, activePreset.fmaxHz, minSampleRate)
      : null;
  const nyquistWarn =
    activePreset && minSampleRate > 0 && activeNyquist === null
      ? `현재 채널 Nyquist(${(minSampleRate / 2).toFixed(2)} Hz)보다 밴드가 높아 필터를 적용할 수 없습니다.`
      : activePreset && activeNyquist?.clamped
        ? `Nyquist(${(minSampleRate / 2).toFixed(2)} Hz)에 맞춰 ${activeNyquist.fminHz.toPrecision(3)}–${activeNyquist.fmaxHz.toPrecision(3)} Hz로 적용합니다.`
        : "";

  const builtin = presets.filter((p) => p.builtin);
  const custom = presets.filter((p) => !p.builtin);

  return (
    <>
      <div className="status-bar">
        <div className="status-bar-side">
          <Badge
            variant={
              status === "connected"
                ? "success"
                : status === "error" || status === "disconnected"
                  ? "destructive"
                  : status === "connecting" || status === "reconnecting"
                    ? "warning"
                    : "secondary"
            }
            className={`pill status-${status}`}
          >
            {labels[status] || status}
          </Badge>
          <span className="status-detail" title={detail}>
            {detail}
          </span>
        </div>

        <div className="status-bar-main">
          <div className="status-bar-left" aria-label="타임윈도우 및 파형 컨트롤">
            <Button
              type="button"
              variant="outline"
              size="icon"
              className="tb-icon-btn tb-window-btn w-auto px-2"
              onClick={() => setWindowModalOpen(true)}
              title="타임윈도우 설정"
              aria-label="타임윈도우 설정"
            >
              <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
                <path
                  fill="currentColor"
                  d="M12 2a10 10 0 1 0 10 10A10.011 10.011 0 0 0 12 2zm0 18a8 8 0 1 1 8-8 8.009 8.009 0 0 1-8 8zm.5-13H11v6l5.25 3.15.75-1.23-4.5-2.67z"
                />
              </svg>
              <span className="tb-window-value">{formatTimeWindow(durationSec)}</span>
            </Button>

            <Button
              type="button"
              variant="outline"
              size="icon"
              className="tb-icon-btn"
              disabled={atMax}
              onClick={() => setDuration(stepTimeWindow(durationSec, "out"))}
              title="줌아웃 — 타임윈도우 늘리기"
              aria-label="줌아웃"
            >
              <svg viewBox="0 0 24 24" width="19" height="19" aria-hidden="true">
                <path
                  fill="currentColor"
                  d="M15.5 14h-.79l-.28-.27A6.471 6.471 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14zM7 9h5v1H7V9z"
                />
              </svg>
            </Button>

            <Button
              type="button"
              variant="outline"
              size="icon"
              className="tb-icon-btn"
              disabled={atMin}
              onClick={() => setDuration(stepTimeWindow(durationSec, "in"))}
              title="줌인 — 타임윈도우 줄이기"
              aria-label="줌인"
            >
              <svg viewBox="0 0 24 24" width="19" height="19" aria-hidden="true">
                <path
                  fill="currentColor"
                  d="M15.5 14h-.79l-.28-.27A6.471 6.471 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14zM10 7H9v2H7v1h2v2h1v-2h2V9h-2V7z"
                />
              </svg>
            </Button>

            <Button
              type="button"
              variant="outline"
              size="icon"
              className={cn("tb-icon-btn pause-icon-btn", globalPaused && "paused")}
              onClick={() => setGlobalPaused(!globalPaused)}
              title={globalPaused ? "재개" : "일시정지"}
              aria-label={globalPaused ? "재개" : "일시정지"}
              aria-pressed={globalPaused}
            >
              {globalPaused ? (
                <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
                  <path fill="currentColor" d="M8 5v14l11-7L8 5z" />
                </svg>
              ) : (
                <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
                  <path fill="currentColor" d="M7 5h3v14H7V5zm7 0h3v14h-3V5z" />
                </svg>
              )}
            </Button>

            <Button
              type="button"
              variant="outline"
              size="icon"
              className={cn("tb-icon-btn scale-icon-btn", isUniformScale && "uniform")}
              onClick={toggleYScale}
              title={
                isUniformScale
                  ? "Uniform 스케일 — 클릭하면 Auto로 전환"
                  : "Auto 스케일 — 클릭하면 Uniform(최대 진폭 기준)으로 전환"
              }
              aria-label={isUniformScale ? "Uniform 스케일" : "Auto 스케일"}
              aria-pressed={isUniformScale}
            >
              <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
                <path
                  fill="currentColor"
                  d="M3 5h2v14H3V5zm4 4h2v10H7V9zm4-4h2v14h-2V5zm4 6h2v8h-2v-8zm4-2h2v10h-2V9z"
                />
              </svg>
            </Button>

            <Button
              type="button"
              variant="outline"
              size="icon"
              className={cn("tb-icon-btn calib-icon-btn", isPhysical && "physical")}
              onClick={toggleAmplitude}
              title={
                isPhysical
                  ? "Physical(물리량) — 클릭하면 Raw counts로 전환"
                  : "Raw counts — 클릭하면 Physical(물리량)로 전환"
              }
              aria-label={isPhysical ? "Physical 물리량" : "Raw counts"}
              aria-pressed={isPhysical}
            >
              <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
                <path
                  fill="currentColor"
                  d="M22 7H2v10h20V7zm-2 8H4v-6h2v4h2v-4h2v4h2v-4h2v4h2v-4h2v4h2v-4h2v6z"
                />
              </svg>
            </Button>

            <div className="filter-menu" ref={filterRootRef}>
              <Button
                type="button"
                variant="outline"
                size="icon"
                className={cn("tb-icon-btn filter-icon-btn", bandPassEnabled && "active")}
                onClick={() => {
                  setFilterOpen((v) => !v);
                  setFilterMsg("");
                }}
                title={
                  activePreset
                    ? `밴드패스 ${activePreset.name} (${fmtBand(activePreset)})`
                    : "밴드패스 필터 (Off)"
                }
                aria-label="밴드패스 필터"
                aria-pressed={bandPassEnabled}
                aria-expanded={filterOpen}
              >
                <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
                  <path
                    fill="currentColor"
                    d="M10 18h4v-2h-4v2zM3 6v2h18V6H3zm3 7h12v-2H6v2z"
                  />
                </svg>
              </Button>
              {filterOpen && (
                <div className="filter-dropdown" role="menu">
                  <div className="filter-dropdown-head">Band-pass Filter</div>
                  {nyquistWarn && <p className="filter-msg">{nyquistWarn}</p>}
                  <button
                    type="button"
                    className={`filter-item ${!bandPassEnabled ? "selected" : ""}`}
                    onClick={selectFilterOff}
                  >
                    <span className="filter-item-name">Off</span>
                    <span className="filter-item-band">필터 없음</span>
                  </button>

                  {builtin.map((p) => (
                    <button
                      key={p.id}
                      type="button"
                      className={`filter-item ${
                        bandPassEnabled && bandPassPresetId === p.id ? "selected" : ""
                      }`}
                      onClick={() => selectPreset(p.id)}
                    >
                      <span className="filter-item-name">{p.name}</span>
                      <span className="filter-item-band">{fmtBand(p)}</span>
                    </button>
                  ))}

                  {(custom.length > 0 || addingCustom) && (
                    <div className="filter-group-label">커스텀</div>
                  )}
                  {custom.map((p) => (
                    <div key={p.id} className="filter-custom-row">
                      <button
                        type="button"
                        className={`filter-item ${
                          bandPassEnabled && bandPassPresetId === p.id ? "selected" : ""
                        }`}
                        onClick={() => selectPreset(p.id)}
                      >
                        <span className="filter-item-name">{p.name}</span>
                        <span className="filter-item-band">{fmtBand(p)}</span>
                      </button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="filter-del"
                        title="삭제"
                        aria-label={`${p.name} 삭제`}
                        onClick={() => setDeletePresetId(p.id)}
                      >
                        ✕
                      </Button>
                    </div>
                  ))}

                  {!addingCustom ? (
                    <Button
                      type="button"
                      variant="outline"
                      className="filter-add-btn"
                      onClick={() => {
                        setAddingCustom(true);
                        setFilterMsg("");
                      }}
                    >
                      + 커스텀 추가
                    </Button>
                  ) : (
                    <div className="filter-add-form">
                      <label>
                        이름
                        <Input
                          value={customName}
                          onChange={(e) => setCustomName(e.target.value)}
                          placeholder="예: BP 2–8 Hz"
                        />
                      </label>
                      <div className="filter-add-freq">
                        <label>
                          Min Hz
                          <Input
                            type="number"
                            step="any"
                            min="0"
                            value={customFmin}
                            onChange={(e) => setCustomFmin(e.target.value)}
                          />
                        </label>
                        <label>
                          Max Hz
                          <Input
                            type="number"
                            step="any"
                            min="0"
                            value={customFmax}
                            onChange={(e) => setCustomFmax(e.target.value)}
                          />
                        </label>
                      </div>
                      {filterMsg && <p className="filter-msg">{filterMsg}</p>}
                      <div className="filter-add-actions">
                        <Button type="button" onClick={addCustomPreset}>
                          저장·적용
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          onClick={() => {
                            setAddingCustom(false);
                            setFilterMsg("");
                          }}
                        >
                          취소
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          <div className="status-bar-right">
            <Button
              type="button"
              variant="outline"
              size="icon"
              className="tb-icon-btn close-all-btn"
              onClick={closeAllStreams}
              disabled={!panels.length}
              title="전체 스트림 닫기"
              aria-label="전체 스트림 닫기"
            >
              <X className="size-4" aria-hidden="true" />
            </Button>
          </div>
        </div>
      </div>

      <Dialog open={windowModalOpen} onOpenChange={setWindowModalOpen}>
        <DialogContent className="time-window-modal max-w-[360px]">
          <DialogHeader>
            <DialogTitle>타임윈도우</DialogTitle>
          </DialogHeader>
          <div className="time-window-modal-body">
            <label>
              표시 구간
              <Select
                value={String(draftWindow)}
                onValueChange={(value) => setDraftWindow(Number(value))}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {!TIME_WINDOW_STEPS.includes(
                    draftWindow as (typeof TIME_WINDOW_STEPS)[number],
                  ) && (
                    <SelectItem value={String(draftWindow)}>
                      현재 {formatTimeWindowLabel(draftWindow)} ({draftWindow}s)
                    </SelectItem>
                  )}
                  {TIME_WINDOW_STEPS.map((sec) => (
                    <SelectItem key={sec} value={String(sec)}>
                      {formatTimeWindowLabel(sec)} ({sec}s)
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </label>
            <p className="muted">줌인/줌아웃은 위 프리셋 간격으로 이동합니다.</p>
          </div>
          <DialogFooter>
            <Button type="button" onClick={applyWindowModal}>
              적용
            </Button>
            <Button type="button" variant="outline" onClick={() => setWindowModalOpen(false)}>
              닫기
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={closeAllOpen} onOpenChange={setCloseAllOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>전체 스트림 닫기</AlertDialogTitle>
            <AlertDialogDescription>
              표출 중인 스트림 {panels.length}개를 모두 닫을까요?
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>취소</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                clearAllPanels();
                setCloseAllOpen(false);
              }}
            >
              닫기
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog
        open={deletePresetId != null}
        onOpenChange={(open) => !open && setDeletePresetId(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>커스텀 필터 삭제</AlertDialogTitle>
            <AlertDialogDescription>
              {`커스텀 필터 「${presets.find((p) => p.id === deletePresetId)?.name || ""}」을(를) 삭제할까요?`}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>취소</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (deletePresetId) deleteCustomPreset(deletePresetId);
                setDeletePresetId(null);
              }}
            >
              삭제
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
