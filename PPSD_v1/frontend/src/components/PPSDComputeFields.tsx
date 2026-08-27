interface Props {
  value: {
    ppsd_length: number;
    overlap: number;
    period_step_octaves: number;
    period_smoothing_width_octaves: number;
  };
  onChange: (v: {
    ppsd_length: number;
    overlap: number;
    period_step_octaves: number;
    period_smoothing_width_octaves: number;
  }) => void;
}

export function PPSDComputeFields({ value, onChange }: Props) {
  const set = <K extends keyof Props["value"]>(k: K, v: Props["value"][K]) =>
    onChange({ ...value, [k]: v });

  return (
    <div className="section">
      <h3>PPSD computation</h3>
      <p className="hint">
        ObsPy PPSD 세그먼트·주기 binning 파라미터입니다. 값을 바꾸면 재계산되며
        SDS 캐시 npz가 덮어씌워집니다. 세그먼트가 너무 짧으면 처리 실패할 수
        있습니다.
      </p>
      <div className="range-row">
        <span>ppsd_length [s]</span>
        <input
          type="number"
          min={1}
          step={1}
          value={value.ppsd_length}
          onChange={(e) => set("ppsd_length", Number(e.target.value))}
        />
      </div>
      <div className="range-row">
        <span>overlap</span>
        <input
          type="number"
          min={0}
          max={0.99}
          step={0.05}
          value={value.overlap}
          onChange={(e) => set("overlap", Number(e.target.value))}
        />
      </div>
      <div className="range-row">
        <span>period_step_octaves</span>
        <input
          type="number"
          min={0.001}
          step={0.0125}
          value={value.period_step_octaves}
          onChange={(e) => set("period_step_octaves", Number(e.target.value))}
        />
      </div>
      <div className="range-row">
        <span>period_smoothing_width_octaves</span>
        <input
          type="number"
          min={0.001}
          step={0.125}
          value={value.period_smoothing_width_octaves}
          onChange={(e) =>
            set("period_smoothing_width_octaves", Number(e.target.value))
          }
        />
      </div>
    </div>
  );
}
