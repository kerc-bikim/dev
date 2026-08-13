export interface AxisRangeValue {
  x_min: number | null;
  x_max: number | null;
  y_min: number | null;
  y_max: number | null;
}

export const EMPTY_AXIS_RANGE: AxisRangeValue = {
  x_min: null,
  x_max: null,
  y_min: null,
  y_max: null,
};

interface Props {
  value: AxisRangeValue;
  onChange: (v: AxisRangeValue) => void;
  xaxis: "period" | "frequency";
}

function fmt(n: number | null): string {
  return n === null || n === undefined ? "" : String(n);
}

function parse(s: string): number | null {
  const t = s.trim();
  if (!t) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

export function AxisRangePanel({ value, onChange, xaxis }: Props) {
  const xUnit = xaxis === "frequency" ? "Hz" : "s";
  const set = <K extends keyof AxisRangeValue>(k: K, raw: string) =>
    onChange({ ...value, [k]: parse(raw) });

  return (
    <div className="section">
      <h3>Axis range</h3>
      <p className="hint">
        X축을 비우면(auto) 채널 샘플레이트에 맞는 의미 있는 구간만 표시합니다
        (주기: Nyquist ~ min(세그먼트/8, 179 s), 주파수: 그 역수). 장주기 쪽
        불안정한 bin(세로 스파이크)을 가리기 위함입니다. Y축을 비우면 단위별
        기본값 또는 서버 .env 설정을 사용합니다.
      </p>
      <div className="row-2">
        <div className="field">
          <label>X min ({xUnit})</label>
          <input
            type="number"
            step="any"
            value={fmt(value.x_min)}
            onChange={(e) => set("x_min", e.target.value)}
            placeholder="auto"
          />
        </div>
        <div className="field">
          <label>X max ({xUnit})</label>
          <input
            type="number"
            step="any"
            value={fmt(value.x_max)}
            onChange={(e) => set("x_max", e.target.value)}
            placeholder="auto"
          />
        </div>
      </div>
      <div className="row-2">
        <div className="field">
          <label>Y min (dB)</label>
          <input
            type="number"
            step="any"
            value={fmt(value.y_min)}
            onChange={(e) => set("y_min", e.target.value)}
            placeholder="auto"
          />
        </div>
        <div className="field">
          <label>Y max (dB)</label>
          <input
            type="number"
            step="any"
            value={fmt(value.y_max)}
            onChange={(e) => set("y_max", e.target.value)}
            placeholder="auto"
          />
        </div>
      </div>
    </div>
  );
}
