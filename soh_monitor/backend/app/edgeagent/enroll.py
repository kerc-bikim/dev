"""일회용 Token → 클라이언트 인증서.

등록이 끝나면 Token 은 파일에서 지우고 메모리에서도 버린다. 이후 통신은
인증서(또는 발급받은 Edge 토큰)로만 한다.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

from app.observability.logging import get_logger

logger = get_logger("app.edgeagent.enroll", role="edge")


def generate_enrollment_token() -> str:
    return secrets.token_urlsafe(32)


def hash_enrollment_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_edge_token(edge_id: str, secret: str, *, ttl_seconds: int = 30 * 24 * 3600, now: int | None = None) -> str:
    issued = int(now if now is not None else time.time())
    expires = issued + ttl_seconds
    payload = f"edge:{edge_id}:{expires}".encode("utf-8")
    body = hashlib.sha256(payload).hexdigest()[:32]
    signature = hmac.new(secret.encode("utf-8"), f"{body}:{edge_id}:{expires}".encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{body}.{edge_id}.{expires}.{signature}"


def verify_edge_token(token: str | None, secret: str, *, now: int | None = None) -> str:
    if not token:
        raise ValueError("Edge 토큰이 없다")
    try:
        body, edge_id, expires_raw, signature = token.split(".", 3)
        expires = int(expires_raw)
    except ValueError as exc:
        raise ValueError("Edge 토큰 형식이 잘못됐다") from exc
    expected = hmac.new(
        secret.encode("utf-8"), f"{body}:{edge_id}:{expires}".encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise ValueError("Edge 토큰 서명이 맞지 않는다")
    current = int(now if now is not None else time.time())
    if expires <= current:
        raise ValueError("Edge 토큰이 만료됐다")
    return edge_id


@dataclass
class EnrollmentBundle:
    certificate: str
    private_key: str
    ca_certificate: str
    client_token: str
    expires_at: str | None = None


class EnrollmentStore:
    def __init__(self, cert_dir: Path, *, token: str | None = None, token_file: Path | None = None) -> None:
        self.cert_dir = Path(cert_dir)
        self.cert_dir.mkdir(parents=True, exist_ok=True)
        self._token = token
        self._token_file = token_file
        self.cert_path = self.cert_dir / "client.crt"
        self.key_path = self.cert_dir / "client.key"
        self.ca_path = self.cert_dir / "ca.crt"
        self.token_path = self.cert_dir / "client.token"

    def has_certificate(self) -> bool:
        return self.cert_path.exists() and self.key_path.exists() and self.token_path.exists()

    def peek_token(self) -> str | None:
        """아직 쓰지 않은 Token 을 보여 준다. 중앙이 꺼져 있으면 다음 Tick 에 다시 쓴다."""
        if self._token:
            return self._token
        if self._token_file and self._token_file.exists():
            return self._token_file.read_text(encoding="utf-8").strip() or None
        return None

    def take_token(self) -> str | None:
        """한 번만 돌려주고 버린다. 파일은 discard_token_file 이 지운다."""
        token = self.peek_token()
        self._token = None
        return token or None

    def discard_token_file(self) -> None:
        if self._token_file and self._token_file.exists():
            self._token_file.unlink()
            self._token_file = None

    def save(self, bundle: EnrollmentBundle) -> None:
        self.cert_path.write_text(bundle.certificate, encoding="utf-8")
        self.key_path.write_text(bundle.private_key, encoding="utf-8")
        self.ca_path.write_text(bundle.ca_certificate, encoding="utf-8")
        self.token_path.write_text(bundle.client_token, encoding="utf-8")
        os.chmod(self.key_path, 0o600)
        os.chmod(self.token_path, 0o600)

    def client_token(self) -> str | None:
        if not self.token_path.exists():
            return None
        return self.token_path.read_text(encoding="utf-8").strip()

    def identity_record(self) -> dict:
        return {
            "hasCertificate": self.has_certificate(),
            "certificatePath": str(self.cert_path),
        }


def write_placeholder_certificate(common_name: str, issued_at: str) -> tuple[str, str, str]:
    """개발·시험용 인증서 파일.

    운영 mTLS 검증(M8) 은 중앙 CA 가 발급한 X.509 를 쓴다. 여기서는 등록이 끝났다는
    사실을 파일로 남기는 것이 목적이다.
    """
    payload = json.dumps({"cn": common_name, "issuedAt": issued_at}, ensure_ascii=False)
    cert = f"-----BEGIN CERTIFICATE-----\n{payload}\n-----END CERTIFICATE-----\n"
    key = f"-----BEGIN PRIVATE KEY-----\n{payload}\n-----END PRIVATE KEY-----\n"
    ca = f"-----BEGIN CERTIFICATE-----\nsoh-central-ca\n-----END CERTIFICATE-----\n"
    return cert, key, ca
