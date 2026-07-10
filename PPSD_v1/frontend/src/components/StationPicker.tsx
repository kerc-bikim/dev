import { useEffect, useState } from "react";
import { api, ChannelInfo, NetworkInfo, StationInfo } from "../api/client";

export interface StationSelection {
  network: string;
  station: string;
  location: string;
  channel: string;
}

interface Props {
  value: StationSelection;
  onChange: (v: StationSelection) => void;
}

type Mode = "dropdown" | "manual";

export function StationPicker({ value, onChange }: Props) {
  const [mode, setMode] = useState<Mode>("dropdown");
  const [networks, setNetworks] = useState<NetworkInfo[]>([]);
  const [stations, setStations] = useState<StationInfo[]>([]);
  const [channels, setChannels] = useState<ChannelInfo[]>([]);
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (mode !== "dropdown") return;
    setLoading("networks");
    setError(null);
    api
      .networks()
      .then(setNetworks)
      .catch((e) => setError(String(e.message ?? e)))
      .finally(() => setLoading(null));
  }, [mode]);

  useEffect(() => {
    if (mode !== "dropdown" || !value.network) return;
    setLoading("stations");
    setError(null);
    setStations([]);
    setChannels([]);
    api
      .stations(value.network)
      .then(setStations)
      .catch((e) => setError(String(e.message ?? e)))
      .finally(() => setLoading(null));
  }, [mode, value.network]);

  useEffect(() => {
    if (mode !== "dropdown" || !value.network || !value.station) return;
    setLoading("channels");
    setError(null);
    setChannels([]);
    api
      .channels(value.network, value.station)
      .then(setChannels)
      .catch((e) => setError(String(e.message ?? e)))
      .finally(() => setLoading(null));
  }, [mode, value.network, value.station]);

  const set = (patch: Partial<StationSelection>) =>
    onChange({ ...value, ...patch });

  return (
    <div>
      <div className="toggle-row">
        <span>Input mode:</span>
        <button
          className={mode === "dropdown" ? "active" : ""}
          onClick={() => setMode("dropdown")}
          type="button"
        >
          Dropdown
        </button>
        <button
          className={mode === "manual" ? "active" : ""}
          onClick={() => setMode("manual")}
          type="button"
        >
          Manual
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 10 }}>{error}</div>}

      {mode === "dropdown" ? (
        <>
          <div className="field">
            <label>Network {loading === "networks" && "…"}</label>
            <select
              value={value.network}
              onChange={(e) =>
                set({ network: e.target.value, station: "", channel: "", location: "" })
              }
            >
              <option value="">-- select --</option>
              {networks.map((n) => (
                <option key={n.code} value={n.code}>
                  {n.code}
                  {n.description ? ` — ${n.description}` : ""}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>Station {loading === "stations" && "…"}</label>
            <select
              value={value.station}
              onChange={(e) => set({ station: e.target.value, channel: "", location: "" })}
              disabled={!value.network}
            >
              <option value="">-- select --</option>
              {stations.map((s) => (
                <option key={`${s.network}.${s.code}`} value={s.code}>
                  {s.code}
                  {s.name ? ` — ${s.name}` : ""}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>Location / Channel {loading === "channels" && "…"}</label>
            <select
              value={`${value.location}|${value.channel}`}
              onChange={(e) => {
                const [loc, cha] = e.target.value.split("|");
                set({ location: loc, channel: cha });
              }}
              disabled={!value.station}
            >
              <option value="|">-- select --</option>
              {channels.map((c) => (
                <option
                  key={`${c.location}|${c.channel}`}
                  value={`${c.location}|${c.channel}`}
                >
                  {(c.location || "--") + "." + c.channel}
                  {c.sample_rate ? ` @ ${c.sample_rate} Hz` : ""}
                </option>
              ))}
            </select>
          </div>
        </>
      ) : (
        <>
          <div className="row-2">
            <div className="field">
              <label>Network</label>
              <input
                type="text"
                value={value.network}
                onChange={(e) => set({ network: e.target.value.toUpperCase() })}
                placeholder="e.g. IU"
              />
            </div>
            <div className="field">
              <label>Station</label>
              <input
                type="text"
                value={value.station}
                onChange={(e) => set({ station: e.target.value.toUpperCase() })}
                placeholder="e.g. ANMO"
              />
            </div>
          </div>
          <div className="row-2">
            <div className="field">
              <label>Location</label>
              <input
                type="text"
                value={value.location}
                onChange={(e) => set({ location: e.target.value })}
                placeholder="00 (or empty)"
              />
            </div>
            <div className="field">
              <label>Channel</label>
              <input
                type="text"
                value={value.channel}
                onChange={(e) => set({ channel: e.target.value.toUpperCase() })}
                placeholder="e.g. BHZ"
              />
            </div>
          </div>
        </>
      )}
    </div>
  );
}
