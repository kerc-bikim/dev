import { useCallback, useEffect, useMemo, useState } from "react";
import { apiGet, apiPost, apiText, type ChannelSummary, type Me, type NrlStatus, type ResponseCurve } from "../api";
import { NrlPanel } from "./NrlPanel";
import { ResponseCurveChart } from "./ResponseCurveChart";

type Tab = "curve" | "xml";
type OutputUnit = "DIS" | "VEL" | "ACC";

const OUTPUTS: { value: OutputUnit; label: string }[] = [
  { value: "DIS", label: "변위 (DIS)" },
  { value: "VEL", label: "속도 (VEL)" },
  { value: "ACC", label: "가속도 (ACC)" },
];

type ApplyTarget = {
  projectId: number;
  station: string;
  start: string;
  channels: ChannelSummary[];
  selectedNslc: string;
};

export function NrlWorkbench({
  disabled = false,
  apply = null,
  onApplied,
}: {
  disabled?: boolean;
  apply?: ApplyTarget | null;
  onApplied?: () => void;
}) {
  const [sensor, setSensor] = useState<string | null>(null);
  const [datalogger, setDatalogger] = useState<string | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [curve, setCurve] = useState<ResponseCurve | null>(null);
  const [tab, setTab] = useState<Tab>("curve");
  const [output, setOutput] = useState<OutputUnit>("VEL");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [nrlStatus, setNrlStatus] = useState<NrlStatus | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [testResult, setTestResult] = useState<string | null>(null);

  const onSensor = useCallback((value: string | null) => setSensor(value), []);
  const onDatalogger = useCallback((value: string | null) => setDatalogger(value), []);

  useEffect(() => {
    apiGet<NrlStatus>("/api/nrl/status")
      .then(setNrlStatus)
      .catch(() => undefined);
    apiGet<Me>("/api/me")
      .then(setMe)
      .catch(() => undefined);
  }, []);

  const cascade = [sensor, datalogger].filter(Boolean).join(":");
  const siblings = useMemo(() => {
    if (!apply) return [];
    const code = apply.selectedNslc.includes(".")
      ? apply.selectedNslc.split(".")[1]
      : apply.selectedNslc;
    const loc = apply.selectedNslc.includes(".") ? apply.selectedNslc.split(".")[0] : "";
    const band = code.slice(0, 2);
    return apply.channels.filter((ch) => ch.location === loc && ch.code.slice(0, 2) === band);
  }, [apply]);
  const targets = siblings.filter((ch) => checked[ch.nslc] !== false);

  async function loadCurve(nextOutput: OutputUnit = output) {
    return apiGet<ResponseCurve>(
      `/api/nrl/curve?instconfig=${encodeURIComponent(cascade)}&output=${nextOutput}`
    );
  }

  async function loadPreview() {
    if (!cascade) return;
    setBusy(true);
    setError(null);
    try {
      const [xml, nextCurve] = await Promise.all([
        apiText(
          `/api/nrl/combine?format=stationxml-resp&instconfig=${encodeURIComponent(cascade)}`
        ),
        loadCurve(),
      ]);
      setPreview(xml);
      setCurve(nextCurve);
      setTab("curve");
    } catch (err) {
      setPreview(null);
      setCurve(null);
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function onOutput(next: OutputUnit) {
    setOutput(next);
    if (!cascade || !curve) return;
    setBusy(true);
    setError(null);
    try {
      setCurve(await loadCurve(next));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function applyToChannels() {
    if (!apply || !cascade || disabled) return;
    const names = targets.map((ch) => ch.nslc).join(", ");
    if (!window.confirm(`${names} 채널에 NRL 응답을 적용할까요?`)) return;
    setBusy(true);
    setError(null);
    try {
      await apiPost(`/api/projects/${apply.projectId}/apply-nrl`, {
        station: apply.station,
        start_time: apply.start,
        channels: targets.map((ch) => ch.nslc),
        sensor_instconfig: sensor,
        datalogger_instconfig: datalogger,
        replace_existing: true,
      });
      onApplied?.();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="nrl-workbench">
      <p className="hint">
        NRL v2는 서버가 대신 조회합니다. 고유값이 하나뿐인 설정은 묻지 않습니다. 기준 모델은
        Guralp CMG-3T, Quanterra Q330HR 입니다.
        {nrlStatus ? ` · 모드 ${nrlStatus.mode}${nrlStatus.last_ok ? " · 캐시 있음" : ""}` : null}
      </p>
      {me?.role === "admin" ? (
        <p className="wizard-nav">
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              setBusy(true);
              apiPost<{ ok: boolean; status_code: number; elapsed_ms: number; url: string; elements?: string[] }>(
                "/api/nrl/test"
              )
                .then((data) =>
                  setTestResult(
                    `${data.ok ? "성공" : "실패"} HTTP ${data.status_code} · ${data.elapsed_ms} ms · ${data.url}`
                  )
                )
                .catch((err: Error) => setTestResult(err.message))
                .finally(() => setBusy(false));
            }}
          >
            연결 테스트
          </button>
          {testResult ? <span className="hint">{testResult}</span> : null}
        </p>
      ) : null}
      <div className="nrl-grid">
        <NrlPanel element="sensor" onResolved={onSensor} disabled={disabled} />
        <NrlPanel element="datalogger" onResolved={onDatalogger} disabled={disabled} />
      </div>
      {apply && siblings.length > 0 ? (
        <section className="nrl-card">
          <h3>채널에 적용</h3>
          <p className="hint">같은 밴드 3성분을 기본으로 제안합니다. 체크를 해제하면 빼집니다.</p>
          {siblings.map((ch) => (
            <label key={ch.nslc} className="check">
              <input
                type="checkbox"
                checked={checked[ch.nslc] !== false}
                disabled={disabled}
                onChange={(e) => setChecked((prev) => ({ ...prev, [ch.nslc]: e.target.checked }))}
              />
              {ch.nslc}
              {ch.has_response ? " (기존 응답 있음)" : ""}
            </label>
          ))}
          <button
            type="button"
            className="primary"
            disabled={!cascade || disabled || busy || targets.length === 0}
            onClick={applyToChannels}
          >
            채널에 적용
          </button>
          <button
            type="button"
            disabled={!cascade || disabled || busy}
            onClick={() => {
              const name = window.prompt("장비 세트 이름", "광대역 표준세트");
              if (!name || !sensor) return;
              apiPost("/api/equipment-sets", {
                name,
                sensor_instconfig: sensor,
                datalogger_instconfig: datalogger || "",
                channels: siblings.map((ch) => ch.code),
              }).catch((err: Error) => setError(err.message));
            }}
          >
            장비 세트로 저장
          </button>
        </section>
      ) : null}
      <section className="nrl-card">
        <h3>응답 미리보기</h3>
        <p className="mono">{cascade || "센서·기록계 구성을 끝까지 고르세요."}</p>
        <button type="button" className="primary" disabled={!cascade || busy || disabled} onClick={loadPreview}>
          미리보기 불러오기
        </button>
        {error ? <p className="error">{error}</p> : null}
        {curve || preview ? (
          <>
            <div className="tabs" role="tablist" aria-label="응답 미리보기">
              <button
                type="button"
                role="tab"
                aria-selected={tab === "curve"}
                className={tab === "curve" ? "tab active" : "tab"}
                onClick={() => setTab("curve")}
              >
                응답 곡선
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={tab === "xml"}
                className={tab === "xml" ? "tab active" : "tab"}
                onClick={() => setTab("xml")}
              >
                StationXML
              </button>
            </div>
            {tab === "curve" ? (
              <div role="tabpanel">
                <div className="curve-toolbar">
                  <label>
                    출력 단위
                    <select
                      value={output}
                      disabled={busy}
                      onChange={(e) => onOutput(e.target.value as OutputUnit)}
                    >
                      {OUTPUTS.map((item) => (
                        <option key={item.value} value={item.value}>
                          {item.label}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                {curve ? <ResponseCurveChart curve={curve} /> : <p className="hint">곡선을 불러오는 중…</p>}
              </div>
            ) : (
              <div role="tabpanel">{preview ? <pre className="xml">{preview}</pre> : null}</div>
            )}
          </>
        ) : null}
      </section>
    </div>
  );
}
