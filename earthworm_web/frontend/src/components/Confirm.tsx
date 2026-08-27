export function ConfirmModal({
  title,
  body,
  onOk,
  onCancel,
}: {
  title: string;
  body: string;
  onOk: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="modal-bg">
      <div className="modal">
        <h3>{title}</h3>
        <p className="lead">{body}</p>
        <div className="row">
          <button type="button" onClick={onCancel}>
            취소
          </button>
          <button type="button" className="primary" onClick={onOk}>
            확인
          </button>
        </div>
      </div>
    </div>
  );
}

export function Field({
  label,
  value,
  onChange,
  type = "text",
  disabled,
}: {
  label: string;
  value: string | number;
  onChange: (v: string) => void;
  type?: string;
  disabled?: boolean;
}) {
  return (
    <div>
      <label>{label}</label>
      <input
        type={type}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}
