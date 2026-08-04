import { useEffect, useState } from "react";
import { useAppStore } from "../../store/appStore";
import {
  TIME_WINDOW_STEPS,
  formatTimeWindow,
  formatTimeWindowLabel,
  stepTimeWindow,
} from "../../realtime/timeWindow";

const labels: Record<string, string> = {
  connecting: "연결 중",
  connected: "연결됨",
  reconnecting: "재연결 중",
  disconnected: "끊김",
  error: "오류",
};

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

  const durationSec = settings?.durationSec ?? 300;
  const amplitudeMode = settings?.amplitudeMode || "raw";
  const isPhysical = amplitudeMode === "physical";
  const yScaleMode = settings?.yScaleMode || "auto";
  const isUniformScale = yScaleMode === "uniform";

  useEffect(() => {
    if (windowModalOpen) setDraftWindow(durationSec);
  }, [windowModalOpen, durationSec]);

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
    if (!confirm(`표출 중인 스트림 ${panels.length}개를 모두 닫을까요?`)) return;
    clearAllPanels();
  };

  const applyWindowModal = () => {
    setDuration(draftWindow);
    setWindowModalOpen(false);
  };

  const atMin = durationSec <= TIME_WINDOW_STEPS[0]!;
  const atMax = durationSec >= TIME_WINDOW_STEPS[TIME_WINDOW_STEPS.length - 1]!;

  return (
    <>
      <div className="status-bar">
        <div className="status-bar-side">
          <span className={`pill status-${status}`}>{labels[status] || status}</span>
          <span className="status-detail" title={detail}>
            {detail}
          </span>
        </div>

        <div className="status-bar-main">
          <div className="status-bar-left" aria-label="타임윈도우 및 파형 컨트롤">
            <button
              type="button"
              className="tb-icon-btn tb-window-btn"
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
            </button>

            <button
              type="button"
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
            </button>

            <button
              type="button"
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
            </button>

            <button
              type="button"
              className={`tb-icon-btn pause-icon-btn ${globalPaused ? "paused" : ""}`}
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
            </button>

            <button
              type="button"
              className={`tb-icon-btn scale-icon-btn ${isUniformScale ? "uniform" : ""}`}
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
            </button>

            <button
              type="button"
              className={`tb-icon-btn calib-icon-btn ${isPhysical ? "physical" : ""}`}
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
            </button>
          </div>

          <div className="status-bar-right">
            <button
              type="button"
              className="tb-icon-btn close-all-btn"
              onClick={closeAllStreams}
              disabled={!panels.length}
              title="전체 스트림 닫기"
              aria-label="전체 스트림 닫기"
            >
              <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
                <path
                  fill="currentColor"
                  d="M5.3 4.2 4.2 5.3 6.9 8l-2.7 2.7 1.1 1.1L8 9.1l2.7 2.7 1.1-1.1L9.1 8l2.7-2.7-1.1-1.1L8 6.9 5.3 4.2zm7.2 0-1.1 1.1L14.1 8l-2.7 2.7 1.1 1.1L15.2 9.1l2.7 2.7 1.1-1.1L16.3 8l2.7-2.7-1.1-1.1L15.2 6.9l-2.7-2.7z"
                />
              </svg>
            </button>
          </div>
        </div>
      </div>

      {windowModalOpen && (
        <div
          className="modal-backdrop"
          role="dialog"
          aria-modal="true"
          aria-labelledby="time-window-title"
        >
          <div className="modal time-window-modal">
            <div className="modal-head">
              <h3 id="time-window-title">타임윈도우</h3>
              <button
                type="button"
                className="modal-close"
                aria-label="닫기"
                onClick={() => setWindowModalOpen(false)}
              >
                ✕
              </button>
            </div>
            <div className="time-window-modal-body">
              <label>
                표시 구간
                <select
                  value={String(draftWindow)}
                  onChange={(e) => setDraftWindow(Number(e.target.value))}
                >
                  {!TIME_WINDOW_STEPS.includes(
                    draftWindow as (typeof TIME_WINDOW_STEPS)[number],
                  ) && (
                    <option value={String(draftWindow)}>
                      현재 {formatTimeWindowLabel(draftWindow)} ({draftWindow}s)
                    </option>
                  )}
                  {TIME_WINDOW_STEPS.map((sec) => (
                    <option key={sec} value={String(sec)}>
                      {formatTimeWindowLabel(sec)} ({sec}s)
                    </option>
                  ))}
                </select>
              </label>
              <p className="muted">
                줌인/줌아웃은 위 프리셋 간격으로 이동합니다.
              </p>
            </div>
            <div className="modal-actions">
              <button type="button" className="primary" onClick={applyWindowModal}>
                적용
              </button>
              <button type="button" onClick={() => setWindowModalOpen(false)}>
                닫기
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
