import { useState } from "react";
import { apiSend, type CatalogRow, type ChannelRow, type StationRow } from "./api";
import { Field, NEW_EQUIPMENT, catalogLabel } from "./ui";

export function ChannelForm({
  value,
  stations,
  sensors,
  loggers,
  actor,
  onClose,
  onSave,
}: {
  value: Partial<ChannelRow>;
  stations: StationRow[];
  sensors: CatalogRow[];
  loggers: CatalogRow[];
  actor: string;
  onClose: () => void;
  onSave: (payload: Record<string, unknown>) => Promise<void>;
}) {
  const [form, setForm] = useState(value);
  const [err, setErr] = useState<string | null>(null);
  const [customSensor, setCustomSensor] = useState({
    code: "",
    manufacturer: "",
    model: "",
    description: "",
  });
  const [customLogger, setCustomLogger] = useState({
    code: "",
    manufacturer: "",
    model: "",
    sample_rate: value.sample_rate ? String(value.sample_rate) : "",
    description: "",
  });
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
                  {catalogLabel(s)}
                </option>
              ))}
              <option value={NEW_EQUIPMENT}>목록에 없음…</option>
            </select>
          </Field>
          {form.sensor_id === NEW_EQUIPMENT && (
            <>
              <Field label="센서 제조사">
                <input
                  value={customSensor.manufacturer}
                  onChange={(e) =>
                    setCustomSensor({ ...customSensor, manufacturer: e.target.value })
                  }
                />
              </Field>
              <Field label="센서 모델">
                <input
                  value={customSensor.model}
                  onChange={(e) => setCustomSensor({ ...customSensor, model: e.target.value })}
                />
              </Field>
              <Field label="센서 ID (선택)">
                <input
                  placeholder="비우면 자동"
                  value={customSensor.code}
                  onChange={(e) => setCustomSensor({ ...customSensor, code: e.target.value })}
                />
              </Field>
              <Field label="센서 설명">
                <input
                  value={customSensor.description}
                  onChange={(e) =>
                    setCustomSensor({ ...customSensor, description: e.target.value })
                  }
                />
              </Field>
            </>
          )}
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
                  {catalogLabel(s)}
                </option>
              ))}
              <option value={NEW_EQUIPMENT}>목록에 없음…</option>
            </select>
          </Field>
          {form.datalogger_id === NEW_EQUIPMENT && (
            <>
              <Field label="기록계 제조사">
                <input
                  value={customLogger.manufacturer}
                  onChange={(e) =>
                    setCustomLogger({ ...customLogger, manufacturer: e.target.value })
                  }
                />
              </Field>
              <Field label="기록계 모델">
                <input
                  value={customLogger.model}
                  onChange={(e) => setCustomLogger({ ...customLogger, model: e.target.value })}
                />
              </Field>
              <Field label="기록계 sps">
                <input
                  type="number"
                  value={customLogger.sample_rate}
                  onChange={(e) =>
                    setCustomLogger({ ...customLogger, sample_rate: e.target.value })
                  }
                />
              </Field>
              <Field label="기록계 ID (선택)">
                <input
                  placeholder="비우면 자동"
                  value={customLogger.code}
                  onChange={(e) => setCustomLogger({ ...customLogger, code: e.target.value })}
                />
              </Field>
              <Field label="기록계 설명">
                <input
                  value={customLogger.description}
                  onChange={(e) =>
                    setCustomLogger({ ...customLogger, description: e.target.value })
                  }
                />
              </Field>
            </>
          )}
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
                const payload: Record<string, unknown> = { ...form };
                if (form.sensor_id === NEW_EQUIPMENT) {
                  const created = await apiSend<CatalogRow>(
                    "POST",
                    "/api/catalog",
                    {
                      kind: "sensor",
                      code: customSensor.code || null,
                      manufacturer: customSensor.manufacturer,
                      model: customSensor.model,
                      description: customSensor.description || null,
                    },
                    actor
                  );
                  payload.sensor_id = created.code;
                }
                if (form.datalogger_id === NEW_EQUIPMENT) {
                  const created = await apiSend<CatalogRow>(
                    "POST",
                    "/api/catalog",
                    {
                      kind: "datalogger",
                      code: customLogger.code || null,
                      manufacturer: customLogger.manufacturer,
                      model: customLogger.model,
                      sample_rate: customLogger.sample_rate
                        ? Number(customLogger.sample_rate)
                        : null,
                      description: customLogger.description || null,
                    },
                    actor
                  );
                  payload.datalogger_id = created.code;
                }
                await onSave(payload);
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
