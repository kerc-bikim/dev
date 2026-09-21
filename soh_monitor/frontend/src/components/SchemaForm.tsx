import type { AdapterDto, JsonSchemaProperty } from "../api/client";

export interface ConnectionDraft {
  scheme: string;
  hostname: string;
  port: string;
  basePath: string;
  tlsVerify: boolean;
  instrumentId: string;
  username: string;
  credentialReference: string;
}

export function emptyConnection(): ConnectionDraft {
  return {
    scheme: "http",
    hostname: "",
    port: "",
    basePath: "",
    tlsVerify: true,
    instrumentId: "",
    username: "admin",
    credentialReference: "",
  };
}

function Field({
  name,
  spec,
  value,
  onChange,
}: {
  name: string;
  spec: JsonSchemaProperty;
  value: string | boolean;
  onChange: (next: string | boolean) => void;
}) {
  const title = spec.title ?? name;
  if (spec.type === "boolean") {
    return (
      <label className="field checkbox">
        <input type="checkbox" checked={Boolean(value)} onChange={(event) => onChange(event.target.checked)} />
        <span>{title}</span>
      </label>
    );
  }
  if (spec.enum) {
    return (
      <label className="field">
        <span>{title}</span>
        <select value={String(value)} onChange={(event) => onChange(event.target.value)}>
          {spec.enum.map((item) => (
            <option key={String(item)} value={String(item)}>
              {String(item)}
            </option>
          ))}
        </select>
        {spec.description && <small>{spec.description}</small>}
      </label>
    );
  }
  return (
    <label className="field">
      <span>{title}</span>
      <input
        type={spec.type === "integer" ? "number" : "text"}
        value={String(value ?? "")}
        min={spec.minimum}
        max={spec.maximum}
        onChange={(event) => onChange(event.target.value)}
      />
      {spec.description && <small>{spec.description}</small>}
    </label>
  );
}

export function SchemaForm({
  adapter,
  value,
  onChange,
}: {
  adapter: AdapterDto;
  value: ConnectionDraft;
  onChange: (next: ConnectionDraft) => void;
}) {
  const schema = adapter.configurationSchema ?? { properties: {}, required: [], secretFields: [] };
  const properties = schema.properties ?? {};
  const secretFields = new Set(schema.secretFields ?? ["password"]);
  const groups = adapter.uiHints?.groups ?? [{ title: "접속", fields: Object.keys(properties) }];

  function patch(name: string, next: string | boolean) {
    onChange({ ...value, [name]: next } as ConnectionDraft);
  }

  return (
    <div className="form-grid">
      {groups.map((group) => (
        <fieldset key={group.title} className="card">
          <legend>{group.title}</legend>
          {group.fields.map((name) => {
            if (secretFields.has(name)) {
              return (
                <label className="field" key={name}>
                  <span>인증정보 참조</span>
                  <input
                    value={value.credentialReference}
                    onChange={(event) => onChange({ ...value, credentialReference: event.target.value })}
                    placeholder="env:SOH_DEVICE_PW_A01 또는 file:/run/secrets/..."
                  />
                  <small>비밀번호 평문은 저장하지 않는다. Secret 저장소 참조만 받는다.</small>
                </label>
              );
            }
            const spec = properties[name];
            if (!spec) return null;
            const current = (value as unknown as Record<string, string | boolean>)[name];
            return (
              <Field
                key={name}
                name={name}
                spec={spec}
                value={current ?? (spec.default as string | boolean) ?? ""}
                onChange={(next) => patch(name, next)}
              />
            );
          })}
        </fieldset>
      ))}
      {(adapter.uiHints?.notes ?? []).map((note) => (
        <p key={note} className="muted">
          {note}
        </p>
      ))}
    </div>
  );
}

export function connectionPayload(draft: ConnectionDraft, adapterKey: string) {
  return {
    adapterKey,
    hostname: draft.hostname,
    scheme: draft.scheme,
    port: draft.port ? Number(draft.port) : null,
    basePath: draft.basePath,
    tlsVerify: draft.tlsVerify,
    instrumentId: draft.instrumentId || null,
    credentialReference: draft.credentialReference || null,
  };
}
