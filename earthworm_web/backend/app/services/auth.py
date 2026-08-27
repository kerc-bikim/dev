from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import HTTPException

from ..config import settings
from .audit import record_audit, utcnow
from .control_db import connect

ph = PasswordHasher()
USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{2,31}$")
ROLES = ("admin", "operator", "viewer")
IDLE = timedelta(hours=12)
ABSOLUTE = timedelta(days=7)
TICKET_TTL = timedelta(seconds=60)
FAIL_WINDOW = timedelta(minutes=10)
FAIL_LIMIT = 5
LOCK_MINUTES = 10


@dataclass
class Actor:
    id: int | None
    username: str
    display_name: str
    role: str
    enabled: bool = True
    is_service: bool = False

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "role": self.role,
            "enabled": self.enabled,
            "is_service": self.is_service,
        }


SERVICE_ACTOR = Actor(
    id=None, username="service", display_name="service", role="operator", is_service=True
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def validate_username(username: str) -> str:
    if not USERNAME_RE.match(username or ""):
        raise HTTPException(400, "로그인 ID 는 영문으로 시작하고 3–32자(영문·숫자·_.-)입니다")
    return username


def validate_password(password: str) -> str:
    if not password or len(password) < 10:
        raise HTTPException(400, "비밀번호는 10자 이상이어야 합니다")
    return password


def validate_role(role: str) -> str:
    if role not in ROLES:
        raise HTTPException(400, "역할은 admin, operator, viewer 중 하나여야 합니다")
    return role


def hash_password(password: str) -> str:
    return ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def operator_count() -> int:
    row = connect().execute("SELECT COUNT(*) AS n FROM operators").fetchone()
    return int(row["n"] if row else 0)


def enabled_admin_count(exclude_id: int | None = None) -> int:
    sql = "SELECT COUNT(*) AS n FROM operators WHERE role='admin' AND enabled=1"
    args: tuple = ()
    if exclude_id is not None:
        sql += " AND id != ?"
        args = (exclude_id,)
    row = connect().execute(sql, args).fetchone()
    return int(row["n"] if row else 0)


def get_operator(op_id: int) -> dict | None:
    row = connect().execute("SELECT * FROM operators WHERE id=?", (op_id,)).fetchone()
    return dict(row) if row else None


def get_operator_by_username(username: str) -> dict | None:
    row = connect().execute(
        "SELECT * FROM operators WHERE username_lc=?", ((username or "").lower(),)
    ).fetchone()
    return dict(row) if row else None


def public_operator(row: dict) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
        "enabled": bool(row["enabled"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "created_by": row["created_by"],
    }


def list_operators() -> list[dict]:
    rows = connect().execute("SELECT * FROM operators ORDER BY id").fetchall()
    return [public_operator(dict(r)) for r in rows]


def create_operator(
    *,
    username: str,
    display_name: str,
    password: str,
    role: str,
    created_by: int | None,
) -> dict:
    username = validate_username(username)
    validate_password(password)
    role = validate_role(role)
    display_name = (display_name or username).strip()
    if not display_name:
        raise HTTPException(400, "표시 이름이 필요합니다")
    if get_operator_by_username(username):
        raise HTTPException(400, "이미 있는 로그인 ID 입니다")
    now = utcnow()
    conn = connect()
    cur = conn.execute(
        "INSERT INTO operators (username, username_lc, display_name, password_hash, role, "
        "enabled, created_at, updated_at, created_by) VALUES (?,?,?,?,?,1,?,?,?)",
        (
            username,
            username.lower(),
            display_name,
            hash_password(password),
            role,
            now,
            now,
            created_by,
        ),
    )
    conn.commit()
    return public_operator(get_operator(cur.lastrowid) or {})


def update_operator(
    op_id: int,
    *,
    display_name: str | None = None,
    role: str | None = None,
    enabled: bool | None = None,
    password: str | None = None,
) -> dict:
    row = get_operator(op_id)
    if not row:
        raise HTTPException(404, "작업자가 없습니다")
    if role is not None:
        validate_role(role)
    if enabled is False and row["role"] == "admin" and enabled_admin_count(exclude_id=op_id) < 1:
        raise HTTPException(400, "마지막 관리자는 정지할 수 없습니다")
    if role is not None and role != "admin" and row["role"] == "admin" and enabled_admin_count(exclude_id=op_id) < 1:
        raise HTTPException(400, "마지막 관리자의 역할은 바꿀 수 없습니다")
    fields = []
    args: list = []
    if display_name is not None:
        name = display_name.strip()
        if not name:
            raise HTTPException(400, "표시 이름이 필요합니다")
        fields.append("display_name=?")
        args.append(name)
    if role is not None:
        fields.append("role=?")
        args.append(role)
    if enabled is not None:
        fields.append("enabled=?")
        args.append(1 if enabled else 0)
    if password is not None:
        validate_password(password)
        fields.append("password_hash=?")
        args.append(hash_password(password))
    if not fields:
        return public_operator(row)
    fields.append("updated_at=?")
    args.append(utcnow())
    args.append(op_id)
    conn = connect()
    conn.execute(f"UPDATE operators SET {', '.join(fields)} WHERE id=?", args)
    conn.commit()
    return public_operator(get_operator(op_id) or {})


def bootstrap_admin(username: str, display_name: str, password: str) -> dict:
    if operator_count() > 0:
        raise HTTPException(403, "이미 관리자가 있습니다")
    return create_operator(
        username=username,
        display_name=display_name or username,
        password=password,
        role="admin",
        created_by=None,
    )


def seed_bootstrap_from_env() -> None:
    user = (settings.BOOTSTRAP_USERNAME or "").strip()
    pw = settings.BOOTSTRAP_PASSWORD or ""
    if not user or not pw:
        return
    if operator_count() > 0:
        return
    try:
        rec = bootstrap_admin(user, user, pw)
        record_audit(
            action="bootstrap_admin",
            result="ok",
            actor_username=rec["username"],
            actor_display_name=rec["display_name"],
            actor_id=rec["id"],
            target=rec["username"],
            detail={"source": "env"},
        )
    except Exception:
        pass


def _locked_until(username_lc: str) -> datetime | None:
    since = _iso(_now() - FAIL_WINDOW)
    conn = connect()
    rows = conn.execute(
        "SELECT at FROM login_fail WHERE username_lc=? AND at>=? ORDER BY at DESC",
        (username_lc, since),
    ).fetchall()
    if len(rows) < FAIL_LIMIT:
        return None
    last = datetime.fromisoformat(rows[0]["at"])
    until = last + timedelta(minutes=LOCK_MINUTES)
    if until > _now():
        return until
    return None


def _note_fail(username_lc: str) -> None:
    conn = connect()
    conn.execute("INSERT INTO login_fail (username_lc, at) VALUES (?,?)", (username_lc, utcnow()))
    conn.commit()


def create_session(operator_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = _now()
    conn = connect()
    conn.execute(
        "INSERT INTO sessions (token, operator_id, created_at, last_seen, expires_at) VALUES (?,?,?,?,?)",
        (token, operator_id, _iso(now), _iso(now), _iso(now + ABSOLUTE)),
    )
    conn.commit()
    return token


def delete_session(token: str | None) -> None:
    if not token:
        return
    conn = connect()
    conn.execute("DELETE FROM sessions WHERE token=?", (token,))
    conn.commit()


def actor_from_session(token: str | None) -> Actor | None:
    if not token:
        return None
    conn = connect()
    row = conn.execute(
        "SELECT s.created_at, s.last_seen, s.expires_at, o.* "
        "FROM sessions s JOIN operators o ON o.id=s.operator_id WHERE s.token=?",
        (token,),
    ).fetchone()
    if not row:
        return None
    now = _now()
    try:
        last_seen = datetime.fromisoformat(row["last_seen"])
        created = datetime.fromisoformat(row["created_at"])
        expires = datetime.fromisoformat(row["expires_at"])
    except Exception:
        delete_session(token)
        return None
    if now > expires or now > created + ABSOLUTE or now > last_seen + IDLE:
        delete_session(token)
        return None
    if not row["enabled"]:
        delete_session(token)
        return None
    conn.execute("UPDATE sessions SET last_seen=? WHERE token=?", (utcnow(), token))
    conn.commit()
    return Actor(
        id=row["id"],
        username=row["username"],
        display_name=row["display_name"],
        role=row["role"],
        enabled=bool(row["enabled"]),
    )


def actor_from_api_key(key: str | None) -> Actor | None:
    expected = (settings.API_KEY or "").strip()
    if not expected:
        return None
    if not key or key != expected:
        return None
    return SERVICE_ACTOR


def login(username: str, password: str, ip: str | None = None) -> tuple[dict, str]:
    username_lc = (username or "").lower()
    locked = _locked_until(username_lc)
    if locked:
        record_audit(
            action="login_failed",
            result="denied",
            actor_username=username or "unknown",
            actor_display_name=username or "unknown",
            target=username,
            ip=ip,
            detail={"reason": "locked"},
        )
        raise HTTPException(403, "잠시 후 다시 로그인하세요")
    row = get_operator_by_username(username or "")
    if not row or not row["enabled"] or not verify_password(row["password_hash"], password or ""):
        _note_fail(username_lc)
        record_audit(
            action="login_failed",
            result="denied",
            actor_username=username or "unknown",
            actor_display_name=(row["display_name"] if row else username) or "unknown",
            actor_id=row["id"] if row else None,
            target=username,
            ip=ip,
            detail={"reason": "invalid"},
        )
        raise HTTPException(403, "로그인 ID 또는 비밀번호가 올바르지 않습니다")
    token = create_session(row["id"])
    record_audit(
        action="login",
        result="ok",
        actor_id=row["id"],
        actor_username=row["username"],
        actor_display_name=row["display_name"],
        target=row["username"],
        ip=ip,
    )
    return public_operator(row), token


def change_own_password(actor: Actor, current: str, new: str) -> None:
    if actor.is_service or actor.id is None:
        raise HTTPException(400, "서비스 계정은 비밀번호를 바꾸지 않습니다")
    row = get_operator(actor.id)
    if not row or not verify_password(row["password_hash"], current or ""):
        raise HTTPException(403, "현재 비밀번호가 올바르지 않습니다")
    validate_password(new)
    update_operator(actor.id, password=new)


def issue_ws_ticket(actor: Actor) -> dict:
    ticket = secrets.token_urlsafe(24)
    now = _now()
    conn = connect()
    conn.execute(
        "INSERT INTO ws_tickets (ticket, operator_id, username, display_name, role, created_at, expires_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (
            ticket,
            actor.id,
            actor.username,
            actor.display_name,
            actor.role,
            _iso(now),
            _iso(now + TICKET_TTL),
        ),
    )
    conn.commit()
    return {"ticket": ticket, "expires_in": 60}


def consume_ws_ticket(ticket: str | None) -> Actor | None:
    if not ticket:
        return None
    conn = connect()
    row = conn.execute("SELECT * FROM ws_tickets WHERE ticket=?", (ticket,)).fetchone()
    if not row:
        return None
    conn.execute("DELETE FROM ws_tickets WHERE ticket=?", (ticket,))
    conn.commit()
    try:
        exp = datetime.fromisoformat(row["expires_at"])
    except Exception:
        return None
    if _now() > exp:
        return None
    return Actor(
        id=row["operator_id"],
        username=row["username"],
        display_name=row["display_name"],
        role=row["role"],
        is_service=row["username"] == "service" and row["operator_id"] is None,
    )
