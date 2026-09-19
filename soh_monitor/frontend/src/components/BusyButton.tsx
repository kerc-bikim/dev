import { useEffect, useState, type ReactNode } from "react";

export function BusyButton({
  busy,
  onCancel,
  children,
  className = "btn primary",
  disabled,
  type = "button",
  onClick,
}: {
  busy: boolean;
  onCancel?: () => void;
  children: ReactNode;
  className?: string;
  disabled?: boolean;
  type?: "button" | "submit";
  onClick?: () => void;
}) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!busy) {
      setElapsed(0);
      return;
    }
    const started = Date.now();
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 250);
    return () => window.clearInterval(timer);
  }, [busy]);

  return (
    <span className="busy-group">
      <button className={className} type={type} disabled={disabled || busy} onClick={onClick}>
        {busy ? `진행 중… ${elapsed}초` : children}
      </button>
      {busy && onCancel && (
        <button className="btn ghost" type="button" onClick={onCancel}>
          취소
        </button>
      )}
    </span>
  );
}
