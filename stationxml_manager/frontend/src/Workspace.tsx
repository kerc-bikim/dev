import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  apiGet,
  apiSend,
  type CatalogRow,
  type ChannelRow,
  type ExportStatus,
  type NetworkRow,
  type StationRow,
} from "./api";
import { ChannelForm } from "./ChannelForm";
import { ResponsePanel } from "./ResponsePanel";
import { StationForm } from "./StationForm";
import { Field, NRL_DISABLED_HINT, canApplyNrl, responseBadge } from "./ui";

type Selection =
  | { kind: "network"; id: number }
  | { kind: "station"; id: number }
  | { kind: "channel"; id: number };

export function Workspace({
  actor,
  onError,
  reloadToken,
  importMessage,
  importWarnings,
  exportWarnings,
  onOpenHelp,
}: {
  actor: string;
  onError: (e: string | null) => void;
  reloadToken: number;
  importMessage: string | null;
  importWarnings: string[];
  exportWarnings: string[];
  onOpenHelp: () => void;
}) {
  const [networks, setNetworks] = useState<NetworkRow[]>([]);
  const [stations, setStations] = useState<StationRow[]>([]);
  const [channels, setChannels] = useState<ChannelRow[]>([]);
  const [catalog, setCatalog] = useState<CatalogRow[]>([]);
  const [status, setStatus] = useState<ExportStatus | null>(null);
  const [query, setQuery] = useState("");
  const [selection, setSelection] = useState<Selection | null>(null);
  const [overlayIds, setOverlayIds] = useState<number[]>([]);
  const [editingChannel, setEditingChannel] = useState<Partial<ChannelRow> | null>(null);
  const [addingStation, setAddingStation] = useState(false);
  const requestId = useRef(0);

  const reload = useCallback(async () => {
    const current = ++requestId.current;
    try {
      const [nets, stas, chs, cat, st] = await Promise.all([
        apiGet<NetworkRow[]>("/api/networks"),
        apiGet<StationRow[]>("/api/stations"),
        apiGet<ChannelRow[]>("/api/channels"),
        apiGet<CatalogRow[]>("/api/catalog"),
        apiGet<ExportStatus>("/api/export/status"),
      ]);
      if (current !== requestId.current) return;
      setNetworks(nets);
      setStations(stas);
      setChannels(chs);
      setCatalog(cat);
      setStatus(st);
      onError(null);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  }, [onError]);

  useEffect(() => {
    void reload();
  }, [reload, reloadToken]);

  const sensors = catalog.filter((c) => c.kind === "sensor");
  const loggers = catalog.filter((c) => c.kind === "datalogger");
  const selectedChannel =
    selection?.kind === "channel"
      ? channels.find((c) => c.id === selection.id) || null
      : null;
  const selectedStation =
    selection?.kind === "station"
      ? stations.find((s) => s.id === selection.id) || null
      : selectedChannel
        ? stations.find((s) => s.id === selectedChannel.station_id) || null
        : null;
  const selectedNetwork =
    selection?.kind === "network"
      ? networks.find((n) => n.id === selection.id) || null
      : selectedStation
        ? networks.find((n) => n.id === selectedStation.network_id) || null
        : null;

  const tree = useMemo(() => {
    const q = query.trim().toLowerCase();
    return networks
      .map((net) => {
        const netStations = stations
          .filter((s) => s.network_id === net.id)
          .map((sta) => {
            const staChannels = channels.filter((c) => c.station_id === sta.id);
            return { sta, channels: staChannels };
          })
          .filter((entry) => {
            if (!q) return true;
            const hitSta =
              entry.sta.code.toLowerCase().includes(q) ||
              (entry.sta.site_name || "").toLowerCase().includes(q);
            const hitCh = entry.channels.some((c) =>
              (c.nslc || "").toLowerCase().includes(q)
            );
            return hitSta || hitCh || net.code.toLowerCase().includes(q);
          })
          .map((entry) => ({
            ...entry,
            channels: q
              ? entry.channels.filter(
                  (c) =>
                    (c.nslc || "").toLowerCase().includes(q) ||
                    entry.sta.code.toLowerCase().includes(q) ||
                    net.code.toLowerCase().includes(q)
                )
              : entry.channels,
          }));
        if (!q) return { net, stations: netStations };
        if (net.code.toLowerCase().includes(q) || netStations.length) {
          return { net, stations: netStations };
        }
        return null;
      })
      .filter((row): row is { net: NetworkRow; stations: { sta: StationRow; channels: ChannelRow[] }[] } =>
        Boolean(row)
      );
  }, [channels, networks, query, stations]);

  const siblings = selectedChannel
    ? channels.filter((c) => c.station_id === selectedChannel.station_id)
    : selectedStation
      ? channels.filter((c) => c.station_id === selectedStation.id)
      : [];

  const toggleOverlay = (id: number, hasResponse: boolean) => {
    if (!hasResponse) return;
    if (overlayIds.includes(id)) {
      setOverlayIds(overlayIds.filter((item) => item !== id));
      return;
    }
    if (overlayIds.length >= 8) {
      onError("겹치기는 최대 8채널입니다");
      return;
    }
    setOverlayIds([...overlayIds, id]);
  };

  const summary = status
    ? `${status.network_count}망 · ${status.station_count}소 · ${status.channel_count}채널 · 응답 ${status.response_count}/${status.channel_count}`
    : "불러오는 중";

  return (
    <div className="workbench">
      <aside className="tree-pane">
        <div className="pane-head">
          <strong>관측망</strong>
          <span className="muted">{summary}</span>
        </div>
        <input
          className="tree-search"
          placeholder="NSLC 검색 (예: KG.AAA.--.HHZ)"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <div className="tree-scroll">
          {tree.length === 0 && (
            <div className="empty-tree">
              <p>아직 채널이 없습니다.</p>
              <button className="secondary" onClick={onOpenHelp}>
                메타데이터 생성 방법
              </button>
            </div>
          )}
          {tree.map(({ net, stations: netStations }) => (
            <div key={net.id} className="tree-net">
              <button
                type="button"
                className={`tree-item net ${selection?.kind === "network" && selection.id === net.id ? "active" : ""}`}
                onClick={() => setSelection({ kind: "network", id: net.id })}
              >
                <span>{net.code}</span>
                <span className="muted">{net.description || "네트워크"}</span>
              </button>
              {netStations.map(({ sta, channels: staChannels }) => (
                <div key={sta.id} className="tree-sta-block">
                  <button
                    type="button"
                    className={`tree-item sta ${selection?.kind === "station" && selection.id === sta.id ? "active" : ""}`}
                    onClick={() => setSelection({ kind: "station", id: sta.id })}
                  >
                    <span>{sta.code}</span>
                    <span className="muted">{sta.site_name || `${sta.latitude.toFixed(2)}, ${sta.longitude.toFixed(2)}`}</span>
                  </button>
                  {staChannels.map((ch) => (
                    <div
                      key={ch.id}
                      className={`tree-item cha selectable ${selectedChannel?.id === ch.id ? "active" : ""}`}
                      onClick={() => setSelection({ kind: "channel", id: ch.id })}
                    >
                      <input
                        type="checkbox"
                        disabled={!ch.has_response}
                        checked={overlayIds.includes(ch.id)}
                        title={ch.has_response ? "겹치기" : "응답이 없어 겹칠 수 없습니다"}
                        onClick={(e) => e.stopPropagation()}
                        onChange={() => toggleOverlay(ch.id, Boolean(ch.has_response))}
                      />
                      <span className="tree-code">{ch.location || "--"}.{ch.channel}</span>
                      <span className={`badge ${ch.has_response ? "ok" : "warn"}`}>
                        {responseBadge(ch.response_source, ch.has_response)}
                      </span>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          ))}
        </div>
        <div className="tree-foot">
          <button
            className="secondary"
            onClick={() => setAddingStation(true)}
          >
            + 관측소
          </button>
          <button
            onClick={() =>
              setEditingChannel({
                station_id: selectedStation?.id,
                location: "",
                sample_rate: 100,
                depth: 0,
                azimuth: 0,
                dip: -90,
              })
            }
          >
            + 채널
          </button>
        </div>
      </aside>

      <section className="inspector-pane">
        <div className="pane-head">
          <strong>
            {selectedChannel
              ? selectedChannel.nslc
              : selectedStation
                ? `${selectedNetwork?.code || ""}.${selectedStation.code}`
                : selectedNetwork
                  ? selectedNetwork.code
                  : "대상을 선택하세요"}
          </strong>
          <button className="secondary" onClick={() => void reload()}>
            새로고침
          </button>
        </div>
        <div className="inspector-scroll">
          {!selection && (
            <div className="welcome">
              <h2>관측망 워크벤치</h2>
              <p>
                왼쪽에서 채널을 고르면 가운데에서 메타데이터를, 오른쪽에서 응답 곡선을 같이 봅니다.
                파일이 있으면 상단 「가져오기」를, 없으면 「+ 관측소」로 시작합니다.
              </p>
              <div className="welcome-actions">
                <button onClick={onOpenHelp}>메타데이터 생성 방법</button>
                <button className="secondary" onClick={() => setAddingStation(true)}>
                  관측소 추가
                </button>
              </div>
            </div>
          )}
          {selection?.kind === "network" && selectedNetwork && (
            <NetworkInspector
              row={selectedNetwork}
              actor={actor}
              onSaved={reload}
              onError={onError}
            />
          )}
          {selection?.kind === "station" && selectedStation && (
            <>
              <StationForm
                key={selectedStation.id}
                value={selectedStation}
                networks={networks}
                onCancel={() => setSelection(null)}
                onSave={async (payload) => {
                  await apiSend("PUT", `/api/stations/${selectedStation.id}`, payload, actor);
                  await reload();
                }}
              />
              <div className="inspector-actions">
                <button
                  className="danger"
                  onClick={async () => {
                    if (!confirm("관측소와 하위 채널을 삭제할까요?")) return;
                    try {
                      await apiSend("DELETE", `/api/stations/${selectedStation.id}`, undefined, actor);
                      setSelection(selectedNetwork ? { kind: "network", id: selectedNetwork.id } : null);
                      await reload();
                    } catch (e) {
                      onError(e instanceof Error ? e.message : String(e));
                    }
                  }}
                >
                  관측소 삭제
                </button>
              </div>
            </>
          )}
          {selectedChannel && (
            <>
            <ChannelInspector
              row={selectedChannel}
              sensors={sensors}
              loggers={loggers}
              actor={actor}
              onEdit={() => setEditingChannel(selectedChannel)}
              onReload={reload}
              onError={onError}
              onDeleted={() => {
                setSelection(
                  selectedStation ? { kind: "station", id: selectedStation.id } : null
                );
              }}
            />
            </>
          )}
          {siblings.length > 0 && (
            <div className="sibling-table">
              <h3>같은 관측소 채널</h3>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th className="check-col">겹치기</th>
                      <th>NSLC</th>
                      <th>시작</th>
                      <th>sps</th>
                      <th>센서</th>
                      <th>기록계</th>
                      <th>응답</th>
                    </tr>
                  </thead>
                  <tbody>
                    {siblings.map((r) => (
                      <tr
                        key={r.id}
                        className={`selectable${selectedChannel?.id === r.id ? " selected" : ""}`}
                        onClick={() => setSelection({ kind: "channel", id: r.id })}
                      >
                        <td className="check-col" onClick={(e) => e.stopPropagation()}>
                          <input
                            type="checkbox"
                            disabled={!r.has_response}
                            checked={overlayIds.includes(r.id)}
                            onChange={() => toggleOverlay(r.id, Boolean(r.has_response))}
                          />
                        </td>
                        <td>{r.nslc}</td>
                        <td>{r.start_time}</td>
                        <td>{r.sample_rate}</td>
                        <td>{r.sensor_id || "—"}</td>
                        <td>{r.datalogger_id || "—"}</td>
                        <td>{responseBadge(r.response_source, r.has_response)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </section>

      <section className="response-pane">
        <ResponsePanel
          rows={channels}
          selectedId={selectedChannel?.id ?? null}
          overlayIds={overlayIds}
          actor={actor}
          onReload={reload}
          onError={onError}
        />
      </section>

      <footer className="status-bar">
        <span>{importMessage || summary}</span>
        {status?.dataless_ok ? (
          <span className="ok">Dataless SEED 가능</span>
        ) : (
          <span className="warn">
            Dataless SEED 불가
            {status?.errors[0] ? ` · ${status.errors[0].reason}` : ""}
          </span>
        )}
        {status?.stationxml_ok ? (
          <span className="ok">StationXML 가능</span>
        ) : (
          <span className="muted">내보낼 채널이 없습니다</span>
        )}
        {importWarnings.slice(0, 2).map((w) => (
          <span key={w} className="warn">
            {w}
          </span>
        ))}
        {exportWarnings.slice(0, 2).map((w) => (
          <span key={w} className="warn">
            {w}
          </span>
        ))}
        <button type="button" className="linkish" onClick={onOpenHelp}>
          도움말
        </button>
      </footer>

      {editingChannel && (
        <ChannelForm
          value={editingChannel}
          stations={stations}
          sensors={sensors}
          loggers={loggers}
          actor={actor}
          onClose={() => setEditingChannel(null)}
          onSave={async (payload) => {
            if (payload.id) {
              await apiSend("PUT", `/api/channels/${payload.id}`, payload, actor);
            } else {
              const created = await apiSend<ChannelRow>("POST", "/api/channels", payload, actor);
              setSelection({ kind: "channel", id: created.id });
            }
            setEditingChannel(null);
            await reload();
          }}
        />
      )}
      {addingStation && (
        <div className="modal-backdrop" onClick={() => setAddingStation(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>관측소 추가</h3>
            <StationForm
              value={{
                network_id: selectedNetwork?.id,
                network_code: selectedNetwork?.code,
                latitude: 0,
                longitude: 0,
                elevation: 0,
              }}
              networks={networks}
              onCancel={() => setAddingStation(false)}
              onSave={async (payload) => {
                const created = await apiSend<StationRow>("POST", "/api/stations", payload, actor);
                setAddingStation(false);
                setSelection({ kind: "station", id: created.id });
                await reload();
              }}
            />
          </div>
        </div>
      )}
    </div>
  );
}

function ChannelInspector({
  row,
  sensors,
  loggers,
  actor,
  onEdit,
  onReload,
  onError,
  onDeleted,
}: {
  row: ChannelRow;
  sensors: CatalogRow[];
  loggers: CatalogRow[];
  actor: string;
  onEdit: () => void;
  onReload: () => Promise<void>;
  onError: (e: string | null) => void;
  onDeleted: () => void;
}) {
  const nrlOk = canApplyNrl(row, sensors, loggers);
  return (
    <>
    <div className="cards">
      <div className="card">
        <h3>위치·시간</h3>
        <dl className="kv">
          <dt>시작</dt>
          <dd>{row.start_time}</dd>
          <dt>끝</dt>
          <dd>{row.end_time || "—"}</dd>
          <dt>sps</dt>
          <dd>{row.sample_rate}</dd>
          <dt>방위각 / 경사</dt>
          <dd>
            {row.azimuth} / {row.dip}
          </dd>
          <dt>심도</dt>
          <dd>{row.depth}</dd>
        </dl>
      </div>
      <div className="card">
        <h3>장비</h3>
        <dl className="kv">
          <dt>센서</dt>
          <dd>
            {row.sensor_id || "없음"} {row.sensor_serial ? `· ${row.sensor_serial}` : ""}
          </dd>
          <dt>기록계</dt>
          <dd>
            {row.datalogger_id || "없음"}{" "}
            {row.datalogger_serial ? `· ${row.datalogger_serial}` : ""}
          </dd>
          <dt>응답</dt>
          <dd>{responseBadge(row.response_source, row.has_response)}</dd>
        </dl>
      </div>
    </div>
      <div className="inspector-actions">
        <button className="secondary" onClick={onEdit}>
          수정
        </button>
        <button
          className="secondary"
          disabled={!nrlOk}
          title={nrlOk ? "NRL 응답 적용" : NRL_DISABLED_HINT}
          onClick={async () => {
            if (!nrlOk) return;
            if (!confirm("NRL 응답을 적용할까요? 기존 응답을 덮어씁니다.")) return;
            try {
              await apiSend("POST", `/api/channels/${row.id}/apply-nrl`, undefined, actor);
              await onReload();
            } catch (e) {
              onError(e instanceof Error ? e.message : String(e));
            }
          }}
        >
          NRL
        </button>
        <button
          className="danger"
          onClick={async () => {
            if (!confirm("이 채널을 삭제할까요?")) return;
            try {
              await apiSend("DELETE", `/api/channels/${row.id}`, undefined, actor);
              onDeleted();
              await onReload();
            } catch (e) {
              onError(e instanceof Error ? e.message : String(e));
            }
          }}
        >
          삭제
        </button>
      </div>
    </>
  );
}

function NetworkInspector({
  row,
  actor,
  onSaved,
  onError,
}: {
  row: NetworkRow;
  actor: string;
  onSaved: () => Promise<void>;
  onError: (e: string | null) => void;
}) {
  const [form, setForm] = useState(row);
  useEffect(() => setForm(row), [row]);
  return (
    <div className="card">
      <h3>네트워크 {row.code}</h3>
      <div className="grid">
        <Field label="설명">
          <input
            value={form.description ?? ""}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
          />
        </Field>
        <Field label="운영기관">
          <input
            value={form.operator_agency ?? ""}
            onChange={(e) => setForm({ ...form, operator_agency: e.target.value })}
          />
        </Field>
        <Field label="공개제한">
          <select
            value={form.restricted_status ?? ""}
            onChange={(e) => setForm({ ...form, restricted_status: e.target.value })}
          >
            <option value="">(없음)</option>
            <option value="open">open</option>
            <option value="closed">closed</option>
            <option value="partial">partial</option>
          </select>
        </Field>
      </div>
      <div className="inspector-actions">
        <button
          className="secondary"
          onClick={async () => {
            try {
              await apiSend("PUT", `/api/networks/${row.id}`, form, actor);
              await onSaved();
            } catch (e) {
              onError(e instanceof Error ? e.message : String(e));
            }
          }}
        >
          저장
        </button>
      </div>
    </div>
  );
}
