from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from .control_db import connect

log = logging.getLogger("earthworm_web.audit")

SECRET_KEY_RE = re.compile(
    r"(password|passwd|secret|authcode|api[_-]?key|token|ticket|session)",
    re.I,
)
SECRET_FIELD_NAMES = {
    "password",
    "password_hash",
    "current",
    "new",
    "new_password",
    "AuthCode",
    "authcode",
    "API_KEY",
    "api_key",
    "x-api-key",
    "ew_session",
    "ticket",
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def mask_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in SECRET_FIELD_NAMES or SECRET_KEY_RE.search(str(k)):
                out[k] = "***"
            else:
                out[k] = mask_secrets(v)
        return out
    if isinstance(value, list):
        return [mask_secrets(v) for v in value]
    return value


def record_audit(
    *,
    action: str,
    result: str,
    actor_id: int | None = None,
    actor_username: str = "",
    actor_display_name: str = "",
    target: str | None = None,
    ip: str | None = None,
    detail: Any = None,
    backup_dir: str | None = None,
) -> None:
    payload = mask_secrets(detail) if detail is not None else None
    if isinstance(payload, (dict, list)):
        text = json.dumps(payload, ensure_ascii=False)
    elif payload is None:
        text = None
    else:
        text = str(payload)
    if text and SECRET_KEY_RE.search(text) and "***" not in text:
        # last-resort: never persist raw secret-looking blobs
        text = json.dumps({"redacted": True}, ensure_ascii=False)
    row = (
        utcnow(),
        actor_id,
        actor_username or "unknown",
        actor_display_name or actor_username or "unknown",
        action,
        target,
        result,
        ip,
        text,
        backup_dir,
    )
    sql = (
        "INSERT INTO audit_event (at, actor_id, actor_username, actor_display_name, "
        "action, target, result, ip, detail, backup_dir) VALUES (?,?,?,?,?,?,?,?,?,?)"
    )
    try:
        conn = connect()
        conn.execute(sql, row)
        conn.commit()
    except Exception:
        log.warning("audit insert failed; retrying once", exc_info=True)
        try:
            conn = connect()
            conn.execute(sql, row)
            conn.commit()
        except Exception:
            log.exception("audit insert retry failed")


def list_audit(
    *,
    since: str | None = None,
    until: str | None = None,
    actor: str | None = None,
    action: str | None = None,
    result: str | None = None,
    q: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> dict:
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    where: list[str] = []
    args: list[Any] = []
    if since:
        where.append("at >= ?")
        args.append(since)
    if until:
        where.append("at <= ?")
        args.append(until)
    if actor:
        where.append("(actor_username LIKE ? OR actor_display_name LIKE ?)")
        args.extend([f"%{actor}%", f"%{actor}%"])
    if action:
        where.append("action = ?")
        args.append(action)
    if result:
        where.append("result = ?")
        args.append(result)
    if q:
        where.append("(target LIKE ? OR detail LIKE ? OR action LIKE ?)")
        args.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    conn = connect()
    total = conn.execute(f"SELECT COUNT(*) FROM audit_event{clause}", args).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM audit_event{clause} ORDER BY id DESC LIMIT ? OFFSET ?",
        [*args, limit, offset],
    ).fetchall()
    events = []
    for r in rows:
        events.append(
            {
                "id": r["id"],
                "at": r["at"],
                "actor_id": r["actor_id"],
                "actor_username": r["actor_username"],
                "actor_display_name": r["actor_display_name"],
                "action": r["action"],
                "target": r["target"],
                "result": r["result"],
                "ip": r["ip"],
                "detail": json.loads(r["detail"]) if r["detail"] else None,
                "backup_dir": r["backup_dir"],
            }
        )
    return {"events": events, "total": total, "offset": offset, "limit": limit}


def export_csv(
    *,
    since: str | None = None,
    until: str | None = None,
    actor: str | None = None,
    action: str | None = None,
    result: str | None = None,
    q: str | None = None,
) -> str:
    data = list_audit(
        since=since, until=until, actor=actor, action=action, result=result, q=q, offset=0, limit=200
    )
    # pull remaining pages
    events = list(data["events"])
    while data["offset"] + data["limit"] < data["total"] and len(events) < 10000:
        data = list_audit(
            since=since,
            until=until,
            actor=actor,
            action=action,
            result=result,
            q=q,
            offset=data["offset"] + data["limit"],
            limit=200,
        )
        events.extend(data["events"])
    lines = ["id,at,actor_username,actor_display_name,action,target,result,ip,backup_dir"]
    for e in events:
        cells = [
            e["id"],
            e["at"] or "",
            e["actor_username"] or "",
            e["actor_display_name"] or "",
            e["action"] or "",
            e["target"] or "",
            e["result"] or "",
            e["ip"] or "",
            e["backup_dir"] or "",
        ]
        lines.append(",".join(_csv_cell(c) for c in cells))
    return "\n".join(lines) + "\n"


def _csv_cell(v: Any) -> str:
    s = str(v).replace('"', '""')
    if any(ch in s for ch in ",\n\r"):
        return f'"{s}"'
    return s


def sweep_audit(retention_days: int) -> int:
    days = max(1, int(retention_days))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    conn = connect()
    cur = conn.execute("DELETE FROM audit_event WHERE at < ? AND action != 'audit_sweep'", (cutoff,))
    deleted = cur.rowcount or 0
    conn.commit()
    if deleted:
        record_audit(
            action="audit_sweep",
            result="ok",
            actor_username="system",
            actor_display_name="system",
            target="audit_event",
            detail={"deleted": deleted, "cutoff": cutoff},
        )
    return deleted
