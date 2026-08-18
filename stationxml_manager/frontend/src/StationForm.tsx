import { useState } from "react";
import type { NetworkRow, StationRow } from "./api";
import { Field } from "./ui";

export function StationForm({
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
