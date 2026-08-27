import { useEffect, useState } from "react";
import { api } from "../api/client";
import { ConfirmModal, Field } from "../components/Confirm";

type FieldRow = { key: string; label: string; value: string; used_in: string[] };

export function VariablesPage({ toast }: { toast: (m: string) => void }) {
  const [fields, setFields] = useState<FieldRow[]>([]);
  const [preview, setPreview] = useState<string[] | null>(null);
  const [pending, setPending] = useState<Record<string, string> | null>(null);

  useEffect(() => {
    api<{ fields: FieldRow[] }>("/api/variables")
      .then((d) => setFields(d.fields))
      .catch((e: Error) => toast(e.message));
  }, [toast]);

  function apply() {
    const values: Record<string, string> = {};
    for (const f of fields) values[f.key] = f.value;
    const files = Array.from(new Set(fields.flatMap((f) => f.used_in)));
    setPending(values);
    setPreview(files.length ? files : ["earthworm_commonvars.d"]);
  }

  async function confirm() {
    if (!pending) return;
    try {
      const res = await api<{ changed: string[] }>("/api/variables", {
        method: "PUT",
        body: JSON.stringify({ values: pending }),
      });
      toast("적용됨: " + res.changed.join(", "));
    } catch (e) {
      toast((e as Error).message);
    }
    setPreview(null);
    setPending(null);
  }

  return (
    <>
      <h2>통합 변수</h2>
      <p className="lead">
        저장 위치는 earthworm_commonvars.d 의 SetEnvVariable. HeartbeatInt 변경 시 .desc tsec 도 같이
        올립니다.
      </p>
      <div className="card grid cols-2">
        {fields.map((f) => (
          <Field
            key={f.key}
            label={f.label}
            value={f.value}
            onChange={(v) => setFields(fields.map((x) => (x.key === f.key ? { ...x, value: v } : x)))}
          />
        ))}
      </div>
      <button className="primary" onClick={apply}>
        적용 미리보기
      </button>
      {preview && pending && (
        <ConfirmModal
          title="변수 적용"
          body={`변경될 파일: ${preview.join(", ")}`}
          onOk={() => void confirm()}
          onCancel={() => {
            setPreview(null);
            setPending(null);
          }}
        />
      )}
    </>
  );
}
