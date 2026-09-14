import { useState } from "react";
import { useSettings } from "../settings/SettingsContext";
import {
  CMAP_OPTIONS,
  DEFAULT_APP_SETTINGS,
  type AppSettings,
} from "../settings/appSettings";
import { PPSDComputeFields } from "./PPSDComputeFields";

interface Props {
  onClose: () => void;
}

export function SettingsModal({ onClose }: Props) {
  const { settings, updateSettings } = useSettings();
  const [draft, setDraft] = useState<AppSettings>(() => ({ ...settings }));

  const patch = (partial: Partial<AppSettings>) =>
    setDraft((prev) => ({ ...prev, ...partial }));

  const handleDone = () => {
    updateSettings(draft);
    onClose();
  };

  const handleCancel = () => {
    onClose();
  };

  return (
    <div className="modal-overlay" onClick={handleCancel}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <h2>설정 (기본값)</h2>
          <button
            type="button"
            className="btn-ghost"
            onClick={handleCancel}
            aria-label="Close settings"
          >
            ✕
          </button>
        </div>

        <div className="modal-body">
          <p className="hint">
            여기서 지정한 값은 <strong>완료</strong>를 누르면 브라우저에 저장되어,
            각 탭을 열 때 기본값으로 계속 적용됩니다. (탭 내에서 개별적으로 다시
            바꿀 수 있습니다.) 취소(✕)하거나 바깥을 클릭하면 변경이 버려집니다.
          </p>

          <div className="section">
            <h3>Station input</h3>
            <div className="field">
              <label>Input mode</label>
              <select
                value={draft.input_mode}
                onChange={(e) =>
                  patch({
                    input_mode: e.target.value === "manual" ? "manual" : "dropdown",
                  })
                }
              >
                <option value="dropdown">Dropdown</option>
                <option value="manual">Manual</option>
              </select>
            </div>
            <p className="hint">
              관측소·채널을 FDSN 목록에서 고를지(Dropdown), 코드를 직접 입력할지
              (Manual) 정합니다. 각 탭을 열 때 이 값이 초기 모드가 됩니다.
            </p>
          </div>

          {/* Percentiles (heatmap) */}
          <div className="section">
            <h3>Percentiles (Single / Multi)</h3>
            <div className="range-row">
              <span>Low</span>
              <input
                type="range"
                min={0}
                max={50}
                step={1}
                value={draft.percentile_low}
                onChange={(e) =>
                  patch({ percentile_low: Number(e.target.value) })
                }
              />
              <span>{draft.percentile_low}</span>
            </div>
            <div className="range-row">
              <span>High</span>
              <input
                type="range"
                min={50}
                max={100}
                step={1}
                value={draft.percentile_high}
                onChange={(e) =>
                  patch({ percentile_high: Number(e.target.value) })
                }
              />
              <span>{draft.percentile_high}</span>
            </div>
          </div>

          {/* Plot options */}
          <div className="section">
            <h3>Plot options</h3>
            <div className="field">
              <label>X axis</label>
              <select
                value={draft.xaxis}
                onChange={(e) =>
                  patch({
                    xaxis: e.target.value as "period" | "frequency",
                  })
                }
              >
                <option value="period">Period [s]</option>
                <option value="frequency">Frequency [Hz]</option>
              </select>
            </div>
            <div className="field">
              <label>Colormap</label>
              <select
                value={draft.cmap}
                onChange={(e) => patch({ cmap: e.target.value })}
              >
                {CMAP_OPTIONS.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>
            <div className="range-row">
              <span>Probability [%] min</span>
              <input
                type="number"
                min={0}
                max={100}
                step={1}
                value={draft.probability_min}
                onChange={(e) => {
                  const v = Number(e.target.value);
                  if (!Number.isFinite(v)) return;
                  patch({
                    probability_min: Math.min(v, draft.probability_max - 0.01),
                  });
                }}
              />
            </div>
            <div className="range-row">
              <span>Probability [%] max</span>
              <input
                type="number"
                min={0}
                max={100}
                step={1}
                value={draft.probability_max}
                onChange={(e) => {
                  const v = Number(e.target.value);
                  if (!Number.isFinite(v)) return;
                  patch({
                    probability_max: Math.max(v, draft.probability_min + 0.01),
                  });
                }}
              />
            </div>
            <p className="hint">
              히트맵·컬러바 Probability [%] 표시 범위입니다. ObsPy 기본과 같이
              0–30을 권장합니다.
            </p>

            <label className="checkbox">
              <input
                type="checkbox"
                checked={draft.show_overlay}
                onChange={(e) => patch({ show_overlay: e.target.checked })}
              />
              Overlay percentile curves
            </label>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={draft.clip_to_percentile}
                onChange={(e) =>
                  patch({ clip_to_percentile: e.target.checked })
                }
              />
              Clip histogram to percentile range
            </label>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={draft.show_noise_models}
                onChange={(e) =>
                  patch({ show_noise_models: e.target.checked })
                }
              />
              Show Peterson NLNM / NHNM
            </label>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={draft.show_mode}
                onChange={(e) => patch({ show_mode: e.target.checked })}
              />
              Show mode curve
            </label>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={draft.show_mean}
                onChange={(e) => patch({ show_mean: e.target.checked })}
              />
              Show mean curve
            </label>
          </div>

          <PPSDComputeFields
            value={{
              ppsd_length: draft.ppsd_length,
              overlap: draft.overlap,
              period_step_octaves: draft.period_step_octaves,
              period_smoothing_width_octaves:
                draft.period_smoothing_width_octaves,
            }}
            onChange={(compute) => patch(compute)}
          />

          {/* Compare */}
          <div className="section">
            <h3>Compare options (Compare Station / Time)</h3>
            <div className="field">
              <label>Default percentiles (comma-separated)</label>
              <input
                type="text"
                value={draft.compare_percentiles}
                onChange={(e) =>
                  patch({ compare_percentiles: e.target.value })
                }
                placeholder="10, 50, 90"
              />
            </div>
          </div>
        </div>

        <div className="modal-footer">
          <button
            type="button"
            className="btn-secondary"
            onClick={() => setDraft({ ...DEFAULT_APP_SETTINGS })}
          >
            기본값으로 초기화
          </button>
          <button
            type="button"
            className="primary modal-done"
            onClick={handleDone}
          >
            완료
          </button>
        </div>
      </div>
    </div>
  );
}
