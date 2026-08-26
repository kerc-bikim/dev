import { useCallback, useState } from "react";
import { apiGet, apiText, type ResponseCurve } from "../api";
import { NrlPanel } from "./NrlPanel";
import { ResponseCurveChart } from "./ResponseCurveChart";

type Tab = "curve" | "xml";
type OutputUnit = "DIS" | "VEL" | "ACC";

const OUTPUTS: { value: OutputUnit; label: string }[] = [
  { value: "DIS", label: "변위 (DIS)" },
  { value: "VEL", label: "속도 (VEL)" },
  { value: "ACC", label: "가속도 (ACC)" },
];

export function NrlWorkbench() {
  const [sensor, setSensor] = useState<string | null>(null);
  const [datalogger, setDatalogger] = useState<string | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [curve, setCurve] = useState<ResponseCurve | null>(null);
  const [tab, setTab] = useState<Tab>("curve");
  const [output, setOutput] = useState<OutputUnit>("VEL");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const onSensor = useCallback((value: string | null) => setSensor(value), []);
  const onDatalogger = useCallback((value: string | null) => setDatalogger(value), []);

  const cascade = [sensor, datalogger].filter(Boolean).join(":");

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

  return (
    <div className="workbench">
      <p className="hint">
        NRL v2는 서버가 대신 조회합니다. 고유값이 하나뿐인 설정은 묻지 않습니다. 기준 모델은
        Guralp CMG-3T, Quanterra Q330HR 입니다.
      </p>
      <div className="nrl-grid">
        <NrlPanel element="sensor" onResolved={onSensor} />
        <NrlPanel element="datalogger" onResolved={onDatalogger} />
      </div>
      <section className="nrl-card">
        <h3>응답 미리보기</h3>
        <p className="mono">{cascade || "센서·기록계 구성을 끝까지 고르세요."}</p>
        <button type="button" className="primary" disabled={!cascade || busy} onClick={loadPreview}>
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
