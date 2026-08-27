import { useEffect, useMemo, useRef, useState } from "react";
import { fetchStreams, type StreamNode } from "../../api/client";
import { useAppStore } from "../../store/appStore";
import { scnlKey } from "../../types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

function TriCheckbox({
  checked,
  indeterminate,
  title,
  onChange,
}: {
  checked: boolean;
  indeterminate?: boolean;
  title?: string;
  onChange: (next: boolean) => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = Boolean(indeterminate) && !checked;
  }, [indeterminate, checked]);
  return (
    <input
      ref={ref}
      type="checkbox"
      className="tree-check"
      title={title}
      checked={checked}
      onChange={(e) => {
        e.stopPropagation();
        onChange(e.target.checked);
      }}
      onClick={(e) => e.stopPropagation()}
    />
  );
}

type Tree = Record<string, Record<string, StreamNode[]>>;

const CHANNEL_PRESETS = [
  { id: "all", label: "전체" },
  { id: "Z", label: "*Z" },
  { id: "N", label: "*N" },
  { id: "E", label: "*E" },
  { id: "HH", label: "HH*" },
  { id: "BH", label: "BH*" },
  { id: "EH", label: "EH*" },
  { id: "HL", label: "HL*" },
  { id: "EL", label: "EL*" },
] as const;

function matchesPreset(channel: string, preset: string): boolean {
  if (preset === "all") return true;
  const ch = channel.toUpperCase();
  if (preset.length === 1) return ch.endsWith(preset);
  return ch.startsWith(preset.toUpperCase());
}

function matchesQuery(node: StreamNode, q: string): boolean {
  if (!q) return true;
  const hay = `${node.network} ${node.station} ${node.location} ${node.channel} ${scnlKey(node)}`.toLowerCase();
  return q
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((token) => hay.includes(token));
}

export function StreamTree() {
  const [streams, setStreams] = useState<StreamNode[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState("");
  const [preset, setPreset] = useState<string>("all");
  const [openNets, setOpenNets] = useState<Set<string>>(new Set());
  const [openStas, setOpenStas] = useState<Set<string>>(new Set());

  const selected = useAppStore((s) => s.selectedTree);
  const toggleTree = useAppStore((s) => s.toggleTree);
  const setTreeKeys = useAppStore((s) => s.setTreeKeys);
  const clearTreeSelection = useAppStore((s) => s.clearTreeSelection);
  const plotSelected = useAppStore((s) => s.plotSelected);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      setStreams(await fetchStreams());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const filtered = useMemo(() => {
    return streams.filter(
      (s) => matchesPreset(s.channel, preset) && matchesQuery(s, query.trim()),
    );
  }, [streams, query, preset]);

  const tree = useMemo(() => {
    const t: Tree = {};
    for (const s of filtered) {
      t[s.network] ||= {};
      t[s.network]![s.station] ||= [];
      t[s.network]![s.station]!.push(s);
    }
    return t;
  }, [filtered]);

  const netNames = useMemo(() => Object.keys(tree).sort(), [tree]);

  // 검색/필터 시 매칭된 노드만 자동 펼침
  useEffect(() => {
    const hasFilter = query.trim().length > 0 || preset !== "all";
    if (!hasFilter) return;
    const nets = new Set<string>();
    const stas = new Set<string>();
    for (const [net, stations] of Object.entries(tree)) {
      nets.add(net);
      for (const sta of Object.keys(stations)) stas.add(`${net}.${sta}`);
    }
    setOpenNets(nets);
    setOpenStas(stas);
  }, [tree, query, preset]);

  const toggleNet = (net: string) => {
    setOpenNets((prev) => {
      const next = new Set(prev);
      if (next.has(net)) next.delete(net);
      else next.add(net);
      return next;
    });
  };

  const toggleSta = (netSta: string) => {
    setOpenStas((prev) => {
      const next = new Set(prev);
      if (next.has(netSta)) next.delete(netSta);
      else next.add(netSta);
      return next;
    });
  };

  const collapseAll = () => {
    setOpenNets(new Set());
    setOpenStas(new Set());
  };

  const expandNetworks = () => {
    setOpenNets(new Set(netNames));
  };

  return (
    <section className="panel-block stream-panel">
      <div className="panel-head">
        <h2>
          Streams
          <span className="count-badge">{filtered.length}/{streams.length}</span>
        </h2>
        <Button type="button" variant="outline" size="sm" onClick={() => void load()} disabled={loading}>
          {loading ? "…" : "새로고침"}
        </Button>
      </div>

      <div className="stream-toolbar">
        <Input
          className="stream-search"
          type="search"
          placeholder="검색: KG AJD HHZ …"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <div className="preset-row">
          {CHANNEL_PRESETS.map((p) => (
            <Button
              key={p.id}
              type="button"
              variant={preset === p.id ? "default" : "outline"}
              size="sm"
              className={cn("preset-chip", preset === p.id && "active")}
              onClick={() => setPreset(p.id)}
            >
              {p.label}
            </Button>
          ))}
        </div>
        <div className="stream-tools">
          <Button type="button" variant="outline" size="sm" onClick={expandNetworks}>
            NET 펼치기
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={collapseAll}>
            접기
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={clearTreeSelection}>
            선택해제
          </Button>
          <span className="muted sel-count">선택 {selected.size}</span>
        </div>
      </div>

      {error && <p className="error">{error}</p>}

      <div className="tree dense">
        {netNames.length === 0 && !loading && (
          <p className="muted">
            {streams.length === 0
              ? "스트림이 없습니다. ringserver URL을 확인하세요."
              : "검색/필터 결과가 없습니다."}
          </p>
        )}
        {netNames.map((net) => {
          const stations = tree[net]!;
          const staNames = Object.keys(stations).sort();
          const netKeys = staNames.flatMap((sta) => stations[sta]!.map(scnlKey));
          const netCount = netKeys.length;
          const netSelected = netKeys.filter((k) => selected.has(k)).length;
          const netAll = netSelected === netCount && netCount > 0;
          const netPartial = netSelected > 0 && !netAll;
          const netOpen = openNets.has(net);
          return (
            <div key={net} className="tree-net">
              <div className="tree-row net-row">
                <button
                  type="button"
                  className="row-expand"
                  onClick={() => toggleNet(net)}
                  aria-expanded={netOpen}
                >
                  <span className="caret">{netOpen ? "▾" : "▸"}</span>
                </button>
                <TriCheckbox
                  checked={netAll}
                  indeterminate={netPartial}
                  title={netAll ? `${net} 전체 해제` : `${net} 하위 전체 선택`}
                  onChange={(on) => setTreeKeys(netKeys, on)}
                />
                <button
                  type="button"
                  className="row-label"
                  onClick={() => toggleNet(net)}
                >
                  <span className="tree-name">{net}</span>
                  <span className="count-badge">
                    {netSelected > 0 ? `${netSelected}/` : ""}
                    {netCount}
                  </span>
                </button>
              </div>
              {netOpen &&
                staNames.map((sta) => {
                  const chans = stations[sta]!;
                  const netSta = `${net}.${sta}`;
                  const staOpen = openStas.has(netSta);
                  const keys = chans.map(scnlKey);
                  const selectedCount = keys.filter((k) => selected.has(k)).length;
                  const allSelected = selectedCount === keys.length && keys.length > 0;
                  const partial = selectedCount > 0 && !allSelected;
                  return (
                    <div key={netSta} className="tree-sta">
                      <div className="tree-row sta-row">
                        <button
                          type="button"
                          className="row-expand"
                          onClick={() => toggleSta(netSta)}
                          aria-expanded={staOpen}
                        >
                          <span className="caret">{staOpen ? "▾" : "▸"}</span>
                        </button>
                        <TriCheckbox
                          checked={allSelected}
                          indeterminate={partial}
                          title={allSelected ? `${sta} 전체 해제` : `${sta} 전체 선택`}
                          onChange={(on) => setTreeKeys(keys, on)}
                        />
                        <button
                          type="button"
                          className="row-label"
                          onClick={() => toggleSta(netSta)}
                        >
                          <span className="tree-name">{sta}</span>
                          <span className="count-badge">
                            {selectedCount > 0 ? `${selectedCount}/` : ""}
                            {chans.length}
                          </span>
                        </button>
                      </div>
                      {staOpen && (
                        <ul>
                          {chans.map((c) => {
                            const key = scnlKey(c);
                            const loc = c.location && c.location !== "--" ? `${c.location}.` : "";
                            return (
                              <li key={key} title={key}>
                                <label>
                                  <input
                                    type="checkbox"
                                    className="tree-check"
                                    checked={selected.has(key)}
                                    onChange={() => toggleTree(c)}
                                  />
                                  <span>
                                    {loc}
                                    {c.channel}
                                  </span>
                                </label>
                              </li>
                            );
                          })}
                        </ul>
                      )}
                    </div>
                  );
                })}
            </div>
          );
        })}
      </div>

      <Button type="button" className="w-full mt-3" onClick={() => void plotSelected()}>
        선택한 채널 표출 ({selected.size})
      </Button>
    </section>
  );
}
