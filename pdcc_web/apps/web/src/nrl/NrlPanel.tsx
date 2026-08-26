import { ChangeEvent, useEffect, useState } from "react";
import { apiGet, apiPost, type WizardResult } from "../api";

const LABELS: Record<string, string> = {
  sensor: "센서",
  datalogger: "기록계",
};

type Props = {
  element: "sensor" | "datalogger";
  onResolved: (instconfig: string | null) => void;
};

export function NrlPanel({ element, onResolved }: Props) {
  const [manufacturers, setManufacturers] = useState<string[]>([]);
  const [models, setModels] = useState<string[]>([]);
  const [manufacturer, setManufacturer] = useState("");
  const [model, setModel] = useState("");
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [wizard, setWizard] = useState<WizardResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setBusy(true);
    apiGet<{ manufacturers: string[] }>(`/api/nrl/manufacturers?element=${element}`)
      .then((data) => setManufacturers(data.manufacturers))
      .catch((err: Error) => setError(err.message))
      .finally(() => setBusy(false));
  }, [element]);

  useEffect(() => {
    onResolved(null);
    setModel("");
    setModels([]);
    setAnswers({});
    setWizard(null);
    if (!manufacturer) return;
    apiGet<{ models: string[] }>(
      `/api/nrl/models?element=${element}&manufacturer=${encodeURIComponent(manufacturer)}`
    )
      .then((data) => setModels(data.models))
      .catch((err: Error) => setError(err.message));
  }, [element, manufacturer, onResolved]);

  async function loadWizard(nextAnswers: Record<string, string>, nextModel = model) {
    if (!manufacturer || !nextModel) return;
    setBusy(true);
    setError(null);
    try {
      const data = await apiPost<WizardResult>("/api/nrl/wizard", {
        element,
        manufacturer,
        model: nextModel,
        answers: nextAnswers,
      });
      setWizard(data);
      const resolved = data.match_count === 1 ? data.matches[0].instconfig : null;
      onResolved(resolved);
    } catch (err) {
      setError((err as Error).message);
      onResolved(null);
    } finally {
      setBusy(false);
    }
  }

  async function onPickModel(event: ChangeEvent<HTMLSelectElement>) {
    const next = event.currentTarget.value;
    setModel(next);
    setAnswers({});
    if (next) await loadWizard({}, next);
    else {
      setWizard(null);
      onResolved(null);
    }
  }

  async function onAnswer(key: string, value: string) {
    const next = { ...answers };
    if (!value) delete next[key];
    else next[key] = value;
    const keys = (wizard?.questions ?? []).map((q) => q.key);
    const idx = keys.indexOf(key);
    for (const later of keys.slice(idx + 1)) delete next[later];
    setAnswers(next);
    await loadWizard(next);
  }

  const title = LABELS[element] ?? element;
  const resolved = wizard?.match_count === 1 ? wizard.matches[0] : null;

  return (
    <section className="nrl-card">
      <h3>{title}</h3>
      <label>
        제조사
        <select
          value={manufacturer}
          disabled={busy && manufacturers.length === 0}
          onChange={(e) => setManufacturer(e.target.value)}
        >
          <option value="">선택</option>
          {manufacturers.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </label>
      <label>
        모델
        <select value={model} disabled={!manufacturer} onChange={onPickModel}>
          <option value="">선택</option>
          {models.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </label>
      {wizard
        ? wizard.questions.map((q) => (
            <label key={q.key}>
              {q.question}
              <select
                value={answers[q.key] ?? ""}
                onChange={(e) => onAnswer(q.key, e.target.value)}
              >
                <option value="">선택</option>
                {q.options.map((opt) => (
                  <option key={opt} value={opt}>
                    {opt}
                  </option>
                ))}
              </select>
            </label>
          ))
        : null}
      {wizard && Object.keys(wizard.locked).length > 0 ? (
        <p className="hint">
          고정:{" "}
          {Object.entries(wizard.locked)
            .map(([k, v]) => `${k}=${v}`)
            .join(", ")}
        </p>
      ) : null}
      {wizard && wizard.questions.length === 0 && wizard.match_count > 1 ? (
        <label>
          구성
          <select
            defaultValue=""
            onChange={(e) => onResolved(e.target.value || null)}
          >
            <option value="">선택</option>
            {wizard.matches.map((match) => (
              <option key={match.instconfig} value={match.instconfig}>
                {match.description || match.instconfig}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {wizard ? (
        <p className="hint">
          남은 구성 {wizard.match_count}개
          {resolved ? ` · ${resolved.instconfig}` : null}
        </p>
      ) : null}
      {error ? <p className="error">{error}</p> : null}
    </section>
  );
}
