import { defaultTimeWindow, shiftTimeWindow } from "../utils/time";

export interface TimeWindowRow {
  id: string;
  starttime: string;
  endtime: string;
  label?: string;
  color?: string;
}

const DEFAULT_COLORS = [
  "#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6",
  "#1abc9c", "#e67e22", "#34495e", "#e91e63", "#00bcd4",
];

let _rowId = 0;
function newRowId() {
  return `tw-${++_rowId}`;
}

interface Props {
  rows: TimeWindowRow[];
  onChange: (rows: TimeWindowRow[]) => void;
}

export function createDefaultTimeWindowRow(
  starttime: string,
  endtime: string,
  color?: string
): TimeWindowRow {
  return {
    id: newRowId(),
    starttime,
    endtime,
    color,
  };
}

export function createDefaultTimeWindows(): TimeWindowRow[] {
  const current = defaultTimeWindow();
  const previous = shiftTimeWindow(
    current.start,
    current.end,
    -7 * 24 * 60 * 60 * 1000
  );
  return [
    createDefaultTimeWindowRow(current.start, current.end, DEFAULT_COLORS[0]),
    createDefaultTimeWindowRow(previous.start, previous.end, DEFAULT_COLORS[1]),
  ];
}

export function TimeWindowListEditor({ rows, onChange }: Props) {
  const updateRow = (id: string, patch: Partial<TimeWindowRow>) => {
    onChange(rows.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  };

  const removeRow = (id: string) => {
    if (rows.length <= 1) return;
    onChange(rows.filter((r) => r.id !== id));
  };

  const addRow = () => {
    const { start, end } = defaultTimeWindow();
    onChange([
      ...rows,
      createDefaultTimeWindowRow(
        start,
        end,
        DEFAULT_COLORS[rows.length % DEFAULT_COLORS.length]
      ),
    ]);
  };

  return (
    <div className="section">
      <h3>Time windows (UTC)</h3>
      <p className="hint">동일 관측소·채널의 서로 다른 시간 구간을 비교합니다.</p>
      {rows.map((row, rowIdx) => (
        <div key={row.id} className="target-row">
          <div className="target-row-header">
            <span className="target-row-title">Window {rowIdx + 1}</span>
            {rows.length > 1 && (
              <button
                type="button"
                className="btn-ghost"
                onClick={() => removeRow(row.id)}
              >
                Remove
              </button>
            )}
          </div>
          <div className="row-2">
            <div className="field">
              <label>Start</label>
              <input
                type="datetime-local"
                step={1}
                value={row.starttime}
                onChange={(e) =>
                  updateRow(row.id, { starttime: e.target.value })
                }
              />
            </div>
            <div className="field">
              <label>End</label>
              <input
                type="datetime-local"
                step={1}
                value={row.endtime}
                onChange={(e) => updateRow(row.id, { endtime: e.target.value })}
              />
            </div>
          </div>
          <div className="row-2">
            <div className="field">
              <label>Label (optional)</label>
              <input
                type="text"
                value={row.label ?? ""}
                onChange={(e) =>
                  updateRow(row.id, { label: e.target.value || undefined })
                }
                placeholder="e.g. Before event"
              />
            </div>
            <div className="field">
              <label>Color</label>
              <div className="color-field">
                <input
                  type="color"
                  className="color-swatch"
                  value={row.color || DEFAULT_COLORS[rowIdx % DEFAULT_COLORS.length]}
                  onChange={(e) => updateRow(row.id, { color: e.target.value })}
                />
                <input
                  type="text"
                  value={row.color || ""}
                  onChange={(e) => updateRow(row.id, { color: e.target.value })}
                  placeholder="#3498db"
                />
              </div>
            </div>
          </div>
        </div>
      ))}
      <button type="button" className="btn-secondary" onClick={addRow}>
        + Add time window
      </button>
    </div>
  );
}
