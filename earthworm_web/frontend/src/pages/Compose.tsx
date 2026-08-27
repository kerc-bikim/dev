import { useEffect, useMemo, useState } from "react";
import {
  api,
  ApiError,
  type ComposeBoard,
  type ComposeInstance,
  type ComposeIssue,
  type FamilySchema,
  type Me,
  type SchemaField,
} from "../api/client";

const PRIORITY_IO = [
  "q3302ew",
  "slink2ew",
  "export_generic",
  "export_scnl",
  "import_generic",
  "import_pasv",
  "tbuf2mseed",
  "mseed2tbuf",
  "ew2ringserver",
  "wave_serverV",
  "ew2mseed",
  "ewmseedarchiver",
];

type SchemaResp = {
  families: Record<string, FamilySchema>;
  common_fields: SchemaField[];
};

function val(v: string | number | undefined): string {
  return v == null ? "" : String(v);
}

export function ComposePage({
  toast,
  running,
  me,
}: {
  toast: (m: string) => void;
  running: boolean;
  me: Me;
}) {
  const canWrite = me.role !== "viewer";
  const [schema, setSchema] = useState<SchemaResp | null>(null);
  const [board, setBoard] = useState<ComposeBoard | null>(null);
  const [issues, setIssues] = useState<ComposeIssue[]>([]);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [rawOpen, setRawOpen] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState("");

  async function load() {
    const [s, b] = await Promise.all([
      api<SchemaResp>("/api/modules/schema"),
      api<ComposeBoard>("/api/compose"),
    ]);
    setSchema(s);
    setBoard(b);
  }
  useEffect(() => {
    load().catch((e: Error) => toast(e.message));
  }, [toast]);

  const grouped = useMemo(() => {
    const map = new Map<string, ComposeInstance[]>();
    for (const inst of board?.instances || []) {
      const list = map.get(inst.family) || [];
      list.push(inst);
      map.set(inst.family, list);
    }
    return map;
  }, [board]);

  function updateSite(patch: Partial<ComposeBoard["site"]>) {
    if (!board) return;
    setBoard({ ...board, site: { ...board.site, ...patch } });
  }

  function updateInst(id: string, patch: Partial<ComposeInstance>) {
    if (!board) return;
    setBoard({
      ...board,
      instances: board.instances.map((i) => (i.id === id ? { ...i, ...patch } : i)),
    });
  }

  function setValue(id: string, key: string, value: string) {
    if (!board) return;
    setBoard({
      ...board,
      instances: board.instances.map((i) =>
        i.id === id ? { ...i, values: { ...i.values, [key]: value } } : i
      ),
    });
  }

  async function addFamily(family: string) {
    if (!board) return;
    try {
      const sug = await api<{ family: string; id: string; values: Record<string, string | number>; enabled: boolean }>(
        "/api/compose/suggest",
        { method: "POST", body: JSON.stringify({ family, board }) }
      );
      const spec = schema?.families[family];
      if (!spec?.fleet && board.instances.some((i) => i.family === family)) {
        setOpen((o) => ({ ...o, [board.instances.find((i) => i.family === family)!.id]: true }));
        toast("이미 카드가 있습니다");
        return;
      }
      const inst: ComposeInstance = {
        family: sug.family,
        id: sug.id,
        enabled: false,
        values: sug.values,
        raw: "",
      };
      setBoard({ ...board, instances: [...board.instances, inst] });
      setOpen((o) => ({ ...o, [inst.id]: true }));
    } catch (e) {
      toast((e as Error).message);
    }
  }

  function removeInst(id: string) {
    if (!board) return;
    if (id === "statmgr") {
      toast("statmgr 는 삭제할 수 없습니다");
      return;
    }
    setBoard({ ...board, instances: board.instances.filter((i) => i.id !== id) });
  }

  async function review() {
    if (!board) return;
    setBusy(true);
    try {
      const res = await api<{ ok: boolean; issues: ComposeIssue[] }>("/api/compose/validate", {
        method: "POST",
        body: JSON.stringify(board),
      });
      setIssues(res.issues);
      toast(res.ok ? "검토 통과" : "검토에 오류가 있습니다");
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function apply() {
    if (!board) return;
    setBusy(true);
    try {
      const res = await api<{ ok: boolean; compose_revision: number; restart_needed?: boolean; issues: ComposeIssue[] }>(
        "/api/compose/apply",
        { method: "POST", body: JSON.stringify({ ...board, reconfigure: false }) }
      );
      setIssues(res.issues || []);
      toast(
        res.restart_needed
          ? `적용됨 (rev ${res.compose_revision}). 기동 중 모듈은 재시작이 필요합니다.`
          : `적용됨 (rev ${res.compose_revision})`
      );
      await load();
    } catch (e) {
      if (e instanceof ApiError && e.issues?.length) setIssues(e.issues);
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function start() {
    setBusy(true);
    try {
      await api("/api/control/start", { method: "POST" });
      toast("startstop 을 기동했습니다");
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!board || !schema) return <p className="lead">구성 보드를 불러오는 중…</p>;

  const errors = issues.filter((i) => i.level !== "warning");
  const warnings = issues.filter((i) => i.level === "warning");

  return (
    <>
      <h2>구성 보드</h2>
      <p className="lead">
        우선 I/O 모듈을 한 창에서 채운 뒤 검토 → 적용 → 시작합니다. 적용과 시작은 분리되어 있습니다.
        꺼진 카드의 빈 필드는 경고이며, 켠 뒤에만 적용을 막습니다.
        {running ? " startstop 이 살아 있으면 적용은 파일만 기록합니다." : ""}
      </p>
      <div className="card">
        <h3>사이트 공통</h3>
        <div className="grid cols-4">
          <div>
            <label>Inst</label>
            <input value={board.site.installation} disabled />
          </div>
          <div>
            <label>HeartbeatInt</label>
            <input
              type="number"
              value={board.site.heartbeat_int}
              disabled={!canWrite}
              onChange={(e) => updateSite({ heartbeat_int: Number(e.target.value) })}
            />
          </div>
          <div>
            <label>LogFile</label>
            <input
              value={board.site.log_file}
              disabled={!canWrite}
              onChange={(e) => updateSite({ log_file: e.target.value })}
            />
          </div>
          <div>
            <label>기본 WAVE_RING</label>
            <select
              value={board.site.default_wave_ring}
              disabled={!canWrite}
              onChange={(e) => updateSite({ default_wave_ring: e.target.value })}
            >
              {(board.rings.length ? board.rings : ["WAVE_RING"]).map((r) => (
                <option key={r}>{r}</option>
              ))}
            </select>
          </div>
        </div>
        <label className="row" style={{ marginTop: 8 }}>
          <input
            type="checkbox"
            checked={board.site.propagate_heartbeat}
            disabled={!canWrite}
            onChange={(e) => updateSite({ propagate_heartbeat: e.target.checked })}
          />
          이 적용에서 HeartbeatInt 를 모든 .d 에 씀
        </label>
        <p className="lead" style={{ margin: "8px 0 0" }}>
          statmgr 는 필수입니다. 끄면 하트비트 감시가 없어집니다.
        </p>
      </div>
      <div className="compose-layout">
        <div className="card palette">
          <h3>팔레트</h3>
          <p className="lead">우선 12. fleet 는 + 로 인스턴스를 늘립니다.</p>
          {PRIORITY_IO.map((fam) => {
            const spec = schema.families[fam];
            return (
              <button
                key={fam}
                disabled={!canWrite}
                onClick={() => void addFamily(fam)}
                title={spec?.fleet ? "인스턴스 추가" : "카드 하나"}
              >
                {spec?.label || fam} {spec?.fleet ? "+" : ""}
              </button>
            );
          })}
          <p className="lead" style={{ marginTop: 12 }}>
            제어·진단은 대시보드와 링 모니터를 쓰세요. 기타 bin 등록은 파일 편집으로 우회합니다.
          </p>
        </div>
        <div>
          <div className="row" style={{ marginBottom: 8 }}>
            <input
              placeholder="필터 (패밀리·이름)"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              style={{ maxWidth: 280 }}
            />
          </div>
          {PRIORITY_IO.map((fam) => {
            const cards = (grouped.get(fam) || []).filter(
              (i) =>
                !filter ||
                i.id.includes(filter) ||
                i.family.includes(filter)
            );
            if (!cards.length && filter) return null;
            return (
              <div key={fam}>
                {cards.map((inst) => {
                  const spec = schema.families[inst.family];
                  const fields = spec?.fields || [];
                  const instIssues = issues.filter((x) => x.instance === inst.id);
                  return (
                    <div className="card instance-card" key={inst.id}>
                      <div className="row" style={{ justifyContent: "space-between" }}>
                        <button
                          className="ghost"
                          onClick={() => setOpen((o) => ({ ...o, [inst.id]: !o[inst.id] }))}
                        >
                          {open[inst.id] === false ? "▸" : "▾"} {inst.id}
                          <span className="lead"> {spec?.label || inst.family}</span>
                        </button>
                        <div className="row">
                          <button
                            className={`toggle ${inst.enabled ? "on" : ""}`}
                            disabled={!canWrite}
                            onClick={() => updateInst(inst.id, { enabled: !inst.enabled })}
                            title="활성"
                          />
                          <button disabled={!canWrite} onClick={() => removeInst(inst.id)}>
                            삭제
                          </button>
                        </div>
                      </div>
                      {instIssues.length > 0 && (
                        <ul>
                          {instIssues.map((x, i) => (
                            <li key={i} className={x.level === "warning" ? "hb-off" : "hb-bad"}>
                              {x.message}
                            </li>
                          ))}
                        </ul>
                      )}
                      {open[inst.id] !== false && (
                        <div className="grid cols-2" style={{ marginTop: 8 }}>
                          <div>
                            <label>MyModuleId</label>
                            <input value={val(inst.values.MyModuleId) || `MOD_${inst.id.toUpperCase()}`} disabled />
                          </div>
                          <div>
                            <label>RingName</label>
                            <select
                              value={val(inst.values.RingName || inst.values.InRing) || board.site.default_wave_ring}
                              disabled={!canWrite}
                              onChange={(e) => setValue(inst.id, inst.values.InRing != null ? "InRing" : "RingName", e.target.value)}
                            >
                              {board.rings.map((r) => (
                                <option key={r}>{r}</option>
                              ))}
                            </select>
                          </div>
                          <div>
                            <label>HeartbeatInt</label>
                            <input
                              value={val(inst.values.HeartbeatInt)}
                              disabled={!canWrite}
                              onChange={(e) => setValue(inst.id, "HeartbeatInt", e.target.value)}
                            />
                          </div>
                          <div>
                            <label>LogFile</label>
                            <input
                              value={val(inst.values.LogFile)}
                              disabled={!canWrite}
                              onChange={(e) => setValue(inst.id, "LogFile", e.target.value)}
                            />
                          </div>
                          {fields.map((f) => (
                            <div key={f.key} className={f.type === "lines" ? "span-2" : ""}>
                              <label>
                                {f.label || f.key}
                                {f.required ? " *" : ""}
                              </label>
                              {f.type === "lines" ? (
                                <textarea
                                  value={val(inst.values[f.key])}
                                  disabled={!canWrite}
                                  onChange={(e) => setValue(inst.id, f.key, e.target.value)}
                                  style={{ minHeight: 80 }}
                                />
                              ) : (
                                <input
                                  type={f.type === "secret" ? "password" : "text"}
                                  value={val(inst.values[f.key])}
                                  disabled={!canWrite}
                                  onChange={(e) => setValue(inst.id, f.key, e.target.value)}
                                />
                              )}
                            </div>
                          ))}
                          <div className="span-2">
                            <button
                              className="ghost"
                              onClick={() => setRawOpen((o) => ({ ...o, [inst.id]: !o[inst.id] }))}
                            >
                              고급 · 원문 .d
                            </button>
                            {rawOpen[inst.id] && (
                              <textarea
                                value={inst.raw || ""}
                                disabled
                                style={{ minHeight: 140, marginTop: 8 }}
                              />
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
      </div>
      <div className="card apply-bar">
        <div>
          {errors.length ? (
            <span className="hb-bad">오류 {errors.length}</span>
          ) : (
            <span className="hb-ok">오류 없음</span>
          )}
          {warnings.length ? <span className="hb-off"> · 경고 {warnings.length}</span> : null}
        </div>
        <div className="row">
          <button disabled={busy} onClick={() => void review()}>
            검토
          </button>
          <button className="primary" disabled={!canWrite || busy} onClick={() => void apply()}>
            적용
          </button>
          <button className="primary" disabled={!canWrite || busy || running} onClick={() => void start()}>
            시작
          </button>
        </div>
      </div>
    </>
  );
}
