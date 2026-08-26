import { useCallback, useState } from "react";
import { apiText } from "../api";
import { NrlPanel } from "./NrlPanel";

export function NrlWorkbench() {
  const [sensor, setSensor] = useState<string | null>(null);
  const [datalogger, setDatalogger] = useState<string | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const onSensor = useCallback((value: string | null) => setSensor(value), []);
  const onDatalogger = useCallback((value: string | null) => setDatalogger(value), []);

  const cascade = [sensor, datalogger].filter(Boolean).join(":");

  async function loadPreview() {
    if (!cascade) return;
    setBusy(true);
    setError(null);
    try {
      const xml = await apiText(
        `/api/nrl/combine?format=stationxml-resp&instconfig=${encodeURIComponent(cascade)}`
      );
      setPreview(xml);
    } catch (err) {
      setPreview(null);
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
          StationXML-Response 불러오기
        </button>
        {error ? <p className="error">{error}</p> : null}
        {preview ? <pre className="xml">{preview}</pre> : null}
      </section>
    </div>
  );
}
