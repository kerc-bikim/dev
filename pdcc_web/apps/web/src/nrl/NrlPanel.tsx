import { ChangeEvent, FormEvent, useEffect, useRef, useState } from "react";
import { apiGet, apiPost, type NrlSearchHit, type WizardResult } from "../api";

const LABELS: Record<string, string> = {
  sensor: "센서",
  datalogger: "기록계",
};

type Props = {
  element: "sensor" | "datalogger";
  onResolved: (instconfig: string | null) => void;
  disabled?: boolean;
};

export function NrlPanel({ element, onResolved, disabled = false }: Props) {
  const [manufacturers, setManufacturers] = useState<string[]>([]);
  const [models, setModels] = useState<string[]>([]);
  const [manufacturer, setManufacturer] = useState("");
  const [model, setModel] = useState("");
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [wizard, setWizard] = useState<WizardResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<NrlSearchHit[]>([]);
  const [excluded, setExcluded] = useState<{ name: string; message: string } | null>(null);
  const [emptyMessage, setEmptyMessage] = useState<string | null>(null);
  const skipClear = useRef(false);

  useEffect(() => {
    setBusy(true);
    apiGet<{ manufacturers: string[] }>(`/api/nrl/manufacturers?element=${element}`)
      .then((data) => setManufacturers(data.manufacturers))
      .catch((err: Error) => setError(err.message))
      .finally(() => setBusy(false));
  }, [element]);

  useEffect(() => {
    if (!skipClear.current) {
      onResolved(null);
      setModel("");
      setAnswers({});
      setWizard(null);
    }
    skipClear.current = false;
    setModels([]);
    if (!manufacturer) return;
    apiGet<{ models: string[] }>(
      `/api/nrl/models?element=${element}&manufacturer=${encodeURIComponent(manufacturer)}`
    )
      .then((data) => setModels(data.models))
      .catch((err: Error) => setError(err.message));
  }, [element, manufacturer, onResolved]);

  async function loadWizard(
    nextAnswers: Record<string, string>,
    nextModel = model,
    nextManufacturer = manufacturer
  ) {
    if (!nextManufacturer || !nextModel) return;
    setBusy(true);
    setError(null);
    try {
      const data = await apiPost<WizardResult>("/api/nrl/wizard", {
        element,
        manufacturer: nextManufacturer,
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

  async function runSearch(event?: FormEvent) {
    event?.preventDefault();
    const q = query.trim();
    setError(null);
    setExcluded(null);
    setHits([]);
    setEmptyMessage(null);
    if (q.length < 2) {
      setEmptyMessage("검색어는 2자 이상입니다");
      return;
    }
    setBusy(true);
    try {
      const data = await apiGet<{
        hits: NrlSearchHit[];
        excluded: { name: string; message: string } | null;
        message: string | null;
      }>(`/api/nrl/search?element=${element}&q=${encodeURIComponent(q)}`);
      if (data.excluded) {
        setExcluded(data.excluded);
        setHits([]);
        setManufacturer("");
        setModel("");
        setWizard(null);
        onResolved(null);
        return;
      }
      setHits(data.hits);
      setEmptyMessage(data.hits.length ? null : data.message);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function applyHit(hit: NrlSearchHit) {
    skipClear.current = true;
    setManufacturer(hit.manufacturer);
    setHits([]);
    setExcluded(null);
    if (hit.model) {
      setModel(hit.model);
      setAnswers({});
      await loadWizard({}, hit.model, hit.manufacturer);
    } else {
      setModel("");
      setWizard(null);
      onResolved(null);
    }
  }

  const title = LABELS[element] ?? element;
  const resolved = wizard?.match_count === 1 ? wizard.matches[0] : null;

  return (
    <section className="nrl-card">
      <h3>{title}</h3>
      <form className="nrl-search" onSubmit={runSearch}>
        <label>
          검색
          <input
            value={query}
            disabled={disabled}
            placeholder="3t, metrozet, cme…"
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <button type="submit" disabled={disabled || busy}>
          찾기
        </button>
      </form>
      {excluded ? (
        <p className="lock-banner" role="status">
          {excluded.message}
        </p>
      ) : null}
      {emptyMessage ? <p className="hint">{emptyMessage}</p> : null}
      {hits.length > 0 ? (
        <ul className="search-hits">
          {hits.map((hit) => (
            <li key={`${hit.manufacturer}-${hit.model ?? ""}`}>
              <button type="button" disabled={disabled} onClick={() => applyHit(hit)}>
                {hit.manufacturer}
                {hit.model ? ` / ${hit.model}` : ""}
                {hit.via === "alias" ? " · 별칭" : ""}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <label>
        제조사
        <select
          value={manufacturer}
          disabled={disabled || (busy && manufacturers.length === 0)}
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
        <select value={model} disabled={disabled || !manufacturer} onChange={onPickModel}>
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
                disabled={disabled}
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
            disabled={disabled}
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
