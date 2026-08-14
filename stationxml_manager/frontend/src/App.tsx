import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  apiGet,
  apiSend,
  downloadFile,
  uploadFile,
  type CatalogRow,
  type ChannelRow,
  type HistoryRow,
  type NetworkRow,
  type StationRow,
  type Tab,
} from "./api";

const TABS: { id: Tab; label: string }[] = [
  { id: "channels", label: "채널" },
  { id: "stations", label: "관측소" },
  { id: "networks", label: "네트워크" },
  { id: "catalog", label: "장비 카탈로그" },
  { id: "io", label: "가져오기/내보내기" },
  { id: "history", label: "변경이력" },
];

function useActor() {
  const [actor, setActor] = useState(() => localStorage.getItem("sxm-actor") || "");
  useEffect(() => {
    localStorage.setItem("sxm-actor", actor);
  }, [actor]);
  return [actor, setActor] as const;
}

function useApiKey() {
  const [apiKey, setApiKey] = useState(
    () => localStorage.getItem("sxm-api-key") || ""
  );
  const updateApiKey = useCallback((value: string) => {
    localStorage.setItem("sxm-api-key", value);
    setApiKey(value);
  }, []);
  return [apiKey, updateApiKey] as const;
}

export default function App() {
  const [tab, setTab] = useState<Tab>("channels");
  const [actor, setActor] = useActor();
  const [apiKey, setApiKey] = useApiKey();
  const [error, setError] = useState<string | null>(null);

  return (
    <div className="app">
      <header className="topbar">
        <h1 className="brand">StationXML 메타데이터 관리</h1>
        <nav className="tabs">
          {TABS.map((t) => (
            <button
              key={t.id}
              className={`tab ${tab === t.id ? "active" : ""}`}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>
        <label className="actor">
          작업자
          <input
            value={actor}
            onChange={(e) => setActor(e.target.value)}
            placeholder="이름(선택)"
          />
        </label>
        <label className="actor">
          API 키
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="원격 접속 시"
          />
        </label>
      </header>
      <main className="content">
        {error && <div className="error">{error}</div>}
        {tab === "channels" && <ChannelsTab actor={actor} onError={setError} />}
        {tab === "stations" && <StationsTab actor={actor} onError={setError} />}
        {tab === "networks" && <NetworksTab actor={actor} onError={setError} />}
        {tab === "catalog" && <CatalogTab actor={actor} onError={setError} />}
        {tab === "io" && <IoTab actor={actor} onError={setError} />}
        {tab === "history" && <HistoryTab onError={setError} />}
      </main>
    </div>
  );
}

function ChannelsTab({
  actor,
  onError,
}: {
  actor: string;
  onError: (e: string | null) => void;
}) {
  const [rows, setRows] = useState<ChannelRow[]>([]);
  const [stations, setStations] = useState<StationRow[]>([]);
  const [catalog, setCatalog] = useState<CatalogRow[]>([]);
  const [filter, setFilter] = useState({ network: "", station: "", channel: "" });
  const [editing, setEditing] = useState<Partial<ChannelRow> | null>(null);
  const requestId = useRef(0);

  const reload = useCallback(async () => {
    const currentRequest = ++requestId.current;
    try {
      const q = new URLSearchParams();
      if (filter.network) q.set("network", filter.network);
      if (filter.station) q.set("station", filter.station);
      if (filter.channel) q.set("channel", filter.channel);
      const qs = q.toString();
      const [ch, st, cat] = await Promise.all([
        apiGet<ChannelRow[]>(`/api/channels${qs ? `?${qs}` : ""}`),
        apiGet<StationRow[]>("/api/stations"),
        apiGet<CatalogRow[]>("/api/catalog"),
      ]);
      if (currentRequest !== requestId.current) return;
      setRows(ch);
      setStations(st);
      setCatalog(cat);
      onError(null);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  }, [filter, onError]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const sensors = catalog.filter((c) => c.kind === "sensor");
  const loggers = catalog.filter((c) => c.kind === "datalogger");

  return (
    <>
      <div className="toolbar">
        <input
          placeholder="네트워크"
          value={filter.network}
          onChange={(e) => setFilter({ ...filter, network: e.target.value })}
        />
        <input
          placeholder="관측소"
          value={filter.station}
          onChange={(e) => setFilter({ ...filter, station: e.target.value })}
        />
        <input
          placeholder="채널"
          value={filter.channel}
          onChange={(e) => setFilter({ ...filter, channel: e.target.value })}
        />
        <button className="secondary" onClick={() => void reload()}>
          새로고침
        </button>
        <button
          onClick={() =>
            setEditing({
              location: "",
              sample_rate: 100,
              depth: 0,
              azimuth: 0,
              dip: -90,
            })
          }
        >
          채널 추가
        </button>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>NSLC</th>
              <th>시작</th>
              <th>끝</th>
              <th>sps</th>
              <th>센서</th>
              <th>기록계</th>
              <th>응답</th>
              <th>비고</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{r.nslc}</td>
                <td>{r.start_time}</td>
                <td>{r.end_time || "—"}</td>
                <td>{r.sample_rate}</td>
                <td>{r.sensor_id || "—"}</td>
                <td>{r.datalogger_id || "—"}</td>
                <td>{r.has_response ? r.response_source : "없음"}</td>
                <td>{r.comment || ""}</td>
                <td>
                  <button className="secondary" onClick={() => setEditing(r)}>
                    수정
                  </button>{" "}
                  <button
                    className="secondary"
                    onClick={async () => {
                      if (!confirm("NRL 응답을 적용할까요? 기존 응답을 덮어씁니다.")) return;
                      try {
                        await apiSend("POST", `/api/channels/${r.id}/apply-nrl`, undefined, actor);
                        await reload();
                      } catch (e) {
                        onError(e instanceof Error ? e.message : String(e));
                      }
                    }}
                  >
                    NRL
                  </button>{" "}
                  <button
                    className="danger"
                    onClick={async () => {
                      if (!confirm("이 채널을 삭제할까요?")) return;
                      try {
                        await apiSend("DELETE", `/api/channels/${r.id}`, undefined, actor);
                        await reload();
                      } catch (e) {
                        onError(e instanceof Error ? e.message : String(e));
                      }
                    }}
                  >
                    삭제
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {editing && (
        <ChannelForm
          value={editing}
          stations={stations}
          sensors={sensors}
          loggers={loggers}
          onClose={() => setEditing(null)}
          onSave={async (payload) => {
            if (payload.id) {
              await apiSend("PUT", `/api/channels/${payload.id}`, payload, actor);
            } else {
              await apiSend("POST", "/api/channels", payload, actor);
            }
            setEditing(null);
            await reload();
          }}
        />
      )}
    </>
  );
}

function ChannelForm({
  value,
  stations,
  sensors,
  loggers,
  onClose,
  onSave,
}: {
  value: Partial<ChannelRow>;
  stations: StationRow[];
  sensors: CatalogRow[];
  loggers: CatalogRow[];
  onClose: () => void;
  onSave: (payload: Record<string, unknown>) => Promise<void>;
}) {
  const [form, setForm] = useState(value);
  const [err, setErr] = useState<string | null>(null);
  const set = (k: string, v: unknown) => setForm((p) => ({ ...p, [k]: v }));
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>{form.id ? "채널 수정" : "채널 추가"}</h3>
        {err && <div className="error">{err}</div>}
        <div className="grid">
          <Field label="관측소">
            <select
              value={form.station_id ?? ""}
              onChange={(e) => set("station_id", Number(e.target.value))}
            >
              <option value="">선택</option>
              {stations.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.network_code}.{s.code}
                </option>
              ))}
            </select>
          </Field>
          <Field label="위치코드">
            <input value={form.location ?? ""} onChange={(e) => set("location", e.target.value)} />
          </Field>
          <Field label="채널">
            <input value={form.channel ?? ""} onChange={(e) => set("channel", e.target.value)} />
          </Field>
          <Field label="시작시간">
            <input value={form.start_time ?? ""} onChange={(e) => set("start_time", e.target.value)} />
          </Field>
          <Field label="끝시간">
            <input value={form.end_time ?? ""} onChange={(e) => set("end_time", e.target.value)} />
          </Field>
          <Field label="샘플링레이트">
            <input
              type="number"
              value={form.sample_rate ?? ""}
              onChange={(e) => set("sample_rate", Number(e.target.value))}
            />
          </Field>
          <Field label="방위각">
            <input
              type="number"
              value={form.azimuth ?? ""}
              onChange={(e) => set("azimuth", Number(e.target.value))}
            />
          </Field>
          <Field label="경사">
            <input
              type="number"
              value={form.dip ?? ""}
              onChange={(e) => set("dip", Number(e.target.value))}
            />
          </Field>
          <Field label="심도">
            <input
              type="number"
              value={form.depth ?? 0}
              onChange={(e) => set("depth", Number(e.target.value))}
            />
          </Field>
          <Field label="센서">
            <select
              value={form.sensor_id ?? ""}
              onChange={(e) => set("sensor_id", e.target.value)}
            >
              <option value="">(없음)</option>
              {sensors.map((s) => (
                <option key={s.code} value={s.code}>
                  {s.code}
                </option>
              ))}
            </select>
          </Field>
          <Field label="센서 일련번호">
            <input
              value={form.sensor_serial ?? ""}
              onChange={(e) => set("sensor_serial", e.target.value)}
            />
          </Field>
          <Field label="기록계">
            <select
              value={form.datalogger_id ?? ""}
              onChange={(e) => set("datalogger_id", e.target.value)}
            >
              <option value="">(없음)</option>
              {loggers.map((s) => (
                <option key={s.code} value={s.code}>
                  {s.code} {s.sample_rate ? `(${s.sample_rate} sps)` : ""}
                </option>
              ))}
            </select>
          </Field>
          <Field label="기록계 일련번호">
            <input
              value={form.datalogger_serial ?? ""}
              onChange={(e) => set("datalogger_serial", e.target.value)}
            />
          </Field>
          <Field label="채널설명">
            <input
              value={form.description ?? ""}
              onChange={(e) => set("description", e.target.value)}
            />
          </Field>
          <Field label="비고">
            <input value={form.comment ?? ""} onChange={(e) => set("comment", e.target.value)} />
          </Field>
          <Field label="채널유형">
            <input
              value={form.channel_types ?? ""}
              onChange={(e) => set("channel_types", e.target.value)}
            />
          </Field>
        </div>
        <div className="modal-actions">
          <button className="secondary" onClick={onClose}>
            취소
          </button>
          <button
            onClick={async () => {
              try {
                await onSave(form as Record<string, unknown>);
              } catch (e) {
                setErr(e instanceof Error ? e.message : String(e));
              }
            }}
          >
            저장
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="field">
      {label}
      {children}
    </label>
  );
}

function StationsTab({ actor, onError }: { actor: string; onError: (e: string | null) => void }) {
  const [rows, setRows] = useState<StationRow[]>([]);
  const [networks, setNetworks] = useState<NetworkRow[]>([]);
  const [editing, setEditing] = useState<Partial<StationRow> | null>(null);
  const reload = useCallback(async () => {
    try {
      setRows(await apiGet("/api/stations"));
      setNetworks(await apiGet("/api/networks"));
      onError(null);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  }, [onError]);
  useEffect(() => {
    void reload();
  }, [reload]);
  return (
    <>
      <div className="toolbar">
        <button onClick={() => setEditing({ latitude: 0, longitude: 0, elevation: 0 })}>
          관측소 추가
        </button>
        <span className="muted">관측소 정보는 채널이 아니라 여기서만 수정합니다.</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>네트워크</th>
              <th>관측소</th>
              <th>위도</th>
              <th>경도</th>
              <th>고도</th>
              <th>관측소명</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{r.network_code}</td>
                <td>{r.code}</td>
                <td>{r.latitude}</td>
                <td>{r.longitude}</td>
                <td>{r.elevation}</td>
                <td>{r.site_name}</td>
                <td>
                  <button className="secondary" onClick={() => setEditing(r)}>
                    수정
                  </button>{" "}
                  <button
                    className="danger"
                    onClick={async () => {
                      if (!confirm("관측소와 하위 채널을 삭제할까요?")) return;
                      try {
                        await apiSend("DELETE", `/api/stations/${r.id}`, undefined, actor);
                        await reload();
                      } catch (e) {
                        onError(e instanceof Error ? e.message : String(e));
                      }
                    }}
                  >
                    삭제
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {editing && (
        <div className="modal-backdrop" onClick={() => setEditing(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{editing.id ? "관측소 수정" : "관측소 추가"}</h3>
            <StationForm
              value={editing}
              networks={networks}
              onCancel={() => setEditing(null)}
              onSave={async (payload) => {
                if (payload.id) await apiSend("PUT", `/api/stations/${payload.id}`, payload, actor);
                else await apiSend("POST", "/api/stations", payload, actor);
                setEditing(null);
                await reload();
              }}
            />
          </div>
        </div>
      )}
    </>
  );
}

function StationForm({
  value,
  networks,
  onCancel,
  onSave,
}: {
  value: Partial<StationRow>;
  networks: NetworkRow[];
  onCancel: () => void;
  onSave: (payload: Record<string, unknown>) => Promise<void>;
}) {
  const [form, setForm] = useState(value);
  const [err, setErr] = useState<string | null>(null);
  const set = (k: string, v: unknown) => setForm((p) => ({ ...p, [k]: v }));
  return (
    <>
      {err && <div className="error">{err}</div>}
      <div className="grid">
        <Field label="네트워크">
          <select
            value={form.network_id ?? ""}
            onChange={(e) => set("network_id", Number(e.target.value))}
          >
            <option value="">선택 또는 코드 입력</option>
            {networks.map((n) => (
              <option key={n.id} value={n.id}>
                {n.code}
              </option>
            ))}
          </select>
        </Field>
        <Field label="네트워크 코드">
          <input
            value={form.network_code ?? ""}
            onChange={(e) => set("network_code", e.target.value)}
            placeholder="새 네트워크면 입력"
          />
        </Field>
        <Field label="관측소 코드">
          <input value={form.code ?? ""} onChange={(e) => set("code", e.target.value)} />
        </Field>
        <Field label="위도">
          <input
            type="number"
            value={form.latitude ?? ""}
            onChange={(e) => set("latitude", Number(e.target.value))}
          />
        </Field>
        <Field label="경도">
          <input
            type="number"
            value={form.longitude ?? ""}
            onChange={(e) => set("longitude", Number(e.target.value))}
          />
        </Field>
        <Field label="고도">
          <input
            type="number"
            value={form.elevation ?? 0}
            onChange={(e) => set("elevation", Number(e.target.value))}
          />
        </Field>
        <Field label="관측소명">
          <input value={form.site_name ?? ""} onChange={(e) => set("site_name", e.target.value)} />
        </Field>
        <Field label="위치설명">
          <input
            value={form.site_description ?? ""}
            onChange={(e) => set("site_description", e.target.value)}
          />
        </Field>
        <Field label="시군구">
          <input value={form.site_town ?? ""} onChange={(e) => set("site_town", e.target.value)} />
        </Field>
        <Field label="지역">
          <input value={form.site_region ?? ""} onChange={(e) => set("site_region", e.target.value)} />
        </Field>
        <Field label="국가">
          <input
            value={form.site_country ?? ""}
            onChange={(e) => set("site_country", e.target.value)}
          />
        </Field>
        <Field label="설치환경">
          <input value={form.vault ?? ""} onChange={(e) => set("vault", e.target.value)} />
        </Field>
        <Field label="지질">
          <input value={form.geology ?? ""} onChange={(e) => set("geology", e.target.value)} />
        </Field>
        <Field label="설치일">
          <input
            value={form.creation_date ?? ""}
            onChange={(e) => set("creation_date", e.target.value)}
          />
        </Field>
        <Field label="철거일">
          <input
            value={form.termination_date ?? ""}
            onChange={(e) => set("termination_date", e.target.value)}
          />
        </Field>
      </div>
      <div className="modal-actions">
        <button className="secondary" onClick={onCancel}>
          취소
        </button>
        <button
          onClick={async () => {
            try {
              const payload: Record<string, unknown> = { ...form, network: form.network_code };
              await onSave(payload);
            } catch (e) {
              setErr(e instanceof Error ? e.message : String(e));
            }
          }}
        >
          저장
        </button>
      </div>
    </>
  );
}

function NetworksTab({ actor, onError }: { actor: string; onError: (e: string | null) => void }) {
  const [rows, setRows] = useState<NetworkRow[]>([]);
  const reload = useCallback(async () => {
    try {
      setRows(await apiGet("/api/networks"));
      onError(null);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  }, [onError]);
  useEffect(() => {
    void reload();
  }, [reload]);
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>코드</th>
            <th>설명</th>
            <th>운영기관</th>
            <th>공개제한</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <NetworkEditRow
              key={r.id}
              row={r}
              actor={actor}
              onSaved={reload}
              onError={onError}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function NetworkEditRow({
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
  return (
    <tr>
      <td>{row.code}</td>
      <td>
        <input
          value={form.description ?? ""}
          onChange={(e) => setForm({ ...form, description: e.target.value })}
        />
      </td>
      <td>
        <input
          value={form.operator_agency ?? ""}
          onChange={(e) => setForm({ ...form, operator_agency: e.target.value })}
        />
      </td>
      <td>
        <select
          value={form.restricted_status ?? ""}
          onChange={(e) => setForm({ ...form, restricted_status: e.target.value })}
        >
          <option value="">(없음)</option>
          <option value="open">open</option>
          <option value="closed">closed</option>
          <option value="partial">partial</option>
        </select>
      </td>
      <td>
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
      </td>
    </tr>
  );
}

function CatalogTab({ actor, onError }: { actor: string; onError: (e: string | null) => void }) {
  const [rows, setRows] = useState<CatalogRow[]>([]);
  const [form, setForm] = useState({
    kind: "sensor",
    code: "",
    manufacturer: "",
    model: "",
    sample_rate: "",
    nrl_keys: "",
  });
  const reload = useCallback(async () => {
    try {
      setRows(await apiGet("/api/catalog"));
      onError(null);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  }, [onError]);
  useEffect(() => {
    void reload();
  }, [reload]);
  return (
    <>
      <div className="note">
        센서/기록계는 카탈로그 ID만 선택합니다. 사용 중인 항목은 삭제할 수 없습니다.
      </div>
      <div className="toolbar">
        <select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
          <option value="sensor">센서</option>
          <option value="datalogger">기록계</option>
        </select>
        <input
          placeholder="ID"
          value={form.code}
          onChange={(e) => setForm({ ...form, code: e.target.value })}
        />
        <input
          placeholder="제조사"
          value={form.manufacturer}
          onChange={(e) => setForm({ ...form, manufacturer: e.target.value })}
        />
        <input
          placeholder="모델"
          value={form.model}
          onChange={(e) => setForm({ ...form, model: e.target.value })}
        />
        <input
          placeholder="sps(기록계)"
          value={form.sample_rate}
          onChange={(e) => setForm({ ...form, sample_rate: e.target.value })}
        />
        <input
          placeholder="NRL 키 (선택, | 구분)"
          value={form.nrl_keys}
          onChange={(e) => setForm({ ...form, nrl_keys: e.target.value })}
        />
        <button
          onClick={async () => {
            try {
              await apiSend(
                "POST",
                "/api/catalog",
                {
                  ...form,
                  sample_rate: form.sample_rate ? Number(form.sample_rate) : null,
                },
                actor
              );
              setForm({ ...form, code: "", manufacturer: "", model: "", sample_rate: "", nrl_keys: "" });
              await reload();
            } catch (e) {
              onError(e instanceof Error ? e.message : String(e));
            }
          }}
        >
          추가
        </button>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>종류</th>
              <th>ID</th>
              <th>제조사</th>
              <th>모델</th>
              <th>sps</th>
              <th>NRL</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{r.kind === "sensor" ? "센서" : "기록계"}</td>
                <td>{r.code}</td>
                <td>{r.manufacturer}</td>
                <td>{r.model}</td>
                <td>{r.sample_rate ?? "—"}</td>
                <td>{r.nrl_keys || "—"}</td>
                <td>
                  <button
                    className="danger"
                    onClick={async () => {
                      try {
                        await apiSend("DELETE", `/api/catalog/${r.id}`, undefined, actor);
                        await reload();
                      } catch (e) {
                        onError(e instanceof Error ? e.message : String(e));
                      }
                    }}
                  >
                    삭제
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function IoTab({ actor, onError }: { actor: string; onError: (e: string | null) => void }) {
  const [replaceAll, setReplaceAll] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  return (
    <>
      <div className="note">
        <strong>엑셀 왕복 한계:</strong> 계측기 응답(Response)과 상세 Comment 구조는 StationXML에만
        있습니다. 엑셀은 표 형태의 메타데이터용입니다. StationXML을 올린 뒤 엑셀을 다시 가져와도
        기존 응답은 지우지 않습니다.
      </div>
      <div className="toolbar">
        <label>
          <input
            type="checkbox"
            checked={replaceAll}
            onChange={(e) => setReplaceAll(e.target.checked)}
          />{" "}
          기존 목록을 지우고 가져오기
        </label>
        <input
          type="file"
          accept=".xlsx,.xml,.stationxml"
          onChange={async (e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (!file) return;
            if (
              replaceAll &&
              !confirm(
                "현재 네트워크·관측소·채널 목록을 모두 교체합니다. 계속할까요?"
              )
            ) {
              return;
            }
            try {
              const result = await uploadFile(file, replaceAll, actor);
              setMsg(`가져오기 완료: 추가 ${result.created}, 수정 ${result.updated}`);
              setWarnings(result.warnings || []);
              onError(null);
            } catch (err) {
              onError(err instanceof Error ? err.message : String(err));
            }
          }}
        />
      </div>
      {msg && <p className="ok">{msg}</p>}
      {warnings.map((w) => (
        <p key={w} className="warn">
          {w}
        </p>
      ))}
      <div className="toolbar">
        <button
          onClick={() =>
            void downloadFile("/api/export/stationxml", "inventory.xml").catch((e) =>
              onError(e instanceof Error ? e.message : String(e))
            )
          }
        >
          StationXML 다운로드
        </button>
        <button
          className="secondary"
          onClick={() =>
            void downloadFile("/api/export/xlsx", "inventory.xlsx").catch((e) =>
              onError(e instanceof Error ? e.message : String(e))
            )
          }
        >
          엑셀 다운로드
        </button>
        <button
          className="secondary"
          onClick={() =>
            void downloadFile(
              "/api/template.xlsx",
              "stationxml_template.xlsx"
            ).catch((e) => onError(e instanceof Error ? e.message : String(e)))
          }
        >
          엑셀 템플릿
        </button>
      </div>
    </>
  );
}

function HistoryTab({ onError }: { onError: (e: string | null) => void }) {
  const [rows, setRows] = useState<HistoryRow[]>([]);
  const [filter, setFilter] = useState("");
  const [detail, setDetail] = useState<HistoryRow | null>(null);
  const reload = useCallback(async () => {
    try {
      const q = filter ? `?nslc=${encodeURIComponent(filter)}` : "";
      setRows(await apiGet(`/api/history${q}`));
      onError(null);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  }, [filter, onError]);
  useEffect(() => {
    void reload();
  }, [reload]);
  const pretty = useMemo(() => {
    if (!detail) return "";
    try {
      return JSON.stringify(
        {
          before: detail.before_json ? JSON.parse(detail.before_json) : null,
          after: detail.after_json ? JSON.parse(detail.after_json) : null,
        },
        null,
        2
      );
    } catch {
      return "이력 상세 JSON을 읽을 수 없습니다.";
    }
  }, [detail]);
  return (
    <>
      <div className="toolbar">
        <input
          placeholder="NSLC 필터"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <button className="secondary" onClick={() => void reload()}>
          새로고침
        </button>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>시각</th>
              <th>작업</th>
              <th>대상</th>
              <th>NSLC</th>
              <th>출처</th>
              <th>작업자</th>
              <th>요약</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} onClick={() => setDetail(r)} style={{ cursor: "pointer" }}>
                <td>{r.created_at}</td>
                <td>{r.action}</td>
                <td>{r.entity_type}</td>
                <td>{r.nslc}</td>
                <td>{r.source}</td>
                <td>{r.actor}</td>
                <td>{r.summary}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {detail && <pre className="history-detail">{pretty}</pre>}
    </>
  );
}
