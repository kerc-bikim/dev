"""TLS 인증서 설정과 연결 점검.

사내망에서 TLS 검사 장비(프록시)를 거치면 서버 인증서 체인에 사설 루트
인증서가 끼어들어, 기본 신뢰 저장소로는 검증이 실패한다.

    [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed:
    self-signed certificate in certificate chain

이때는 그 사설 인증서를 신뢰 목록으로 넘겨야 한다. `.env`의
`LATLON_CA_BUNDLE`에 인증서 경로를 적으면 모든 요청이 그 인증서로 서버를
검증한다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from . import parsers
from .config import PROJECT_ROOT, Settings
from .errors import AuthError, ConfigError, LatlonError, QuotaError

PEM_MARKER = b"-----BEGIN CERTIFICATE-----"

# 인증서 파일을 통째로 읽되, 엉뚱한 큰 파일을 지정했을 때를 대비해 상한을 둔다.
_MAX_PROBE_BYTES = 1 << 20


def resolve_ca_bundle(ca_bundle: str) -> str | bool:
    """`LATLON_CA_BUNDLE` 값을 requests의 `verify` 인자로 바꾼다.

    값이 비어 있으면 `True`(기본 신뢰 저장소)를 돌려준다. 경로를 주면
    존재와 형식을 확인한 뒤 절대경로 문자열을 돌려준다.
    """
    raw = (ca_bundle or "").strip().strip('"').strip("'")
    if not raw:
        return True

    given = Path(os.path.expandvars(os.path.expanduser(raw)))
    # 상대경로는 실행 위치를 먼저 보고, 없으면 프로젝트 폴더에서 찾는다.
    candidates = [given] if given.is_absolute() else [Path.cwd() / given, PROJECT_ROOT / given]

    for candidate in candidates:
        if candidate.is_dir():
            # OpenSSL 해시 디렉터리(c_rehash로 준비된 형태)도 받아들인다.
            return str(candidate.resolve())
        if candidate.is_file():
            _ensure_pem(candidate)
            return str(candidate.resolve())

    tried = "\n".join(f"  - {candidate}" for candidate in candidates)
    raise ConfigError(
        f"LATLON_CA_BUNDLE에 지정한 인증서를 찾을 수 없습니다: {raw}\n"
        f"다음 경로를 확인했습니다.\n{tried}\n"
        "절대경로로 적거나 파일을 해당 위치에 두세요."
    )


def _ensure_pem(path: Path) -> None:
    """requests는 PEM만 읽으므로 DER(.crt 바이너리)를 미리 걸러 낸다."""
    data = path.read_bytes()[:_MAX_PROBE_BYTES]
    if PEM_MARKER in data:
        return
    if data[:1] == b"\x30":
        pem_path = path.with_suffix(".pem")
        raise ConfigError(
            f"{path} 는 DER(바이너리) 형식이라 그대로 쓸 수 없습니다. PEM으로 변환해 주세요.\n"
            f"  openssl x509 -inform der -in {path} -out {pem_path}\n"
            f"변환한 뒤 LATLON_CA_BUNDLE을 {pem_path} 로 바꾸세요."
        )
    raise ConfigError(
        f"{path} 에서 PEM 인증서를 찾지 못했습니다 "
        f"('{PEM_MARKER.decode()}' 로 시작하는 블록이 없습니다).\n"
        "인증서 파일이 맞는지, 텍스트(PEM) 형식인지 확인하세요."
    )


def tls_error_message(ca_bundle: str | bool, exc: Exception) -> str:
    """인증서 검증 실패를 설정 방법과 함께 설명한다."""
    lines = [f"서버 인증서를 검증하지 못했습니다: {exc}"]
    if isinstance(ca_bundle, str):
        lines.append(
            f"지정한 인증서({ca_bundle})로도 검증에 실패했습니다. "
            "체인의 루트와 중간 인증서가 모두 들어 있는지 확인하세요 "
            "(여러 장이면 PEM 블록을 한 파일에 이어 붙이면 됩니다)."
        )
    else:
        lines.append(
            "사내망 TLS 검사 장비를 거치는 환경으로 보입니다. 발급받은 인증서(예: test.crt)를 "
            "PEM 형식으로 준비하고 .env의 LATLON_CA_BUNDLE에 경로를 넣으세요."
        )
    lines.append("설정을 확인하려면: python -m latlon_converter check")
    return "\n".join(lines)


def build_session(settings: Settings, session: Any | None = None) -> Any:
    """설정된 인증서를 적용한 requests 세션을 만든다."""
    prepared = session or requests.Session()
    prepared.verify = resolve_ca_bundle(settings.ca_bundle)
    return prepared


# 점검이 어디까지 갔는지 나타내는 값.
CHECK_OK = "ok"
CHECK_TLS_FAILED = "tls_failed"
CHECK_CONNECT_FAILED = "connect_failed"
CHECK_HTTP_ERROR = "http_error"
CHECK_NON_JSON = "non_json"
CHECK_AUTH = "auth"
CHECK_QUOTA = "quota"
CHECK_API_ERROR = "api_error"

# 인증서 검증을 통과해야만 도달할 수 있는 단계들.
_TLS_VERIFIED = frozenset(
    {CHECK_OK, CHECK_HTTP_ERROR, CHECK_NON_JSON, CHECK_AUTH, CHECK_QUOTA, CHECK_API_ERROR}
)


@dataclass
class ConnectionCheck:
    """`check` 명령이 보고하는 점검 결과."""

    ca_bundle: str | bool
    status: str
    http_status: int | None = None
    detail: str = ""
    hint: str = ""

    @property
    def tls_verified(self) -> bool | None:
        """인증서 검증 결과. 연결 자체가 안 되면 판단할 수 없어 None."""
        if self.status in _TLS_VERIFIED:
            return True
        if self.status == CHECK_TLS_FAILED:
            return False
        return None


def check_connection(settings: Settings, url: str, session: Any | None = None) -> ConnectionCheck:
    """실제 서버에 한 번 요청해 TLS 검증과 인증키 상태를 확인한다.

    인증키가 없어도 TLS 검증 여부는 확인할 수 있다. 서버가 키 오류를
    돌려준다는 것 자체가 TLS 연결에 성공했다는 뜻이다.
    """
    prepared = build_session(settings, session)
    params: dict[str, str] = {
        "service": "data",
        "version": "2.0",
        "request": "GetFeature",
        "data": "LP_PA_CBND_BUBUN",
        "format": "json",
        "size": "1",
    }
    if settings.api_key:
        params["key"] = settings.api_key
    if settings.domain:
        params["domain"] = settings.domain

    try:
        response = prepared.get(url, params=params, timeout=settings.timeout)
    except requests.exceptions.SSLError as exc:
        return ConnectionCheck(
            ca_bundle=prepared.verify,
            status=CHECK_TLS_FAILED,
            detail=str(exc),
            hint=tls_error_message(prepared.verify, exc),
        )
    except Exception as exc:
        return ConnectionCheck(
            ca_bundle=prepared.verify,
            status=CHECK_CONNECT_FAILED,
            detail=str(exc),
            hint=(
                "인증서 검증 단계에 가기 전에 연결이 끊겼습니다. 인증서 문제가 아니라 "
                "네트워크나 프록시(HTTPS_PROXY) 설정 문제일 수 있습니다."
            ),
        )

    # 여기까지 왔으면 인증서 검증은 통과했다.
    status = getattr(response, "status_code", None)
    check = ConnectionCheck(ca_bundle=prepared.verify, status=CHECK_OK, http_status=status)

    if status is not None and status >= 400:
        check.status = CHECK_HTTP_ERROR
        check.detail = f"인증서 검증은 통과했지만 서버가 HTTP {status}를 돌려주었습니다"
        check.hint = (
            "TLS 설정 문제는 아닙니다. 프록시나 브이월드 서버 상태를 확인하고 잠시 후 다시 시도하세요."
            if status >= 500
            else "TLS 설정 문제는 아닙니다. 요청 주소와 프록시 설정을 확인하세요."
        )
        return check

    try:
        payload = response.json()
    except ValueError:
        check.status = CHECK_NON_JSON
        check.detail = "인증서 검증은 통과했지만 JSON이 아닌 응답을 받았습니다"
        check.hint = "프록시가 응답을 가로채 오류 페이지를 돌려주는지 확인하세요."
        return check

    try:
        parsers.raise_for_error(payload, "연결 점검")
    except AuthError as exc:
        check.status = CHECK_AUTH
        check.detail = str(exc)
        check.hint = (
            "인증서 검증은 정상입니다. 인증키와 domain 값을 확인하세요."
            if settings.api_key
            else "인증서 검증은 정상입니다. 인증키를 넣으면 실제 조회가 가능합니다."
        )
    except QuotaError as exc:
        check.status = CHECK_QUOTA
        check.detail = str(exc)
        check.hint = "인증서 검증은 정상입니다. 일일 호출 한도가 회복된 뒤 다시 시도하세요."
    except LatlonError as exc:
        check.status = CHECK_API_ERROR
        check.detail = str(exc)
    else:
        check.detail = "인증서 검증과 API 응답이 모두 정상입니다"
    return check
