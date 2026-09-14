import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { apiGet, apiPost, type EquipmentSet, type Project } from "../api";
import { NrlPanel } from "../nrl/NrlPanel";

const PATTERNS: { label: string; channels: string[] }[] = [
  { label: "BHZ / BHN / BHE", channels: ["BHZ", "BHN", "BHE"] },
  { label: "HHZ / HHN / HHE", channels: ["HHZ", "HHN", "HHE"] },
  { label: "EHZ", channels: ["EHZ"] },
];

const STEPS = ["식별", "이름", "기간", "위치", "장비", "채널", "확인"];

export function StationWizard({
  project,
  onDone,
  onCancel,
}: {
  project: Project;
  onDone: (project: Project) => void;
  onCancel: () => void;
}) {
  const [step, setStep] = useState(0);
  const [station, setStation] = useState("TEST1");
  const [siteName, setSiteName] = useState("Test One");
  const [operator, setOperator] = useState(project.operator ?? "");
  const [startTime, setStartTime] = useState("2009-04-10T00:00:00");
  const [current, setCurrent] = useState(true);
  const [endTime, setEndTime] = useState("");
  const [latitude, setLatitude] = useState("76.35");
  const [longitude, setLongitude] = useState("-41.84");
  const [elevation, setElevation] = useState("80");
  const [depth, setDepth] = useState("0");
  const [location, setLocation] = useState("00");
  const [channels, setChannels] = useState(["BHZ", "BHN", "BHE"]);
  const [custom, setCustom] = useState("");
  const [nrlLater, setNrlLater] = useState(false);
  const [sensor, setSensor] = useState<string | null>(null);
  const [datalogger, setDatalogger] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sets, setSets] = useState<EquipmentSet[]>([]);
  const [saveSet, setSaveSet] = useState(false);
  const [setName, setSetName] = useState("광대역 표준세트");
  const [staleWarn, setStaleWarn] = useState<string | null>(null);

  const onSensor = useCallback((value: string | null) => setSensor(value), []);
  const onDatalogger = useCallback((value: string | null) => setDatalogger(value), []);

  useEffect(() => {
    apiGet<{ sets: EquipmentSet[] }>("/api/equipment-sets")
      .then((data) => setSets(data.sets))
      .catch(() => undefined);
  }, []);

  const preview = useMemo(
    () =>
      channels.map((code) => {
        const last = code.slice(-1);
        const azimuth = last === "E" ? 90 : 0;
        const dip = last === "Z" ? -90 : 0;
        return { code, azimuth, dip };
      }),
    [channels]
  );

  function applySet(item: EquipmentSet) {
    setSensor(item.sensor_instconfig);
    setDatalogger(item.datalogger_instconfig || null);
    setChannels(item.channels.length ? item.channels : ["BHZ", "BHN", "BHE"]);
    setNrlLater(false);
    setStaleWarn(
      item.stale
        ? `이 세트는 옛 NRL 응답입니다 (${item.nrl_version}). 최신 카탈로그와 다를 수 있습니다.`
        : null
    );
    setStep(6);
  }

  function next() {
    setError(null);
    setStep((s) => Math.min(s + 1, STEPS.length - 1));
  }

  async function onFinish(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await apiPost<{ project: Project }>(`/api/projects/${project.id}/wizard`, {
        station,
        site_name: siteName,
        operator: operator || null,
        start_time: startTime,
        current_operation: current,
        end_time: current ? null : endTime || null,
        latitude: Number(latitude),
        longitude: Number(longitude),
        elevation: Number(elevation),
        depth: Number(depth),
        location,
        channels,
        nrl_later: nrlLater,
        sensor_instconfig: nrlLater ? null : sensor,
        datalogger_instconfig: nrlLater ? null : datalogger,
      });
      if (saveSet && sensor) {
        await apiPost("/api/equipment-sets", {
          name: setName,
          sensor_instconfig: sensor,
          datalogger_instconfig: datalogger || "",
          channels,
        });
      }
      onDone(result.project);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="nrl-card wizard" onSubmit={onFinish}>
      <h3>관측소 위저드 · {STEPS[step]}</h3>
      <p className="hint">
        단계 {step + 1} / {STEPS.length}
      </p>
      {step === 0 ? (
        <>
          <label>
            네트워크
            <input value={project.network_code} disabled />
          </label>
          <label>
            관측소 코드
            <input value={station} onChange={(e) => setStation(e.target.value)} maxLength={5} />
          </label>
        </>
      ) : null}
      {step === 1 ? (
        <>
          <label>
            사이트명
            <input value={siteName} onChange={(e) => setSiteName(e.target.value)} />
          </label>
          <label>
            운영기관
            <input value={operator} onChange={(e) => setOperator(e.target.value)} />
          </label>
        </>
      ) : null}
      {step === 2 ? (
        <>
          <label>
            시작
            <input value={startTime} onChange={(e) => setStartTime(e.target.value)} />
          </label>
          <label className="check">
            <input type="checkbox" checked={current} onChange={(e) => setCurrent(e.target.checked)} />
            현재 운영 (종료 없음)
          </label>
          {current ? null : (
            <label>
              종료
              <input value={endTime} onChange={(e) => setEndTime(e.target.value)} />
            </label>
          )}
        </>
      ) : null}
      {step === 3 ? (
        <>
          <label>
            위도
            <input value={latitude} onChange={(e) => setLatitude(e.target.value)} />
          </label>
          <label>
            경도
            <input value={longitude} onChange={(e) => setLongitude(e.target.value)} />
          </label>
          <label>
            고도 (m)
            <input value={elevation} onChange={(e) => setElevation(e.target.value)} />
          </label>
          <label>
            깊이 (m)
            <input value={depth} onChange={(e) => setDepth(e.target.value)} />
          </label>
        </>
      ) : null}
      {step === 4 ? (
        <>
          {sets.length ? (
            <div className="set-list">
              <p className="hint">내 장비 세트</p>
              {sets.map((item) => (
                <button key={item.id} type="button" onClick={() => applySet(item)}>
                  {item.name}
                  {item.stale ? " · 옛 NRL" : ""}
                </button>
              ))}
            </div>
          ) : null}
          <label className="check">
            <input
              type="checkbox"
              checked={nrlLater}
              onChange={(e) => setNrlLater(e.target.checked)}
            />
            나중에 추가
          </label>
          {nrlLater ? (
            <p className="hint">마침 후에 편집기에서 NRL을 붙일 수 있습니다.</p>
          ) : (
            <div className="nrl-grid">
              <NrlPanel element="sensor" onResolved={onSensor} />
              <NrlPanel element="datalogger" onResolved={onDatalogger} />
            </div>
          )}
        </>
      ) : null}
      {step === 5 ? (
        <>
          <label>
            Location
            <input value={location} onChange={(e) => setLocation(e.target.value)} maxLength={2} />
          </label>
          <div className="pattern-row">
            {PATTERNS.map((item) => (
              <button
                key={item.label}
                type="button"
                className={channels.join() === item.channels.join() ? "primary" : undefined}
                onClick={() => setChannels(item.channels)}
              >
                {item.label}
              </button>
            ))}
          </div>
          <label>
            직접 입력 (쉼표)
            <input
              value={custom}
              onChange={(e) => {
                setCustom(e.target.value);
                const next = e.target.value
                  .split(",")
                  .map((part) => part.trim().toUpperCase())
                  .filter(Boolean);
                if (next.length) setChannels(next);
              }}
            />
          </label>
        </>
      ) : null}
      {step === 6 ? (
        <>
          {staleWarn ? <p className="error">{staleWarn}</p> : null}
          <p className="mono">
            {project.network_code}.{station} {startTime}
            {current ? " ~ 현재" : ` ~ ${endTime}`}
          </p>
          <table className="confirm-table">
            <thead>
              <tr>
                <th>채널</th>
                <th>Loc</th>
                <th>방위각</th>
                <th>경사</th>
                <th>응답</th>
              </tr>
            </thead>
            <tbody>
              {preview.map((row) => (
                <tr key={row.code}>
                  <td>{row.code}</td>
                  <td>{location}</td>
                  <td>{row.azimuth}</td>
                  <td>{row.dip}</td>
                  <td>{nrlLater ? "나중에" : "NRL"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {nrlLater ? null : (
            <p className="hint mono">
              {sensor || "센서 없음"}
              {datalogger ? ` : ${datalogger}` : ""}
            </p>
          )}
          <label className="check">
            <input type="checkbox" checked={saveSet} onChange={(e) => setSaveSet(e.target.checked)} />
            이 조합을 내 장비 세트로 저장
          </label>
          {saveSet ? (
            <label>
              세트 이름
              <input value={setName} onChange={(e) => setSetName(e.target.value)} />
            </label>
          ) : null}
        </>
      ) : null}
      {error ? <p className="error">{error}</p> : null}
      <div className="wizard-nav">
        <button type="button" onClick={onCancel} disabled={busy}>
          취소
        </button>
        {step > 0 ? (
          <button type="button" onClick={() => setStep((s) => s - 1)} disabled={busy}>
            이전
          </button>
        ) : null}
        {step < STEPS.length - 1 ? (
          <button type="button" className="primary" onClick={next}>
            다음
          </button>
        ) : (
          <button type="submit" className="primary" disabled={busy}>
            마침
          </button>
        )}
      </div>
    </form>
  );
}
