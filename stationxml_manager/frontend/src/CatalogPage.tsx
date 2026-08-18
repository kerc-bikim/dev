import { useCallback, useEffect, useState } from "react";
import { apiGet, apiSend, type CatalogRow } from "./api";

export function CatalogPage({
  actor,
  onError,
}: {
  actor: string;
  onError: (e: string | null) => void;
}) {
  const [rows, setRows] = useState<CatalogRow[]>([]);
  const [form, setForm] = useState({
    kind: "sensor",
    code: "",
    manufacturer: "",
    model: "",
    sample_rate: "",
    nrl_keys: "",
    description: "",
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
    <div className="page-pad">
      <div className="note">
        센서/기록계는 카탈로그 ID만 선택합니다. NRL에 없으면 채널의 「목록에 없음」으로 사용자
        정의 항목을 만들 수 있습니다. ID를 비우면 자동으로 붙습니다. 사용 중인 항목은 삭제할 수
        없습니다. NRL 키를 나중에 넣어도 채널 응답은 바뀌지 않습니다.
      </div>
      <div className="toolbar">
        <select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
          <option value="sensor">센서</option>
          <option value="datalogger">기록계</option>
        </select>
        <input
          placeholder="ID (선택, 비우면 자동)"
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
          placeholder="설명 (선택)"
          value={form.description}
          onChange={(e) => setForm({ ...form, description: e.target.value })}
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
              setForm({
                ...form,
                code: "",
                manufacturer: "",
                model: "",
                sample_rate: "",
                nrl_keys: "",
                description: "",
              });
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
              <th>출처</th>
              <th>설명</th>
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
                <td>{r.origin === "custom" ? "사용자 정의" : "시드"}</td>
                <td>{r.description || "—"}</td>
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
    </div>
  );
}
