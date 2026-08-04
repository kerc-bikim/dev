import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import { useAppStore } from "../../store/appStore";
import type { LayoutItem } from "../../types";

export function LayoutMenu() {
  const layouts = useAppStore((s) => s.layouts);
  const panels = useAppStore((s) => s.panels);
  const settings = useAppStore((s) => s.settings);
  const loadLayout = useAppStore((s) => s.loadLayout);
  const refresh = useAppStore((s) => s.refreshLayouts);
  const [open, setOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [nameDraft, setNameDraft] = useState("");
  const [mode, setMode] = useState<"none" | "create" | "edit">("none");
  const [msg, setMsg] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) {
        setOpen(false);
        setMode("none");
        setMsg("");
      }
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const selected = layouts.find((l) => l.id === selectedId) || null;

  const currentPayload = () => {
    if (!settings) return null;
    return {
      channels: panels.map((p) => p.scnl),
      durationSec: settings.durationSec,
      refreshIntervalMs: settings.refreshIntervalMs,
      amplitudeMode: settings.amplitudeMode,
      yScaleMode: settings.yScaleMode,
      xAxisRightAnchor: settings.xAxisRightAnchor,
      waveformColors: settings.waveformColors,
    };
  };

  const createLayout = async () => {
    const name = nameDraft.trim();
    const payload = currentPayload();
    if (!name || !payload) {
      setMsg("레이아웃 이름을 입력하세요.");
      return;
    }
    if (!payload.channels.length) {
      setMsg("저장할 채널이 없습니다. 먼저 채널을 표출하세요.");
      return;
    }
    const row = await api.createLayout(name, payload);
    setNameDraft("");
    setMode("none");
    setSelectedId(row.id);
    setMsg(`「${row.name}」을(를) 생성했습니다.`);
    await refresh();
  };

  const deleteLayout = async () => {
    if (!selected) {
      setMsg("삭제할 레이아웃을 목록에서 선택하세요.");
      return;
    }
    if (!confirm(`「${selected.name}」을(를) 삭제할까요?`)) return;
    await api.deleteLayout(selected.id);
    setSelectedId(null);
    setMode("none");
    setMsg(`「${selected.name}」을(를) 삭제했습니다.`);
    await refresh();
  };

  const editLayout = async () => {
    if (!selected) {
      setMsg("수정할 레이아웃을 목록에서 선택하세요.");
      return;
    }
    const payload = currentPayload();
    if (!payload) return;
    const name = nameDraft.trim() || selected.name;
    if (!payload.channels.length) {
      setMsg("수정할 채널이 없습니다. 먼저 채널을 표출하세요.");
      return;
    }
    const row = await api.updateLayout(selected.id, name, payload);
    setNameDraft("");
    setMode("none");
    setSelectedId(row.id);
    setMsg(`「${row.name}」을(를) 수정했습니다.`);
    await refresh();
  };

  const onSelectLayout = (l: LayoutItem) => {
    setSelectedId(l.id);
    setMsg("");
    if (mode === "edit") setNameDraft(l.name);
  };

  const onLoad = async (l: LayoutItem) => {
    setSelectedId(l.id);
    await loadLayout(l);
    setMsg(`「${l.name}」을(를) 불러왔습니다.`);
  };

  return (
    <div className="layout-menu" ref={rootRef}>
      <button
        type="button"
        className={open ? "active" : undefined}
        aria-expanded={open}
        aria-haspopup="true"
        onClick={() => {
          setOpen((v) => !v);
          setMode("none");
          setMsg("");
        }}
      >
        레이아웃
      </button>
      {open && (
        <div className="layout-dropdown" role="menu">
          <div className="layout-actions">
            <button
              type="button"
              className={mode === "create" ? "primary" : undefined}
              onClick={() => {
                setMode("create");
                setNameDraft("");
                setMsg("");
              }}
            >
              생성
            </button>
            <button
              type="button"
              className="danger"
              onClick={() => void deleteLayout()}
            >
              삭제
            </button>
            <button
              type="button"
              className={mode === "edit" ? "primary" : undefined}
              onClick={() => {
                if (!selected) {
                  setMsg("수정할 레이아웃을 목록에서 선택하세요.");
                  return;
                }
                setMode("edit");
                setNameDraft(selected.name);
                setMsg("이름을 고친 뒤 저장하거나, 현재 표출 채널로 덮어씁니다.");
              }}
            >
              수정
            </button>
          </div>

          {mode === "create" && (
            <div className="layout-form">
              <input
                value={nameDraft}
                onChange={(e) => setNameDraft(e.target.value)}
                placeholder="새 레이아웃 이름"
                autoFocus
                onKeyDown={(e) => {
                  if (e.key === "Enter") void createLayout();
                }}
              />
              <button type="button" className="primary" onClick={() => void createLayout()}>
                저장
              </button>
            </div>
          )}

          {mode === "edit" && selected && (
            <div className="layout-form">
              <input
                value={nameDraft}
                onChange={(e) => setNameDraft(e.target.value)}
                placeholder="레이아웃 이름"
                autoFocus
                onKeyDown={(e) => {
                  if (e.key === "Enter") void editLayout();
                }}
              />
              <button type="button" className="primary" onClick={() => void editLayout()}>
                저장
              </button>
            </div>
          )}

          {msg && <p className="layout-msg muted">{msg}</p>}

          <div className="layout-dropdown-list-head">저장한 레이아웃</div>
          <ul className="layout-dropdown-list">
            {layouts.length === 0 && (
              <li className="muted layout-empty">저장된 레이아웃이 없습니다.</li>
            )}
            {layouts.map((l) => (
              <li key={l.id}>
                <button
                  type="button"
                  className={`layout-item ${selectedId === l.id ? "selected" : ""}`}
                  onClick={() => onSelectLayout(l)}
                  onDoubleClick={() => void onLoad(l)}
                >
                  <span className="layout-item-name">{l.name}</span>
                  <span className="layout-item-meta">
                    {l.payload.channels?.length || 0} ch
                  </span>
                </button>
                <button
                  type="button"
                  className="layout-load-btn"
                  title="불러오기"
                  onClick={() => void onLoad(l)}
                >
                  불러오기
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
