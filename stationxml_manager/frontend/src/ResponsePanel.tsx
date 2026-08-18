import { useCallback, useEffect, useRef, useState } from "react";
import {
  apiGet,
  apiSend,
  type ChannelRow,
  type OverlayCurve,
  type ResponseStage,
  type ResponseStages,
  type SingleCurve,
} from "./api";
import { exportResponsePng, responsePngFilename } from "./charts/exportResponsePng";
import { renderResponseCurve } from "./charts/responseCurve";

export function ResponsePanel({
  rows,
  selectedId,
  overlayIds,
  actor,
  onReload,
  onError,
}: {
  rows: ChannelRow[];
  selectedId: number | null;
  overlayIds: number[];
  actor: string;
  onReload: () => Promise<void>;
  onError: (e: string | null) => void;
}) {
  const [output, setOutput] = useState("VEL");
  const [curve, setCurve] = useState<OverlayCurve | SingleCurve | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [stages, setStages] = useState<ResponseStages | null>(null);
  const [showPz, setShowPz] = useState(false);
  const [chartWidth, setChartWidth] = useState(0);
  const hostRef = useRef<HTMLDivElement>(null);
  const selected = rows.find((row) => row.id === selectedId) || null;

  const loadCurve = useCallback(async () => {
    if (!selected && overlayIds.length === 0) {
      setCurve(null);
      setErrors([]);
      onError(null);
      return;
    }
    try {
      if (overlayIds.length > 0) {
        const data = await apiGet<OverlayCurve>(
          `/api/response-curves?ids=${overlayIds.join(",")}&output=${output}`
        );
        setCurve(data);
        setErrors(data.errors.map((item) => item.reason));
      } else if (selected) {
        if (!selected.has_response) {
          setCurve(null);
          setErrors([
            "이 채널에는 계측기 응답이 없습니다. StationXML/SEED를 가져오거나 NRL을 적용하세요.",
          ]);
          onError(null);
          return;
        }
        const data = await apiGet<SingleCurve>(
          `/api/channels/${selected.id}/response-curve?output=${output}`
        );
        setCurve(data);
        setErrors([]);
      }
      onError(null);
    } catch (e) {
      setCurve(null);
      const message = e instanceof Error ? e.message : String(e);
      setErrors([message]);
      onError(message);
    }
  }, [onError, output, overlayIds, selected]);

  useEffect(() => {
    void loadCurve();
  }, [loadCurve]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => setChartWidth(host.clientWidth));
    observer.observe(host);
    setChartWidth(host.clientWidth);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const series =
      curve && "series" in curve
        ? curve.series
        : curve
          ? [
              {
                nslc: curve.nslc,
                start_time: curve.start_time,
                amplitude: curve.amplitude,
                phase_deg: curve.phase_deg,
              },
            ]
          : [];
    const frequencies = curve && "frequencies" in curve ? curve.frequencies : [];
    renderResponseCurve(host, {
      frequencies,
      series,
      output,
      title:
        series.length > 1
          ? `응답 비교 (${series.length}채널)`
          : selected?.nslc || "응답 곡선",
      errors,
    });
  }, [chartWidth, curve, errors, output, selected?.nslc]);

  const seriesCount =
    curve && "series" in curve ? curve.series.length : curve ? 1 : 0;

  return (
    <div className="response-panel">
      <div className="toolbar">
        <strong>{selected?.nslc || "채널을 선택하세요"}</strong>
        {selected && (
          <span className="muted">
            {selected.start_time} · {selected.sensor_id || "센서 없음"} /{" "}
            {selected.datalogger_id || "기록계 없음"} ·{" "}
            {selected.has_response ? selected.response_source : "없음"}
          </span>
        )}
        <select value={output} onChange={(e) => setOutput(e.target.value)}>
          <option value="DIS">DIS</option>
          <option value="VEL">VEL</option>
          <option value="ACC">ACC</option>
        </select>
        <button className="secondary" onClick={() => void loadCurve()}>
          새로고침
        </button>
        <button
          className="secondary"
          disabled={seriesCount < 1}
          onClick={() => {
            if (!hostRef.current || !curve) return;
            const series =
              "series" in curve
                ? curve.series
                : [{ nslc: curve.nslc }];
            void exportResponsePng(hostRef.current, responsePngFilename(output, series));
          }}
        >
          PNG 저장
        </button>
        {selected?.has_response && (
          <button
            className="secondary"
            onClick={async () => {
              try {
                setStages(await apiGet(`/api/channels/${selected.id}/response-stages`));
                setShowPz(true);
                onError(null);
              } catch (e) {
                onError(e instanceof Error ? e.message : String(e));
              }
            }}
          >
            Poles/Zeros
          </button>
        )}
      </div>
      {errors.map((item) => (
        <p key={item} className="warn">
          {item}
        </p>
      ))}
      <div ref={hostRef} className="response-chart" />
      {showPz && stages && selected && (
        <PzEditor
          stages={stages}
          actor={actor}
          onClose={() => setShowPz(false)}
          onSaved={async (next) => {
            setStages(next);
            await onReload();
            await loadCurve();
          }}
          onError={onError}
        />
      )}
    </div>
  );
}

function PzEditor({
  stages,
  actor,
  onClose,
  onSaved,
  onError,
}: {
  stages: ResponseStages;
  actor: string;
  onClose: () => void;
  onSaved: (next: ResponseStages) => Promise<void>;
  onError: (e: string | null) => void;
}) {
  const editable = stages.stages.filter((s) => s.editable);
  const [drafts, setDrafts] = useState<Record<number, ResponseStage>>(() =>
    Object.fromEntries(
      editable.map((s) => [s.stage_sequence_number, JSON.parse(JSON.stringify(s))])
    )
  );
  return (
    <div className="pz-editor">
      <h4>Poles/Zeros</h4>
      {stages.warnings?.map((w) => (
        <p key={w} className="warn">
          {w}
        </p>
      ))}
      {stages.stages
        .filter((s) => !s.editable)
        .map((s) => (
          <p key={s.stage_sequence_number} className="muted">
            stage {s.stage_sequence_number} {s.type} (읽기 전용) {s.input_units} → {s.output_units}
          </p>
        ))}
      {editable.map((stage) => {
        const draft = drafts[stage.stage_sequence_number];
        return (
          <div key={stage.stage_sequence_number} className="pz-stage">
            <strong>
              stage {stage.stage_sequence_number} {stage.pz_transfer_function_type}
            </strong>
            <p className="muted">A0는 저장 시 재계산됩니다 ({draft.normalization_factor})</p>
            <div className="grid">
              <label className="field">
                단계 게인
                <input
                  type="number"
                  value={draft.stage_gain ?? 0}
                  onChange={(e) =>
                    setDrafts({
                      ...drafts,
                      [stage.stage_sequence_number]: {
                        ...draft,
                        stage_gain: Number(e.target.value),
                      },
                    })
                  }
                />
              </label>
              <label className="field">
                정규화 주파수
                <input
                  type="number"
                  value={draft.normalization_frequency ?? 1}
                  onChange={(e) =>
                    setDrafts({
                      ...drafts,
                      [stage.stage_sequence_number]: {
                        ...draft,
                        normalization_frequency: Number(e.target.value),
                      },
                    })
                  }
                />
              </label>
            </div>
            <ComplexTable
              title="극"
              rows={draft.poles || []}
              onChange={(poles) =>
                setDrafts({
                  ...drafts,
                  [stage.stage_sequence_number]: { ...draft, poles },
                })
              }
            />
            <ComplexTable
              title="영점"
              rows={draft.zeros || []}
              onChange={(zeros) =>
                setDrafts({
                  ...drafts,
                  [stage.stage_sequence_number]: { ...draft, zeros },
                })
              }
            />
            <button
              onClick={async () => {
                if (
                  !confirm(
                    "계측기 응답을 수정합니다. 곡선과 Dataless SEED 내용이 바뀝니다. 계속할까요?"
                  )
                ) {
                  return;
                }
                try {
                  const next = await apiSend<ResponseStages>(
                    "PUT",
                    `/api/channels/${stages.channel_id}/response-stages/${stage.stage_sequence_number}`,
                    {
                      poles: draft.poles,
                      zeros: draft.zeros,
                      stage_gain: draft.stage_gain,
                      normalization_frequency: draft.normalization_frequency,
                    },
                    actor
                  );
                  await onSaved(next);
                  onError(null);
                } catch (e) {
                  onError(e instanceof Error ? e.message : String(e));
                }
              }}
            >
              stage {stage.stage_sequence_number} 저장
            </button>
          </div>
        );
      })}
      <button className="secondary" onClick={onClose}>
        닫기
      </button>
    </div>
  );
}

function ComplexTable({
  title,
  rows,
  onChange,
}: {
  title: string;
  rows: { real: number; imag: number }[];
  onChange: (rows: { real: number; imag: number }[]) => void;
}) {
  return (
    <div>
      <div className="toolbar">
        <span>{title}</span>
        <button
          className="secondary"
          onClick={() => onChange([...rows, { real: 0, imag: 0 }])}
        >
          행 추가
        </button>
      </div>
      <table>
        <thead>
          <tr>
            <th>실수</th>
            <th>허수</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${title}-${index}`}>
              <td>
                <input
                  type="number"
                  value={row.real}
                  onChange={(e) => {
                    const next = rows.slice();
                    next[index] = { ...row, real: Number(e.target.value) };
                    onChange(next);
                  }}
                />
              </td>
              <td>
                <input
                  type="number"
                  value={row.imag}
                  onChange={(e) => {
                    const next = rows.slice();
                    next[index] = { ...row, imag: Number(e.target.value) };
                    onChange(next);
                  }}
                />
              </td>
              <td>
                <button className="danger" onClick={() => onChange(rows.filter((_, i) => i !== index))}>
                  삭제
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
