import { useEffect, useState } from "react";
import { api, ChannelInfo, NetworkInfo, StationInfo } from "../api/client";
import { channelId } from "../utils/time";

export interface ChannelTarget {
  network: string;
  station: string;
  location: string;
  channel: string;
  label?: string;
  color?: string;
}

export interface StationRow {
  id: string;
  network: string;
  station: string;
  selectedChannels: string[];
  manualLocation?: string;
  manualChannel?: string;
  label?: string;
  color?: string;
}

const DEFAULT_COLORS = [
  "#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6",
  "#1abc9c", "#e67e22", "#34495e", "#e91e63", "#00bcd4",
];

let _rowId = 0;
function newRowId() {
  return `row-${++_rowId}`;
}

interface Props {
  rows: StationRow[];
  onChange: (rows: StationRow[]) => void;
  showColors?: boolean;
  singleChannel?: boolean;
  singleStation?: boolean;
  manualMode?: boolean;
}

export function expandRowsToTargets(
  rows: StationRow[],
  showColors: boolean
): ChannelTarget[] {
  const targets: ChannelTarget[] = [];
  let colorIdx = 0;
  for (const row of rows) {
    if (!row.network || !row.station || row.selectedChannels.length === 0) continue;
    for (const chKey of row.selectedChannels) {
      const [location, channel] = chKey.split("|");
      const color = showColors
        ? row.color || DEFAULT_COLORS[colorIdx % DEFAULT_COLORS.length]
        : undefined;
      targets.push({
        network: row.network,
        station: row.station,
        location: location ?? "",
        channel: channel ?? "",
        label: row.label,
        color,
      });
      colorIdx++;
    }
  }
  return targets;
}

export function TargetListEditor({
  rows,
  onChange,
  showColors = false,
  singleChannel = false,
  singleStation = false,
  manualMode = false,
}: Props) {
  const [networks, setNetworks] = useState<NetworkInfo[]>([]);
  const [stationsByNet, setStationsByNet] = useState<Record<string, StationInfo[]>>({});
  const [channelsByKey, setChannelsByKey] = useState<Record<string, ChannelInfo[]>>({});
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (manualMode) return;
    setLoading("networks");
    api.networks()
      .then(setNetworks)
      .catch((e) => setError(String(e.message ?? e)))
      .finally(() => setLoading(null));
  }, [manualMode]);

  const loadStations = (network: string) => {
    if (!network || stationsByNet[network]) return;
    setLoading(`stations-${network}`);
    api.stations(network)
      .then((list) => setStationsByNet((m) => ({ ...m, [network]: list })))
      .catch((e) => setError(String(e.message ?? e)))
      .finally(() => setLoading(null));
  };

  const loadChannels = (network: string, station: string) => {
    const key = `${network}|${station}`;
    if (!network || !station || channelsByKey[key]) return;
    setLoading(`channels-${key}`);
    api.channels(network, station)
      .then((list) => setChannelsByKey((m) => ({ ...m, [key]: list })))
      .catch((e) => setError(String(e.message ?? e)))
      .finally(() => setLoading(null));
  };

  const updateRow = (id: string, patch: Partial<StationRow>) => {
    onChange(rows.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  };

  const removeRow = (id: string) => {
    onChange(rows.filter((r) => r.id !== id));
  };

  const addRow = () => {
    const idx = rows.length;
    onChange([
      ...rows,
      {
        id: newRowId(),
        network: "",
        station: "",
        selectedChannels: [],
        color: showColors ? DEFAULT_COLORS[idx % DEFAULT_COLORS.length] : undefined,
      },
    ]);
  };

  return (
    <div>
      {error && <div className="error" style={{ marginBottom: 10 }}>{error}</div>}

      {rows.map((row, rowIdx) => {
        const chKey = `${row.network}|${row.station}`;
        const channels = channelsByKey[chKey] ?? [];
        const stations = stationsByNet[row.network] ?? [];

        return (
          <div key={row.id} className="target-row">
            <div className="target-row-header">
              <span className="target-row-title">Station {rowIdx + 1}</span>
              {rows.length > 1 && (
                <button
                  type="button"
                  className="btn-ghost"
                  onClick={() => removeRow(row.id)}
                >
                  Remove
                </button>
              )}
            </div>

            {manualMode ? (
              <div className="row-2">
                <div className="field">
                  <label>Network</label>
                  <input
                    type="text"
                    value={row.network}
                    onChange={(e) =>
                      updateRow(row.id, {
                        network: e.target.value.toUpperCase(),
                        selectedChannels: [],
                      })
                    }
                    placeholder="IU"
                  />
                </div>
                <div className="field">
                  <label>Station</label>
                  <input
                    type="text"
                    value={row.station}
                    onChange={(e) =>
                      updateRow(row.id, {
                        station: e.target.value.toUpperCase(),
                        selectedChannels: [],
                      })
                    }
                    placeholder="ANMO"
                  />
                </div>
              </div>
            ) : (
              <div className="row-2">
                <div className="field">
                  <label>Network {loading === "networks" && "…"}</label>
                  <select
                    value={row.network}
                    onChange={(e) => {
                      const network = e.target.value;
                      loadStations(network);
                      updateRow(row.id, {
                        network,
                        station: "",
                        selectedChannels: [],
                      });
                    }}
                  >
                    <option value="">-- select --</option>
                    {networks.map((n) => (
                      <option key={n.code} value={n.code}>
                        {n.code}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="field">
                  <label>Station</label>
                  <select
                    value={row.station}
                    onChange={(e) => {
                      const station = e.target.value;
                      loadChannels(row.network, station);
                      updateRow(row.id, { station, selectedChannels: [] });
                    }}
                    disabled={!row.network}
                  >
                    <option value="">-- select --</option>
                    {stations.map((s) => (
                      <option key={s.code} value={s.code}>
                        {s.code}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            )}

            {manualMode ? (
              <div className="row-2">
                <div className="field">
                  <label>Location</label>
                  <input
                    type="text"
                    value={row.manualLocation ?? ""}
                    onChange={(e) => {
                      const manualLocation = e.target.value;
                      const manualChannel = row.manualChannel ?? "";
                      updateRow(row.id, {
                        manualLocation,
                        selectedChannels:
                          manualChannel
                            ? [`${manualLocation}|${manualChannel}`]
                            : [],
                      });
                    }}
                    placeholder="00"
                  />
                </div>
                <div className="field">
                  <label>Channel</label>
                  <input
                    type="text"
                    value={row.manualChannel ?? ""}
                    onChange={(e) => {
                      const manualChannel = e.target.value.toUpperCase();
                      const manualLocation = row.manualLocation ?? "";
                      updateRow(row.id, {
                        manualChannel,
                        selectedChannels:
                          manualChannel
                            ? [`${manualLocation}|${manualChannel}`]
                            : [],
                      });
                    }}
                    placeholder="BHZ"
                  />
                </div>
              </div>
            ) : (
              <div className="field">
                <label>
                  {singleChannel ? "Channel" : "Channels (Ctrl+click for multiple)"}{" "}
                  {loading === `channels-${chKey}` && "…"}
                </label>
                {singleChannel ? (
                  <select
                    value={row.selectedChannels[0] ?? ""}
                    onChange={(e) => {
                      const val = e.target.value;
                      updateRow(row.id, {
                        selectedChannels: val ? [val] : [],
                      });
                    }}
                    disabled={!row.station}
                  >
                    <option value="">-- select --</option>
                    {channels.map((c) => {
                      const val = `${c.location}|${c.channel}`;
                      return (
                        <option key={val} value={val}>
                          {(c.location || "--") + "." + c.channel}
                          {c.sample_rate ? ` @ ${c.sample_rate} Hz` : ""}
                        </option>
                      );
                    })}
                  </select>
                ) : (
                  <select
                    multiple
                    size={4}
                    className="multi-select"
                    value={row.selectedChannels}
                    onChange={(e) => {
                      const selected = Array.from(
                        e.target.selectedOptions,
                        (o) => o.value
                      );
                      updateRow(row.id, { selectedChannels: selected });
                    }}
                    disabled={!row.station}
                  >
                    {channels.map((c) => {
                      const val = `${c.location}|${c.channel}`;
                      return (
                        <option key={val} value={val}>
                          {(c.location || "--") + "." + c.channel}
                          {c.sample_rate ? ` @ ${c.sample_rate} Hz` : ""}
                        </option>
                      );
                    })}
                  </select>
                )}
              </div>
            )}

            {showColors && (
              <div className="row-2">
                <div className="field">
                  <label>Color</label>
                  <div className="color-field">
                    <input
                      type="color"
                      className="color-swatch"
                      value={row.color || DEFAULT_COLORS[rowIdx % DEFAULT_COLORS.length]}
                      onChange={(e) => updateRow(row.id, { color: e.target.value })}
                    />
                    <input
                      type="text"
                      value={row.color || ""}
                      onChange={(e) => updateRow(row.id, { color: e.target.value })}
                      placeholder="#e74c3c"
                    />
                  </div>
                </div>
                <div className="field">
                  <label>Label (optional)</label>
                  <input
                    type="text"
                    value={row.label || ""}
                    onChange={(e) => updateRow(row.id, { label: e.target.value })}
                    placeholder={channelId({
                      network: row.network,
                      station: row.station,
                      location: "",
                      channel: "",
                    })}
                  />
                </div>
              </div>
            )}

            {row.selectedChannels.length > 0 && (
              <div className="chip-row">
                {row.selectedChannels.map((ch) => {
                  const [loc, cha] = ch.split("|");
                  return (
                    <span key={ch} className="chip">
                      {row.network}.{row.station}.{(loc || "--") + "." + cha}
                    </span>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}

      {!singleStation && (
        <button type="button" className="btn-secondary" onClick={addRow}>
          + Add station
        </button>
      )}
    </div>
  );
}

export function createDefaultRow(showColors = false): StationRow {
  return {
    id: newRowId(),
    network: "",
    station: "",
    selectedChannels: [],
    color: showColors ? DEFAULT_COLORS[0] : undefined,
  };
}
