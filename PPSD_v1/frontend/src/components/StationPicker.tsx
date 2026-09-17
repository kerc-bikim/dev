import { useEffect, useState } from "react";
import { api, ChannelInfo, NetworkInfo, StationInfo } from "../api/client";
import { useSettings } from "../settings/SettingsContext";
import type { InputMode } from "../settings/appSettings";
import { ManualNslcInput } from "./ManualNslcInput";
import {
  formatNslc,
  nslcIsCompleteExact,
  parseNslcInput,
} from "../utils/nslc";

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

export function StationPicker({ value, onChange }: Props) {
  const { settings } = useSettings();
  const [mode, setMode] = useState<InputMode>(settings.input_mode);
  const [networks, setNetworks] = useState<NetworkInfo[]>([]);
  const [stations, setStations] = useState<StationInfo[]>([]);
  const [channels, setChannels] = useState<ChannelInfo[]>([]);
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [manualQuery, setManualQuery] = useState(() =>
    value.network && value.station && value.channel ? formatNslc(value) : ""
  );

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

  const selectedManual: ChannelInfo[] =
    value.network && value.station && value.channel
      ? [
          {
            network: value.network,
            station: value.station,
            location: value.location,
            channel: value.channel,
          },
        ]
      : [];

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
          onClick={() => {
            setMode("manual");
            if (value.network && value.station && value.channel) {
              setManualQuery(formatNslc(value));
            }
          }}
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
        <ManualNslcInput
          query={manualQuery}
          singleSelect
          onQueryChange={(text) => {
            setManualQuery(text);
            const parsed = parseNslcInput(text);
            if (parsed && nslcIsCompleteExact(parsed)) {
              onChange({
                network: parsed.network,
                station: parsed.station,
                location: parsed.location,
                channel: parsed.channel,
              });
            }
          }}
          selected={selectedManual}
          onSelectedChange={(chs) => {
            const c = chs[0];
            if (!c) {
              onChange({ network: "", station: "", location: "", channel: "" });
              return;
            }
            onChange({
              network: c.network,
              station: c.station,
              location: c.location,
              channel: c.channel,
            });
          }}
        />
      )}
    </div>
  );
}
