"""로컬 Spool.

흐름은 '먼저 기록, 그 다음 전송' 이다. 전송이 실패해도 원본은 디스크에 남아 있다.

  * 메타데이터: SQLite WAL
  * Poll 본문: gzip Segment 파일
  * ACK 받기 전에는 행과 파일을 지우지 않는다
  * 한도를 넘으면 ACK 완료분 → 오래된 정상 Poll 순으로 비운다. 장애 Poll 은 최후

전원 강제 차단을 흉내 내려면 프로세스를 죽인 뒤 같은 경로로 다시 열면 된다.
WAL 과 FULL sync 로 커밋된 행은 재기동 뒤에도 그대로다.
"""
from __future__ import annotations

import gzip
import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from app.domain.models import PollResult
from app.edgeagent.codec import is_incident_poll, poll_to_ingest
from app.observability.logging import get_logger

logger = get_logger("app.edgeagent.spool", role="edge")

PENDING = "PENDING"
UPLOADING = "UPLOADING"
ACKNOWLEDGED = "ACKNOWLEDGED"


class SpoolStatus(str, Enum):
    PENDING = PENDING
    UPLOADING = UPLOADING
    ACKNOWLEDGED = ACKNOWLEDGED


@dataclass(frozen=True)
class SpoolRecord:
    sequence: int
    poll_id: str
    device_id: str
    observed_at: str
    success: bool
    is_incident: bool
    status: str
    batch_id: str | None
    path: str
    bytes: int


class Spool:
    def __init__(self, root: Path, *, limit_bytes: int) -> None:
        self.root = Path(root)
        self.limit_bytes = limit_bytes
        self.segments_dir = self.root / "segments"
        self.segments_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db_path = self.root / "spool.sqlite"
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS polls (
                sequence INTEGER PRIMARY KEY,
                poll_id TEXT NOT NULL UNIQUE,
                device_id TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                success INTEGER NOT NULL,
                is_incident INTEGER NOT NULL,
                status TEXT NOT NULL,
                batch_id TEXT,
                path TEXT NOT NULL,
                bytes INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_polls_status_seq ON polls(status, sequence);
            """
        )
        self._conn.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES('next_sequence', '1')"
        )
        self._conn.commit()

    def _meta(self, key: str, default: str = "") -> str:
        row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def _set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    @property
    def next_sequence(self) -> int:
        return int(self._meta("next_sequence", "1"))

    def used_bytes(self) -> int:
        row = self._conn.execute("SELECT COALESCE(SUM(bytes), 0) AS total FROM polls").fetchone()
        return int(row["total"])

    def pending_count(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM polls WHERE status IN (?, ?)",
            (PENDING, UPLOADING),
        ).fetchone()
        return int(row["n"])

    def oldest_pending_age_seconds(self, *, now: datetime | None = None) -> float | None:
        row = self._conn.execute(
            "SELECT MIN(created_at) AS oldest FROM polls WHERE status IN (?, ?)",
            (PENDING, UPLOADING),
        ).fetchone()
        if not row or not row["oldest"]:
            return None
        oldest = datetime.fromisoformat(row["oldest"])
        current = now or datetime.now(timezone.utc)
        if oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=timezone.utc)
        return max(0.0, (current - oldest).total_seconds())

    def append(self, result: PollResult) -> SpoolRecord:
        """파일을 먼저 쓰고 행을 커밋한다. 커밋 전 죽으면 고아 파일만 남고 유실은 없다."""
        with self._lock:
            sequence = self.next_sequence
            body = poll_to_ingest(result, sequence)
            raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            payload = gzip.compress(raw)
            relative = f"{sequence:08d}.json.gz"
            path = self.segments_dir / relative
            tmp = path.with_suffix(".gz.tmp")
            tmp.write_bytes(payload)
            tmp.replace(path)

            incident = 1 if is_incident_poll(result) else 0
            created = datetime.now(timezone.utc).isoformat()
            self._conn.execute(
                """
                INSERT INTO polls(
                    sequence, poll_id, device_id, observed_at, success, is_incident,
                    status, batch_id, path, bytes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
                """,
                (
                    sequence,
                    result.poll_id,
                    result.device_id,
                    body["observedAt"],
                    1 if result.success else 0,
                    incident,
                    PENDING,
                    relative,
                    len(payload),
                    created,
                ),
            )
            self._set_meta("next_sequence", str(sequence + 1))
            self._conn.commit()
            record = SpoolRecord(
                sequence=sequence,
                poll_id=result.poll_id,
                device_id=result.device_id,
                observed_at=body["observedAt"],
                success=result.success,
                is_incident=bool(incident),
                status=PENDING,
                batch_id=None,
                path=relative,
                bytes=len(payload),
            )
        dropped = self.reclaim_if_needed()
        if dropped:
            logger.warning("Spool 한도를 넘쳐 비웠다", extra={"dropped": dropped, "used_bytes": self.used_bytes()})
        return record

    def load_poll(self, sequence: int) -> dict:
        row = self._conn.execute("SELECT path FROM polls WHERE sequence = ?", (sequence,)).fetchone()
        if row is None:
            raise KeyError(sequence)
        path = self.segments_dir / row["path"]
        return json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))

    def pending(self, *, limit: int = 1000, max_bytes: int = 5 * 1024 * 1024) -> list[SpoolRecord]:
        rows = self._conn.execute(
            "SELECT * FROM polls WHERE status = ? ORDER BY sequence ASC",
            (PENDING,),
        ).fetchall()
        chosen: list[SpoolRecord] = []
        total = 0
        for row in rows:
            if len(chosen) >= limit:
                break
            if total + row["bytes"] > max_bytes and chosen:
                break
            chosen.append(_row_to_record(row))
            total += row["bytes"]
        return chosen

    def mark_uploading(self, sequences: list[int], batch_id: str) -> None:
        with self._lock:
            self._conn.executemany(
                "UPDATE polls SET status = ?, batch_id = ? WHERE sequence = ? AND status = ?",
                [(UPLOADING, batch_id, seq, PENDING) for seq in sequences],
            )
            self._conn.commit()

    def acknowledge(self, batch_id: str) -> int:
        """ACK 받은 뒤에만 파일을 지운다."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT sequence, path FROM polls WHERE batch_id = ? AND status = ?",
                (batch_id, UPLOADING),
            ).fetchall()
            for row in rows:
                path = self.segments_dir / row["path"]
                if path.exists():
                    path.unlink()
            self._conn.execute("DELETE FROM polls WHERE batch_id = ? AND status = ?", (batch_id, UPLOADING))
            self._conn.commit()
            return len(rows)

    def revert_upload(self, batch_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE polls SET status = ?, batch_id = NULL WHERE batch_id = ? AND status = ?",
                (PENDING, batch_id, UPLOADING),
            )
            self._conn.commit()

    def reclaim_if_needed(self) -> int:
        """한도를 넘으면 우선순위에 따라 비운다. ACK 전 장애 Poll 은 가능한 한 남긴다."""
        dropped = 0
        with self._lock:
            while self.used_bytes() > self.limit_bytes:
                victim = self._conn.execute(
                    """
                    SELECT sequence, path, status, is_incident FROM polls
                    ORDER BY
                        CASE status WHEN 'ACKNOWLEDGED' THEN 0 ELSE 1 END,
                        is_incident ASC,
                        sequence ASC
                    LIMIT 1
                    """
                ).fetchone()
                if victim is None:
                    break
                if victim["status"] != ACKNOWLEDGED and victim["is_incident"] and self._only_incidents_left():
                    logger.error("Spool 이 가득 찼고 남은 것은 장애 Poll 뿐이다")
                    break
                path = self.segments_dir / victim["path"]
                if path.exists():
                    path.unlink()
                self._conn.execute("DELETE FROM polls WHERE sequence = ?", (victim["sequence"],))
                self._conn.commit()
                dropped += 1
                if victim["status"] != ACKNOWLEDGED:
                    logger.warning(
                        "ACK 전에 Spool 항목을 버렸다",
                        extra={"sequence": victim["sequence"], "incident": bool(victim["is_incident"])},
                    )
        return dropped

    def _only_incidents_left(self) -> bool:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM polls WHERE is_incident = 0"
        ).fetchone()
        return int(row["n"]) == 0

    def snapshot(self) -> dict:
        return {
            "usedBytes": self.used_bytes(),
            "limitBytes": self.limit_bytes,
            "pending": self.pending_count(),
            "nextSequence": self.next_sequence,
            "oldestPendingAgeSeconds": self.oldest_pending_age_seconds(),
        }


def _row_to_record(row: sqlite3.Row) -> SpoolRecord:
    return SpoolRecord(
        sequence=row["sequence"],
        poll_id=row["poll_id"],
        device_id=row["device_id"],
        observed_at=row["observed_at"],
        success=bool(row["success"]),
        is_incident=bool(row["is_incident"]),
        status=row["status"],
        batch_id=row["batch_id"],
        path=row["path"],
        bytes=row["bytes"],
    )


def new_batch_id() -> str:
    return str(uuid.uuid4())
