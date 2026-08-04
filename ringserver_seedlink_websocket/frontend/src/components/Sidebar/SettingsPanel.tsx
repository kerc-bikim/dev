import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { useAppStore } from "../../store/appStore";
import type { AppSettings } from "../../types";

/** input[type=color] 용 #rrggbb 정규화 */
function normalizeHex(hex: string, fallback = "#3dd6c6"): string {
  const raw = (hex || "").trim();
  if (/^#[0-9a-fA-F]{6}$/.test(raw)) return raw.toLowerCase();
  if (/^#[0-9a-fA-F]{3}$/.test(raw)) {
    const h = raw.slice(1);
    return `#${h[0]}${h[0]}${h[1]}${h[1]}${h[2]}${h[2]}`.toLowerCase();
  }
  if (/^[0-9a-fA-F]{6}$/.test(raw)) return `#${raw.toLowerCase()}`;
  return fallback;
}

export function SettingsPanel() {
  const open = useAppStore((s) => s.settingsOpen);
  const setSettingsOpen = useAppStore((s) => s.setSettingsOpen);
  const settings = useAppStore((s) => s.settings);
  const limits = useAppStore((s) => s.limits);
  const saveSettings = useAppStore((s) => s.saveSettings);
  const estimate = useAppStore((s) => s.estimateMemoryBytes);
  const [testMsg, setTestMsg] = useState("");
  const [testOk, setTestOk] = useState<boolean | null>(null);
  const [testing, setTesting] = useState(false);
  const [draft, setDraft] = useState<AppSettings | null>(settings);

  useEffect(() => {
    if (open) {
      setDraft(settings);
      setTestMsg("");
      setTestOk(null);
    }
  }, [open, settings]);

  if (!open) return null;

  const close = () => setSettingsOpen(false);

  if (!settings || !draft) {
    return (
      <div className="modal-backdrop" role="dialog" aria-modal="true">
        <div className="modal settings-modal">
          <p className="muted">설정 로딩…</p>
        </div>
      </div>
    );
  }

  const mem = estimate();
  const warn = limits && mem > limits.memoryWarnBytes;

  const apply = async () => {
    try {
      await saveSettings({ ...draft, protocol: "datalink" });
      setSettingsOpen(false);
    } catch (e) {
      setTestOk(false);
      setTestMsg(`저장 실패: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const test = async () => {
    setTesting(true);
    setTestMsg("연결 테스트 중…");
    setTestOk(null);
    try {
      await saveSettings({ ringserverUrl: draft.ringserverUrl });
      const res = await api.testRingserver();
      if (res.ok) {
        setTestOk(true);
        setTestMsg(`연결 성공 (${res.status}) ${res.target}`);
      } else {
        setTestOk(false);
        setTestMsg(
          `연결 실패${res.status ? ` (HTTP ${res.status})` : ""}: ${res.error || "알 수 없는 오류"}${
            res.target ? `\n대상: ${res.target}` : ""
          }`,
        );
      }
    } catch (e) {
      setTestOk(false);
      setTestMsg(`연결 테스트 오류: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setTesting(false);
    }
  };

  return (
    <div
      className="modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="settings-modal-title"
    >
      <div className="modal settings-modal">
        <div className="modal-head">
          <h3 id="settings-modal-title">설정</h3>
          <button type="button" className="modal-close" aria-label="닫기" onClick={close}>
            ✕
          </button>
        </div>

        <div className="settings-modal-body settings">
          <label>
            Ringserver URL
            <input
              value={draft.ringserverUrl}
              onChange={(e) => setDraft({ ...draft, ringserverUrl: e.target.value })}
            />
          </label>
          <label>
            FDSNWS URL
            <input
              value={draft.fdsnwsUrl}
              onChange={(e) => setDraft({ ...draft, fdsnwsUrl: e.target.value })}
            />
          </label>
          <label>
            Duration (초) — 최대 {limits?.durationMax ?? 86400}
            <select
              value={
                [15, 30, 60, 120, 180, 240, 300, 600, 900, 1200, 1800, 3600, 7200].includes(
                  draft.durationSec,
                )
                  ? draft.durationSec
                  : draft.durationSec
              }
              onChange={(e) => setDraft({ ...draft, durationSec: Number(e.target.value) })}
            >
              {![15, 30, 60, 120, 180, 240, 300, 600, 900, 1200, 1800, 3600, 7200].includes(
                draft.durationSec,
              ) && (
                <option value={draft.durationSec}>현재 {draft.durationSec}초</option>
              )}
              {[15, 30, 60, 120, 180, 240, 300, 600, 900, 1200, 1800, 3600, 7200].map((sec) => (
                <option key={sec} value={sec}>
                  {sec < 60 ? `${sec}초` : sec < 3600 ? `${sec / 60}분` : `${sec / 3600}시간`} ({sec}s)
                </option>
              ))}
            </select>
          </label>
          <label>
            X축 오른쪽 기준
            <select
              value={draft.xAxisRightAnchor || "lastData"}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  xAxisRightAnchor: e.target.value as "now" | "lastData",
                })
              }
            >
              <option value="now">현재 시간</option>
              <option value="lastData">마지막 데이터</option>
            </select>
          </label>
          <label>
            갱신 인터벌 (ms)
            <input
              type="number"
              min={50}
              max={10000}
              value={draft.refreshIntervalMs}
              onChange={(e) =>
                setDraft({ ...draft, refreshIntervalMs: Number(e.target.value) })
              }
            />
          </label>
          <label>
            최대 패널 (1–{limits?.maxPanelsHard ?? 50})
            <input
              type="number"
              min={1}
              max={limits?.maxPanelsHard ?? 50}
              value={draft.maxPanels}
              onChange={(e) => setDraft({ ...draft, maxPanels: Number(e.target.value) })}
            />
          </label>

          <h3>웨이브폼 색상</h3>
          <div className="color-field-group">
            <span className="color-field-label">채널 팔레트</span>
            <div className="color-swatch-list">
              {draft.waveformColors.palette.map((hex, i) => {
                const safe = normalizeHex(hex);
                return (
                  <label key={i} className="color-swatch-item" title={`채널 색 ${i + 1}`}>
                    <input
                      type="color"
                      value={safe}
                      onChange={(e) => {
                        const next = [...draft.waveformColors.palette];
                        next[i] = e.target.value;
                        setDraft({
                          ...draft,
                          waveformColors: { ...draft.waveformColors, palette: next },
                        });
                      }}
                    />
                    <span className="color-swatch-preview" style={{ background: safe }} />
                    <span className="color-swatch-hex">{safe}</span>
                  </label>
                );
              })}
            </div>
          </div>
          <div className="color-field-row">
            <label className="color-swatch-item">
              <span className="color-field-label">갭 색상</span>
              <input
                type="color"
                value={normalizeHex(draft.waveformColors.gapColor)}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    waveformColors: { ...draft.waveformColors, gapColor: e.target.value },
                  })
                }
              />
              <span
                className="color-swatch-preview"
                style={{ background: normalizeHex(draft.waveformColors.gapColor) }}
              />
              <span className="color-swatch-hex">
                {normalizeHex(draft.waveformColors.gapColor)}
              </span>
            </label>
            <label className="color-swatch-item">
              <span className="color-field-label">선택 하이라이트</span>
              <input
                type="color"
                value={normalizeHex(draft.waveformColors.selectionColor)}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    waveformColors: {
                      ...draft.waveformColors,
                      selectionColor: e.target.value,
                    },
                  })
                }
              />
              <span
                className="color-swatch-preview"
                style={{ background: normalizeHex(draft.waveformColors.selectionColor) }}
              />
              <span className="color-swatch-hex">
                {normalizeHex(draft.waveformColors.selectionColor)}
              </span>
            </label>
          </div>

          <p className={warn ? "warn" : "muted"}>
            예상 버퍼 메모리 ≈ {(mem / (1024 * 1024)).toFixed(1)} MB
            {warn ? " (경고: 512MB 초과 가능)" : ""}
          </p>
        </div>

        {testMsg && (
          <p
            className={`settings-test-msg ${
              testOk === false ? "error" : testOk === true ? "ok" : "muted"
            }`}
            role={testOk === false ? "alert" : undefined}
          >
            {testMsg}
          </p>
        )}

        <div className="modal-actions">
          <button type="button" className="primary" onClick={() => void apply()}>
            저장
          </button>
          <button type="button" disabled={testing} onClick={() => void test()}>
            {testing ? "테스트 중…" : "연결 테스트"}
          </button>
          <button type="button" onClick={close}>
            닫기
          </button>
        </div>
      </div>
    </div>
  );
}
