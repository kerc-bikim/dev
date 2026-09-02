import { useEffect, useRef, useState } from "react";
import { apiPut, type ChannelSummary } from "../api";
import { Hint } from "./Hint";

export function ChannelForm({
  projectId,
  station,
  start,
  channel,
  disabled,
  focusField,
  onDrafted,
}: {
  projectId: number;
  station: string;
  start: string;
  channel: ChannelSummary;
  disabled?: boolean;
  focusField?: string | null;
  onDrafted?: () => void;
}) {
  const [location, setLocation] = useState(channel.location ?? "");
  const [code, setCode] = useState(channel.code ?? "");
  const [depth, setDepth] = useState(String(channel.depth ?? ""));
  const [azimuth, setAzimuth] = useState(String(channel.azimuth ?? ""));
  const [dip, setDip] = useState(String(channel.dip ?? ""));
  const [sampleRate, setSampleRate] = useState(String(channel.sample_rate ?? ""));
  const [sensitivity, setSensitivity] = useState(
    channel.sensitivity == null ? "" : String(channel.sensitivity)
  );
  const [error, setError] = useState<string | null>(null);
  const first = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    setLocation(channel.location ?? "");
    setCode(channel.code ?? "");
    setDepth(String(channel.depth ?? ""));
    setAzimuth(String(channel.azimuth ?? ""));
    setDip(String(channel.dip ?? ""));
    setSampleRate(String(channel.sample_rate ?? ""));
    setSensitivity(channel.sensitivity == null ? "" : String(channel.sensitivity));
  }, [channel]);

  useEffect(() => {
    if (!focusField) return;
    const node = document.querySelector<HTMLInputElement>(`[data-field="${focusField}"]`);
    node?.focus();
    node?.scrollIntoView({ block: "center" });
  }, [focusField, channel.nslc]);

  async function saveDraft() {
    if (disabled) return;
    const az = azimuth === "" ? null : Number(azimuth);
    const dp = dip === "" ? null : Number(dip);
    const rate = sampleRate === "" ? null : Number(sampleRate);
    const dep = depth === "" ? null : Number(depth);
    const sens = sensitivity === "" ? null : Number(sensitivity);
    if (code && !/^[A-Za-z0-9]{3}$/.test(code)) {
      setError("채널 코드는 3자여야 합니다");
      return;
    }
    if (location.length > 2) {
      setError("location은 0–2자여야 합니다");
      return;
    }
    if (az !== null && (Number.isNaN(az) || az < 0 || az > 360)) {
      setError("방위각은 0 ~ 360 이어야 합니다");
      return;
    }
    if (dp !== null && (Number.isNaN(dp) || dp < -90 || dp > 90)) {
      setError("경사는 -90 ~ 90 이어야 합니다");
      return;
    }
    if (rate !== null && (Number.isNaN(rate) || rate <= 0)) {
      setError("샘플링은 0보다 커야 합니다");
      return;
    }
    if (dep !== null && (Number.isNaN(dep) || dep < 0)) {
      setError("깊이는 0 이상이어야 합니다");
      return;
    }
    if (sens !== null && Number.isNaN(sens)) {
      setError("감도는 숫자여야 합니다");
      return;
    }
    if (sens !== null && !channel.has_response) {
      setError("응답이 없어 감도를 바꿀 수 없습니다");
      return;
    }
    setError(null);
    try {
      await apiPut(`/api/projects/${projectId}/draft`, {
        station,
        start_time: start,
        channel: channel.code,
        location: channel.location,
        new_code: code,
        new_location: location,
        depth: dep,
        azimuth: az,
        dip: dp,
        sample_rate: rate,
        sensitivity: sens,
      });
      onDrafted?.();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <section className="nrl-card" id="channel-form">
      <h3>
        채널 {channel.nslc}
      </h3>
      <p className="hint">칸을 벗어나면 초안에만 저장됩니다.</p>
      <label>
        <span>
          코드 <Hint text="3자 SEED 코드입니다. BHE = Broadband / High gain / East." chapter="chapter-7" />
        </span>
        <input
          ref={first}
          data-field="code"
          value={code}
          disabled={disabled}
          onChange={(e) => setCode(e.target.value.toUpperCase())}
          onBlur={saveDraft}
        />
      </label>
      <label>
        <span>
          location <Hint text="0–2자 위치 코드이며 공백과 00은 서로 다릅니다." chapter="chapter-7" />
        </span>
        <input
          data-field="location"
          value={location}
          disabled={disabled}
          onChange={(e) => setLocation(e.target.value)}
          onBlur={saveDraft}
        />
      </label>
      <label>
        <span>
          깊이 (m){" "}
          <Hint
            text="지면 기준 센서 깊이(m). 고도에 더하면 지표면 고도입니다."
            chapter="chapter-7"
          />
        </span>
        <input
          data-field="depth"
          value={depth}
          disabled={disabled}
          onChange={(e) => setDepth(e.target.value)}
          onBlur={saveDraft}
        />
      </label>
      <label>
        <span>
          방위각 <Hint text="북쪽 0°, 동쪽 90° 기준의 수평 방향입니다." chapter="chapter-7" />
        </span>
        <input
          data-field="azimuth"
          value={azimuth}
          disabled={disabled}
          onChange={(e) => setAzimuth(e.target.value)}
          onBlur={saveDraft}
        />
      </label>
      <label>
        <span>
          경사 <Hint text="수평 0°, 위 +90°, 아래 -90°입니다." chapter="chapter-7" />
        </span>
        <input
          data-field="dip"
          value={dip}
          disabled={disabled}
          onChange={(e) => setDip(e.target.value)}
          onBlur={saveDraft}
        />
      </label>
      <label>
        <span>
          샘플링 (Hz) <Hint text="기록계 설정과 일치하는 최종 샘플률입니다." chapter="chapter-7" />
        </span>
        <input
          data-field="sample_rate"
          value={sampleRate}
          disabled={disabled}
          onChange={(e) => setSampleRate(e.target.value)}
          onBlur={saveDraft}
        />
      </label>
      <label>
        <span>
          감도{" "}
          <Hint
            text="InstrumentSensitivity이며 공식 검증 412는 단계 게인 곱과 비교합니다."
            chapter="chapter-7"
          />
        </span>
        <input
          data-field="sensitivity"
          value={sensitivity}
          disabled={disabled || !channel.has_response}
          onChange={(e) => setSensitivity(e.target.value)}
          onBlur={saveDraft}
        />
      </label>
      {error ? <p className="error">{error}</p> : null}
    </section>
  );
}
