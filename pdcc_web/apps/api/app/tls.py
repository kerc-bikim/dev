"""사내 SSL 가시화(검사) 장비 CA를 신뢰 목록에 더한다.

내부망에서 HTTPS를 검사하면 체인에 사설 루트가 끼어
`CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate chain`
이 난다. `SSL_CA_BUNDLE`에 보안팀이 준 PEM 인증서(예: ABC.crt)를 지정하면
기본 CA(certifi)에 그 인증서를 붙여 NRL 등 외부 HTTPS를 검증한다.
검증 자체를 끄지 않는다.
"""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
from pathlib import Path

from .config import Settings, settings

log = logging.getLogger("pdcc.tls")

PEM_MARKER = b"-----BEGIN CERTIFICATE-----"
_MAX_PROBE_BYTES = 1 << 20
_VERIFY: bool | str = True
_APPLIED = False


class CaBundleError(ValueError):
    """SSL_CA_BUNDLE 경로가 없거나 PEM이 아닌 경우."""


def configured_ca_bundle(cfg: Settings | None = None) -> str:
    cfg = cfg or settings
    explicit = (cfg.ssl_ca_bundle or "").strip().strip('"').strip("'")
    if explicit:
        return explicit
    # 프로세스 전역 설정일 때만 requests 표준 변수를 별칭으로 받는다.
    if cfg is settings:
        return os.environ.get("REQUESTS_CA_BUNDLE", "").strip()
    return ""


def project_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "infra" / "docker-compose.yml").is_file():
            return parent
    return Path.cwd()


def resolve_ca_bundle(ca_bundle: str) -> str | None:
    """경로를 절대경로로 바꾼다. 비어 있으면 None."""
    raw = (ca_bundle or "").strip().strip('"').strip("'")
    if not raw:
        return None

    given = Path(os.path.expandvars(os.path.expanduser(raw)))
    candidates: list[Path] = [given] if given.is_absolute() else [
        Path.cwd() / given,
        Path("/certs") / given,
        project_root() / "certs" / given,
        project_root() / given,
    ]
    for candidate in candidates:
        if candidate.is_file():
            _ensure_pem(candidate)
            return str(candidate.resolve())
        if candidate.is_dir():
            raise CaBundleError(
                f"SSL_CA_BUNDLE 은 인증서 파일이어야 합니다 (디렉터리: {candidate}). "
                "예: /certs/ABC.crt"
            )

    tried = "\n".join(f"  - {path}" for path in candidates)
    raise CaBundleError(
        f"SSL_CA_BUNDLE 에 지정한 인증서를 찾을 수 없습니다: {raw}\n"
        f"다음 경로를 확인했습니다.\n{tried}\n"
        "PEM 형식의 ABC.crt 등을 두고 절대경로를 적으세요."
    )


def _ensure_pem(path: Path) -> None:
    data = path.read_bytes()[:_MAX_PROBE_BYTES]
    if PEM_MARKER in data:
        return
    if data[:1] == b"\x30":
        pem_path = path.with_suffix(".pem")
        raise CaBundleError(
            f"{path} 는 DER(바이너리) 형식이라 그대로 쓸 수 없습니다. PEM으로 변환하세요.\n"
            f"  openssl x509 -inform der -in {path} -out {pem_path}\n"
            f"변환한 뒤 SSL_CA_BUNDLE 을 {pem_path} 로 바꾸세요."
        )
    raise CaBundleError(
        f"{path} 에서 PEM 인증서를 찾지 못했습니다 "
        f"('{PEM_MARKER.decode()}' 블록이 없습니다)."
    )


def load_verify(ca_bundle: str) -> bool | str:
    """httpx `verify` 값. 추가 CA가 있으면 certifi 번들에 이어 붙인 파일 경로."""
    resolved = resolve_ca_bundle(ca_bundle)
    if resolved is None:
        return True
    extra = Path(resolved).read_bytes()
    try:
        import certifi

        base = Path(certifi.where()).read_bytes()
    except Exception:
        log.warning("certifi 를 읽지 못해 SSL_CA_BUNDLE 만 사용합니다")
        return resolved
    digest = hashlib.sha256(extra).hexdigest()[:12]
    dest = Path(tempfile.gettempdir()) / f"pdcc-ca-{digest}.pem"
    dest.write_bytes(base + b"\n" + extra + b"\n")
    return str(dest)


def httpx_verify() -> bool | str:
    return _VERIFY


def apply_ca_bundle(cfg: Settings | None = None) -> str | None:
    """기동 시 CA를 확인하고, 있으면 SSL_CERT_FILE 에도 넣어 urllib/requests 가 따라오게 한다."""
    global _VERIFY, _APPLIED
    if _APPLIED:
        return _VERIFY if isinstance(_VERIFY, str) else None
    _VERIFY = load_verify(configured_ca_bundle(cfg))
    _APPLIED = True
    if isinstance(_VERIFY, str):
        os.environ["SSL_CERT_FILE"] = _VERIFY
        os.environ["REQUESTS_CA_BUNDLE"] = _VERIFY
        log.info("SSL_CA_BUNDLE 적용: %s", _VERIFY)
        return _VERIFY
    return None


def reset_ca_bundle_for_tests() -> None:
    global _VERIFY, _APPLIED
    _VERIFY = True
    _APPLIED = False


def is_cert_verify_failed(exc: BaseException | None) -> bool:
    seen: set[int] = set()
    current = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        text = str(current).lower()
        if "certificate_verify_failed" in text or "certificate verify failed" in text:
            return True
        current = current.__cause__ or current.__context__
    return False


def tls_hint(exc: Exception) -> str:
    if isinstance(httpx_verify(), str):
        return (
            "지정한 SSL_CA_BUNDLE 로도 검증에 실패했습니다. "
            "검사 장비 루트·중간 인증서가 PEM 한 파일에 들어 있는지 확인하세요."
        )
    return (
        "사내 SSL 가시화(검사) 장비를 거치는 환경으로 보입니다. "
        "보안팀이 준 인증서(예: ABC.crt)를 PEM 으로 두고 SSL_CA_BUNDLE 에 경로를 지정하세요."
    )
