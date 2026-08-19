import { useEffect, useState } from "react";
import { api } from "../api/client";

export function FilesPage({ toast }: { toast: (m: string) => void }) {
  const [root, setRoot] = useState<"params" | "environment">("params");
  const [items, setItems] = useState<{ path: string; readonly?: boolean }[]>([]);
  const [file, setFile] = useState("");
  const [content, setContent] = useState("");
  const [readonly, setReadonly] = useState(false);

  async function loadTree(r = root) {
    const data = await api<{ items: { path: string; readonly?: boolean }[] }>(`/api/files?root=${r}`);
    setItems(data.items);
    if (data.items[0]) await open(r, data.items[0].path);
  }
  useEffect(() => {
    loadTree().catch((e: Error) => toast(e.message));
  }, [root, toast]);

  async function open(r: string, path: string) {
    const data = await api<{ content: string; readonly: boolean }>(
      `/api/files/content?root=${r}&path=${encodeURIComponent(path)}`
    );
    setFile(path);
    setContent(data.content);
    setReadonly(data.readonly);
  }

  async function save() {
    try {
      await api("/api/files/content", {
        method: "PUT",
        body: JSON.stringify({
          root,
          path: file,
          content,
          allow_global: readonly ? window.confirm("전역 ID 파일입니다. 저장할까요?") : false,
        }),
      });
      toast("저장됨 (백업 *.bak.<ts>)");
    } catch (e) {
      toast((e as Error).message);
    }
  }

  return (
    <>
      <h2>파일 편집</h2>
      <p className="lead">params / environment 트리. earthworm_global.d 는 기본 읽기 전용입니다.</p>
      <div className="row" style={{ marginBottom: 12 }}>
        <button className={root === "params" ? "primary" : ""} onClick={() => setRoot("params")}>
          params
        </button>
        <button
          className={root === "environment" ? "primary" : ""}
          onClick={() => setRoot("environment")}
        >
          environment
        </button>
      </div>
      <div className="grid cols-2">
        <div className="card file-tree">
          {items.map((it) => (
            <button
              key={it.path}
              className={file === it.path ? "active" : ""}
              onClick={() => void open(root, it.path)}
            >
              {it.path}
            </button>
          ))}
        </div>
        <div className="card">
          <textarea value={content} onChange={(e) => setContent(e.target.value)} />
          <button className="primary" style={{ marginTop: 8 }} onClick={() => void save()}>
            저장
          </button>
        </div>
      </div>
    </>
  );
}
