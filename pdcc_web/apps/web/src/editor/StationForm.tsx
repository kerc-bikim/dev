import { useState } from "react";
import { apiPut, type StationSummary } from "../api";

export function StationForm({
  projectId,
  station,
  disabled,
  onDrafted,
}: {
  projectId: number;
  station: StationSummary;
  disabled?: boolean;
  onDrafted?: () => void;
}) {
  const [latitude, setLatitude] = useState(String(station.latitude ?? ""));
  const [longitude, setLongitude] = useState(String(station.longitude ?? ""));
  const [elevation, setElevation] = useState(String(station.elevation ?? ""));
  const [siteName, setSiteName] = useState(station.site_name ?? "");
  const [error, setError] = useState<string | null>(null);

  async function saveDraft() {
    if (disabled) return;
    setError(null);
    try {
      await apiPut(`/api/projects/${projectId}/draft`, {
        station: station.code,
        start_time: station.start,
        latitude: latitude === "" ? null : Number(latitude),
        longitude: longitude === "" ? null : Number(longitude),
        elevation: elevation === "" ? null : Number(elevation),
        site_name: siteName,
      });
      onDrafted?.();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <section className="nrl-card">
      <h3>관측소 {station.code}</h3>
      <p className="hint">칸을 벗어나면 초안에만 저장됩니다. 서버 버전은 저장을 눌러야 바뀝니다.</p>
      <label>
        사이트명
        <input
          value={siteName}
          disabled={disabled}
          onChange={(e) => setSiteName(e.target.value)}
          onBlur={saveDraft}
        />
      </label>
      <label>
        위도
        <input
          value={latitude}
          disabled={disabled}
          onChange={(e) => setLatitude(e.target.value)}
          onBlur={saveDraft}
        />
      </label>
      <label>
        경도
        <input
          value={longitude}
          disabled={disabled}
          onChange={(e) => setLongitude(e.target.value)}
          onBlur={saveDraft}
        />
      </label>
      <label>
        고도 (m)
        <input
          value={elevation}
          disabled={disabled}
          onChange={(e) => setElevation(e.target.value)}
          onBlur={saveDraft}
        />
      </label>
      {error ? <p className="error">{error}</p> : null}
    </section>
  );
}
