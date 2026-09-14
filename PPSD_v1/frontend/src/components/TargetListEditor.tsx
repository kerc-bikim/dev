import { useEffect, useState } from "react";
import { api, ChannelInfo, NetworkInfo, StationInfo } from "../api/client";
import { channelId } from "../utils/time";
import { ManualNslcInput } from "./ManualNslcInput";
import {
  formatNslc,
  locChaKey,
  nslcIsCompleteExact,
  parseNslcInput,
} from "../utils/nslc";

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
  manualQuery?: string;
  /** Set when this row was created from another row's wildcard search. */
  searchOriginId?: string;
  label?: string;
  color?: string;
}

const DEFAULT_COLORS = [
  "#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6",
  "#1abc9c", "#e67e22", "#34495e", "#e91e63", "#00bcd4",
];

const MAX_TARGETS = 20;

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

function channelsFromRow(row: StationRow): ChannelInfo[] {
  return row.selectedChannels.map((chKey) => {
    const [location, channel] = chKey.split("|");
    return {
      network: row.network,
      station: row.station,
      location: location ?? "",
      channel: channel ?? "",
    };
  });
}

function applySelectedToRows(
  rows: StationRow[],
  originId: string,
  selected: ChannelInfo[],
  opts: { singleStation: boolean; singleChannel: boolean; showColors: boolean }
): StationRow[] {
  let picked = selected;
  if (opts.singleChannel) picked = selected.slice(0, 1);
  if (opts.singleStation && picked.length > 0) {
    const first = picked[0];
    picked = picked.filter(
      (c) => c.network === first.network && c.station === first.station
    );
    if (opts.singleChannel) picked = picked.slice(0, 1);
  }
  if (picked.length > MAX_TARGETS) picked = picked.slice(0, MAX_TARGETS);

  const origin = rows.find((r) => r.id === originId);
  if (!origin) return rows;

  const withoutSpawned = rows.filter((r) => r.searchOriginId !== originId);

  const groups = new Map<string, ChannelInfo[]>();
  for (const c of picked) {
    const key = `${c.network}|${c.station}`;
    const list = groups.get(key) ?? [];
    list.push(c);
    groups.set(key, list);
  }

  if (groups.size === 0) {
    return withoutSpawned.map((r) =>
      r.id === originId
        ? { ...r, selectedChannels: [], searchOriginId: undefined }
        : r
    );
  }

  const entries = [...groups.entries()];
  const [firstKey, firstChs] = entries[0];
  const [net, sta] = firstKey.split("|");
  const originUpdated: StationRow = {
    ...origin,
    network: net,
    station: sta,
    selectedChannels: firstChs.map(locChaKey),
    searchOriginId: undefined,
  };

  if (opts.singleStation || entries.length === 1) {
    return withoutSpawned.map((r) => (r.id === originId ? originUpdated : r));
  }

  const originIdx = withoutSpawned.findIndex((r) => r.id === originId);
  const existingSpawned = rows.filter((r) => r.searchOriginId === originId);
  const spawned: StationRow[] = entries.slice(1).map(([key, chs], i) => {
    const [n, s] = key.split("|");
    const prev = existingSpawned.find((r) => r.network === n && r.station === s);
    if (prev) {
      return {
        ...prev,
        selectedChannels: chs.map(locChaKey),
      };
    }
    return {
      id: newRowId(),
      network: n,
      station: s,
      selectedChannels: chs.map(locChaKey),
      searchOriginId: originId,
      color: opts.showColors
        ? DEFAULT_COLORS[(originIdx + 1 + i) % DEFAULT_COLORS.length]
        : undefined,
      manualQuery: formatNslc({
        network: n,
        station: s,
        location: chs.length === 1 ? chs[0].location : "*",
        channel: chs.length === 1 ? chs[0].channel : "*",
      }),
    };
  });

  const next = [...withoutSpawned];
  next[originIdx] = originUpdated;
  next.splice(originIdx + 1, 0, ...spawned);
  return next;
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
    onChange(rows.filter((r) => r.id !== id && r.searchOriginId !== id));
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

  const selectedForRow = (row: StationRow): ChannelInfo[] => {
    if (row.searchOriginId) return channelsFromRow(row);
    const spawned = rows.filter((r) => r.searchOriginId === row.id);
    return [...channelsFromRow(row), ...spawned.flatMap(channelsFromRow)];
  };

  return (
    <div>
      {error && <div className="error" style={{ marginBottom: 10 }}>{error}</div>}

      {rows.map((row, rowIdx) => {
        const chKey = `${row.network}|${row.station}`;
        const channels = channelsByKey[chKey] ?? [];
        const stations = stationsByNet[row.network] ?? [];
        const firstCh = row.selectedChannels[0];
        const [firstLoc, firstCha] = firstCh ? firstCh.split("|") : ["", ""];
        const query =
          row.manualQuery ??
          (row.network
            ? formatNslc({
                network: row.network,
                station: row.station,
                location: firstLoc || row.manualLocation || "",
                channel: firstCha || row.manualChannel || "",
              })
            : "");

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
              row.searchOriginId ? (
                <p className="hint">
                  와일드카드 검색으로 추가된 스테이션입니다. 채널 선택은 검색을
                  실행한 위 항목에서 체크박스로 변경하세요.
                </p>
              ) : (
              <ManualNslcInput
                query={query}
                singleSelect={singleChannel}
                singleStation={singleStation}
                onQueryChange={(text) => {
                  const parsed = parseNslcInput(text);
                  if (parsed && nslcIsCompleteExact(parsed)) {
                    onChange(
                      applySelectedToRows(
                        rows.map((r) =>
                          r.id === row.id ? { ...r, manualQuery: text } : r
                        ),
                        row.id,
                        [
                          {
                            network: parsed.network,
                            station: parsed.station,
                            location: parsed.location,
                            channel: parsed.channel,
                          },
                        ],
                        { singleStation, singleChannel, showColors }
                      )
                    );
                    return;
                  }
                  updateRow(row.id, { manualQuery: text });
                }}
                selected={selectedForRow(row)}
                onSelectedChange={(selected) => {
                  onChange(
                    applySelectedToRows(rows, row.id, selected, {
                      singleStation,
                      singleChannel,
                      showColors,
                    })
                  );
                }}
              />
              )
            ) : (
              <>
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
              </>
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
