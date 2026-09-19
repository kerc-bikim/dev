"""Spool 에 쌓인 Poll 을 오래된 순서대로 중앙에 올린다.

ACK 받기 전에는 Spool 에서 지우지 않는다. 중앙이 꺼져 있으면 다음 Tick 에 다시 시도한다.
"""
from __future__ import annotations

import json
import time
from typing import Any

from jsonschema import Draft202012Validator

from app.edgeagent import AGENT_VERSION
from app.edgeagent.client import CentralClient, CentralRejected, CentralUnavailable
from app.edgeagent.spool import Spool, new_batch_id
from app.metrics.catalog import CONTRACTS_DIR
from app.observability.logging import get_logger

logger = get_logger("app.edgeagent.uploader", role="edge")

INGEST_SCHEMA = json.loads((CONTRACTS_DIR / "edge" / "ingest.schema.json").read_text("utf-8"))
_VALIDATOR = Draft202012Validator(INGEST_SCHEMA)


class Uploader:
    def __init__(
        self,
        spool: Spool,
        client: CentralClient,
        *,
        edge_id: str,
        max_polls: int = 1000,
        max_bytes: int = 5 * 1024 * 1024,
        max_backoff_seconds: float = 60.0,
    ) -> None:
        self.spool = spool
        self.client = client
        self.edge_id = edge_id
        self.max_polls = max_polls
        self.max_bytes = max_bytes
        self.max_backoff_seconds = max_backoff_seconds
        self._failures = 0
        self._next_attempt_at = 0.0

    def _in_backoff(self) -> bool:
        return time.monotonic() < self._next_attempt_at

    def _note_failure(self) -> None:
        self._failures += 1
        delay = min(self.max_backoff_seconds, 2.0 ** min(self._failures, 6))
        self._next_attempt_at = time.monotonic() + delay
        logger.warning(
            "업로드 실패, 잠시 뒤에 다시 시도한다",
            extra={"failures": self._failures, "backoff_seconds": delay},
        )

    def _note_success(self) -> None:
        self._failures = 0
        self._next_attempt_at = 0.0

    def build_batch(self, *, config_version: int, edge_health: dict[str, Any] | None = None) -> tuple[str, dict] | None:
        pending = self.spool.pending(limit=self.max_polls, max_bytes=self.max_bytes)
        if not pending:
            return None
        polls = [self.spool.load_poll(record.sequence) for record in pending]
        batch_id = new_batch_id()
        document = {
            "edgeId": self.edge_id,
            "batchId": batch_id,
            "configVersion": config_version,
            "agentVersion": AGENT_VERSION,
            "firstSequence": pending[0].sequence,
            "lastSequence": pending[-1].sequence,
            "polls": polls,
        }
        if edge_health is not None:
            document["edgeHealth"] = edge_health
        errors = sorted(_VALIDATOR.iter_errors(document), key=lambda item: list(item.path))
        if errors:
            details = "; ".join(error.message for error in errors[:5])
            raise ValueError(f"보낼 Batch 가 Schema 를 어긴다: {details}")
        return batch_id, document

    async def flush(self, *, config_version: int, edge_health: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._in_backoff():
            return {"uploaded": 0, "deferred": True, "reason": "backoff"}
        try:
            built = self.build_batch(config_version=config_version, edge_health=edge_health)
        except ValueError as exc:
            logger.error("보낼 Batch 가 Schema 를 어긴다", extra={"error": str(exc)})
            return {"uploaded": 0, "deferred": False, "rejected": True, "reason": str(exc)}
        if built is None:
            return {"uploaded": 0, "deferred": False}
        batch_id, document = built
        sequences = [poll["sequence"] for poll in document["polls"]]
        self.spool.mark_uploading(sequences, batch_id)
        try:
            ack = await self.client.upload_batch(document)
            self.spool.acknowledge(batch_id)
            self._note_success()
            logger.info(
                "Batch 를 올렸다",
                extra={
                    "batch_id": batch_id,
                    "first_sequence": document["firstSequence"],
                    "last_sequence": document["lastSequence"],
                    "polls": len(sequences),
                },
            )
            return {
                "uploaded": len(sequences),
                "deferred": False,
                "batchId": batch_id,
                "ack": ack,
            }
        except CentralUnavailable as exc:
            self.spool.revert_upload(batch_id)
            self._note_failure()
            return {"uploaded": 0, "deferred": True, "reason": str(exc), "batchId": batch_id}
        except CentralRejected as exc:
            self.spool.revert_upload(batch_id)
            logger.error("중앙이 Batch 를 거절했다", extra={"batch_id": batch_id, "error": str(exc)})
            return {"uploaded": 0, "deferred": False, "rejected": True, "reason": str(exc), "batchId": batch_id}
        except Exception:
            self.spool.revert_upload(batch_id)
            self._note_failure()
            raise
