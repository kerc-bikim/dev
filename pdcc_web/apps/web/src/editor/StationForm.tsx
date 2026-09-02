import { useEffect, useState } from "react";
import { apiPut, type StationSummary } from "../api";
import { Hint } from "./Hint";

function datePart(iso: string | null | undefined): string {
  return iso ? iso.slice(0, 10) : "";
}

function latMessage(value: string): string | null {
  if (value === "") return null;
  const n = Number(value);
  if (Number.isNaN(n) || n < -90 || n > 90) return "위도는 -90 ~ 90 이어야 합니다";
  return null;
}

function lonMessage(value: string): string | null {
  if (value === "") return null;
  const n = Number(value);
  if (Number.isNaN(n) || n < -180 || n > 180) return "경도는 -180 ~ 180 이어야 합니다";
  return null;
}

export function StationForm({
  projectId,
  station,
  disabled,
  focusField,
  onDrafted,
}: {
  projectId: number;
  station: StationSummary;
  disabled?: boolean;
  focusField?: string | null;
  onDrafted?: () => void;
}) {
  const [latitude, setLatitude] = useState(String(station.latitude ?? ""));
  const [longitude, setLongitude] = useState(String(station.longitude ?? ""));
  const [elevation, setElevation] = useState(String(station.elevation ?? ""));
  const [siteName, setSiteName] = useState(station.site_name ?? "");
  const [endDate, setEndDate] = useState(datePart(station.end));
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [latErr, setLatErr] = useState<string | null>(null);

  useEffect(() => {
    setLatitude(String(station.latitude ?? ""));
    setLongitude(String(station.longitude ?? ""));
    setElevation(String(station.elevation ?? ""));
    setSiteName(station.site_name ?? "");
    setEndDate(datePart(station.end));
    setConfirm(false);
    setLatErr(null);
  }, [station]);

  useEffect(() => {
    if (!focusField) return;
    const node = document.querySelector<HTMLInputElement>(`#station-form [data-field="${focusField}"]`);
    node?.focus();
    node?.scrollIntoView({ block: "center" });
  }, [focusField, station.station_path]);

  function geoChanged(): boolean {
    const lat = latitude === "" ? null : Number(latitude);
    const lon = longitude === "" ? null : Number(longitude);
    const elev = elevation === "" ? null : Number(elevation);
    return (
      lat !== station.latitude ||
      lon !== station.longitude ||
      elev !== station.elevation ||
      datePart(endDate) !== datePart(station.end)
    );
  }

  async function saveSite() {
    if (disabled) return;
    setError(null);
    try {
      await apiPut(`/api/projects/${projectId}/draft`, {
        station: station.code,
        start_time: station.start,
        site_name: siteName,
      });
      onDrafted?.();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  function onGeoBlur() {
    const latMsg = latMessage(latitude);
    const lonMsg = lonMessage(longitude);
    setLatErr(latMsg);
    if (latMsg || lonMsg) {
      setError(lonMsg ?? latMsg);
      setConfirm(false);
      return;
    }
    if (disabled || !geoChanged()) return;
    setError(null);
    setConfirm(true);
  }

  async function saveGeo(propagate: boolean) {
    if (disabled) return;
    const latMsg = latMessage(latitude);
    if (latMsg) {
      setLatErr(latMsg);
      setError(latMsg);
      return;
    }
    setError(null);
    try {
      await apiPut(`/api/projects/${projectId}/draft`, {
        station: station.code,
        start_time: station.start,
        latitude: latitude === "" ? null : Number(latitude),
        longitude: longitude === "" ? null : Number(longitude),
        elevation: elevation === "" ? null : Number(elevation),
        set_end: true,
        end: endDate ? `${endDate}T00:00:00` : null,
        propagate,
      });
      setConfirm(false);
      onDrafted?.();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <section className="nrl-card" id="station-form">
      <h3>관측소 {station.code}</h3>
      <p className="hint">칸을 벗어나면 초안에만 저장됩니다. 서버 버전은 저장을 눌러야 바뀝니다.</p>
      <label>
        사이트명
        <input
          data-field="site_name"
          value={siteName}
          disabled={disabled}
          onChange={(e) => setSiteName(e.target.value)}
          onBlur={() => saveSite()}
        />
      </label>
      <label>
        시작
        <input data-field="start" value={datePart(station.start)} disabled />
      </label>
      <label>
        <span>
          종료일 <Hint text="현재 운영이면 비워 두세요. 먼 미래 날짜를 넣지 마세요." />
        </span>
        <input
          data-field="end"
          type="date"
          value={endDate}
          disabled={disabled}
          onChange={(e) => setEndDate(e.target.value)}
          onBlur={onGeoBlur}
        />
      </label>
      <label>
        위도
        <input
          data-field="latitude"
          value={latitude}
          disabled={disabled}
          aria-invalid={Boolean(latErr)}
          onChange={(e) => {
            setLatitude(e.target.value);
            setLatErr(latMessage(e.target.value));
          }}
          onBlur={onGeoBlur}
        />
      </label>
      {latErr ? <p className="error">E_LAT · {latErr}</p> : null}
      <label>
        경도
        <input
          data-field="longitude"
          value={longitude}
          disabled={disabled}
          onChange={(e) => setLongitude(e.target.value)}
          onBlur={onGeoBlur}
        />
      </label>
      <label>
        고도 (m)
        <input
          data-field="elevation"
          value={elevation}
          disabled={disabled}
          onChange={(e) => setElevation(e.target.value)}
          onBlur={onGeoBlur}
        />
      </label>
      {confirm ? (
        <div className="lock-banner" role="alertdialog" aria-label="채널 반영 확인">
          <p>채널 좌표·기간도 바꿀까요?</p>
          <div className="wizard-nav">
            <button type="button" className="primary" onClick={() => saveGeo(true)}>
              채널에도 반영
            </button>
            <button type="button" onClick={() => saveGeo(false)}>
              관측소만
            </button>
            <button type="button" onClick={() => setConfirm(false)}>
              취소
            </button>
          </div>
        </div>
      ) : null}
      {error ? <p className="error">{error}</p> : null}
    </section>
  );
}
