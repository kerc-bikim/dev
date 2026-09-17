"""인증서 설정과 TLS 연결 검증.

자체 서명 인증서로 로컬 HTTPS 서버를 띄워, 사용자가 보고한
`CERTIFICATE_VERIFY_FAILED`를 실제로 재현하고 `LATLON_CA_BUNDLE`을 넣으면
통과하는지 확인한다.
"""

from __future__ import annotations

import json
import shutil
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from latlon_converter import cli
from latlon_converter.config import FIXTURES_DIR, Settings
from latlon_converter.errors import (
    EXIT_AUTH,
    EXIT_NETWORK,
    EXIT_OK,
    EXIT_QUOTA,
    EXIT_TLS,
    AuthError,
    ConfigError,
    TlsError,
)
from latlon_converter.providers import vworld as vworld_module
from latlon_converter.providers.vworld import VWorldProvider
from latlon_converter.tls import (
    CHECK_API_ERROR,
    CHECK_AUTH,
    CHECK_CONNECT_FAILED,
    CHECK_OK,
    CHECK_QUOTA,
    CHECK_TLS_FAILED,
    ConnectionCheck,
    build_session,
    check_connection,
    resolve_ca_bundle,
    tls_error_message,
)

PEM_SAMPLE = (
    "-----BEGIN CERTIFICATE-----\nMIIBkTCB+wIJAKZ\n-----END CERTIFICATE-----\n"
)


# --- LATLON_CA_BUNDLE 값 해석 --------------------------------------------


def test_empty_value_uses_default_trust_store():
    assert resolve_ca_bundle("") is True
    assert resolve_ca_bundle("   ") is True


def test_pem_file_is_accepted(tmp_path):
    cert = tmp_path / "test.crt"
    cert.write_text(PEM_SAMPLE, encoding="utf-8")
    assert resolve_ca_bundle(str(cert)) == str(cert.resolve())


def test_quoted_and_user_path_are_handled(tmp_path, monkeypatch):
    cert = tmp_path / "test.crt"
    cert.write_text(PEM_SAMPLE, encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert resolve_ca_bundle(f'"{cert}"') == str(cert.resolve())
    assert resolve_ca_bundle("~/test.crt") == str(cert.resolve())


def test_relative_path_is_resolved_from_cwd(tmp_path, monkeypatch):
    cert = tmp_path / "certs" / "test.crt"
    cert.parent.mkdir()
    cert.write_text(PEM_SAMPLE, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert resolve_ca_bundle("certs/test.crt") == str(cert.resolve())


def test_directory_is_accepted(tmp_path):
    assert resolve_ca_bundle(str(tmp_path)) == str(tmp_path.resolve())


def test_missing_file_lists_attempted_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError) as info:
        resolve_ca_bundle("없는인증서.crt")
    message = str(info.value)
    assert "찾을 수 없습니다" in message
    assert str(tmp_path) in message


def test_der_certificate_gets_conversion_hint(tmp_path):
    cert = tmp_path / "test.crt"
    # DER은 ASN.1 SEQUENCE(0x30)로 시작한다.
    cert.write_bytes(b"\x30\x82\x03\x0a\x02\x01\x02")
    with pytest.raises(ConfigError) as info:
        resolve_ca_bundle(str(cert))
    message = str(info.value)
    assert "DER" in message
    assert "openssl x509 -inform der" in message


def test_non_certificate_file_is_rejected(tmp_path):
    cert = tmp_path / "test.crt"
    cert.write_text("그냥 메모입니다", encoding="utf-8")
    with pytest.raises(ConfigError) as info:
        resolve_ca_bundle(str(cert))
    assert "PEM 인증서를 찾지 못했습니다" in str(info.value)


def test_build_session_applies_bundle(tmp_path):
    cert = tmp_path / "test.crt"
    cert.write_text(PEM_SAMPLE, encoding="utf-8")
    session = build_session(Settings(ca_bundle=str(cert)))
    assert session.verify == str(cert.resolve())
    assert build_session(Settings()).verify is True


def test_error_message_differs_by_whether_bundle_was_set():
    without = tls_error_message(True, Exception("verify failed"))
    assert "LATLON_CA_BUNDLE" in without

    with_bundle = tls_error_message("/etc/ssl/test.crt", Exception("verify failed"))
    assert "/etc/ssl/test.crt" in with_bundle
    assert "중간 인증서" in with_bundle


# --- 자체 서명 인증서를 쓰는 로컬 HTTPS 서버 -----------------------------


@pytest.fixture(scope="module")
def self_signed_server(tmp_path_factory):
    """자체 서명 인증서로 HTTPS 서버를 띄워 (기본 URL, 인증서 경로)를 준다."""
    if shutil.which("openssl") is None:
        pytest.skip("openssl이 없어 자체 서명 인증서를 만들 수 없습니다")

    workdir = tmp_path_factory.mktemp("tls")
    cert = workdir / "test.crt"
    key = workdir / "test.key"
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-sha256",
            "-days", "1", "-nodes",
            "-keyout", str(key), "-out", str(cert),
            "-subj", "/CN=localhost",
            "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
        ],
        check=True,
        capture_output=True,
    )

    cadastral = (FIXTURES_DIR / "cadastral_yeoksam.json").read_bytes()
    incorrect_key = json.dumps(
        {
            "response": {
                "status": "ERROR",
                "error": {"code": "INCORRECT_KEY", "text": "인증키 정보가 올바르지 않습니다."},
            }
        },
        ensure_ascii=False,
    ).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (http.server가 정한 이름)
            body = cadastral if self.path.startswith("/req/data") else incorrect_key
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            return None

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert), str(key))
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"https://localhost:{server.server_address[1]}", cert
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_self_signed_certificate_fails_without_bundle(self_signed_server):
    """사용자가 보고한 오류를 그대로 재현한다."""
    base, _ = self_signed_server
    check = check_connection(Settings(provider="vworld", timeout=5), f"{base}/req/data")

    assert check.status == CHECK_TLS_FAILED
    assert check.tls_verified is False
    assert "CERTIFICATE_VERIFY_FAILED" in check.detail
    assert "LATLON_CA_BUNDLE" in check.hint


def test_ca_bundle_makes_verification_pass(self_signed_server):
    base, cert = self_signed_server
    settings = Settings(provider="vworld", ca_bundle=str(cert), timeout=5)
    check = check_connection(settings, f"{base}/req/data")

    assert check.status == CHECK_OK
    assert check.tls_verified is True
    assert check.http_status == 200
    assert check.ca_bundle == str(cert.resolve())


def test_check_reports_key_error_over_verified_tls(self_signed_server):
    """키가 틀려도 인증서 검증 자체는 통과했음을 구분해 보고한다."""
    base, cert = self_signed_server
    settings = Settings(provider="vworld", api_key="WRONG", ca_bundle=str(cert), timeout=5)
    check = check_connection(settings, f"{base}/error")

    assert check.status == CHECK_AUTH
    assert check.tls_verified is True
    assert "인증서 검증은 정상입니다" in check.hint


def test_lookup_succeeds_over_tls_with_bundle(self_signed_server, monkeypatch):
    """인증서를 설정하면 실제 HTTPS 요청으로 위경도 조회가 된다."""
    base, cert = self_signed_server
    monkeypatch.setattr(vworld_module, "DATA_URL", f"{base}/req/data")
    settings = Settings(
        provider="vworld", api_key="TEST-KEY", domain="http://localhost",
        ca_bundle=str(cert), retries=1, timeout=5,
    )

    parcel = VWorldProvider(settings).get_parcel(37.50435, 127.02505)

    assert parcel is not None
    assert parcel.pnu == "1168010100108080000"
    assert parcel.jibun_address == "서울특별시 강남구 역삼동 808"


def test_lookup_raises_tls_error_without_bundle(self_signed_server, monkeypatch):
    base, _ = self_signed_server
    monkeypatch.setattr(vworld_module, "DATA_URL", f"{base}/req/data")
    monkeypatch.setattr(vworld_module.time, "sleep", lambda seconds: None)
    settings = Settings(provider="vworld", api_key="TEST-KEY", retries=2, timeout=5)

    with pytest.raises(TlsError) as info:
        VWorldProvider(settings).get_parcel(37.50435, 127.02505)

    message = str(info.value)
    assert "CERTIFICATE_VERIFY_FAILED" in message
    assert "LATLON_CA_BUNDLE" in message


def test_bad_bundle_path_is_reported_before_any_request():
    settings = Settings(provider="vworld", api_key="TEST-KEY", ca_bundle="/없는/경로/test.crt")
    with pytest.raises(ConfigError):
        VWorldProvider(settings)


# --- 재시도하지 않음 / CLI 종료코드 --------------------------------------


class SslFailingSession:
    verify = True

    def __init__(self):
        self.calls = 0

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        raise vworld_module.requests.exceptions.SSLError("certificate verify failed")


def test_tls_failure_is_not_retried(monkeypatch):
    monkeypatch.setattr(vworld_module.time, "sleep", lambda seconds: None)
    session = SslFailingSession()
    provider = VWorldProvider(
        Settings(provider="vworld", api_key="KEY", retries=3), session=session
    )

    with pytest.raises(TlsError):
        provider.get_parcel(37.5, 127.0)
    assert session.calls == 1


@pytest.mark.parametrize(
    ("status", "api_key", "expected"),
    [
        (CHECK_OK, "", EXIT_OK),
        (CHECK_TLS_FAILED, "", EXIT_TLS),
        (CHECK_TLS_FAILED, "KEY", EXIT_TLS),
        (CHECK_AUTH, "", EXIT_OK),
        (CHECK_AUTH, "KEY", EXIT_AUTH),
        (CHECK_QUOTA, "KEY", EXIT_QUOTA),
        (CHECK_CONNECT_FAILED, "", EXIT_NETWORK),
        (CHECK_API_ERROR, "KEY", EXIT_NETWORK),
    ],
)
def test_check_command_exit_codes(monkeypatch, capsys, status, api_key, expected):
    monkeypatch.setenv("LATLON_PROVIDER", "vworld")
    monkeypatch.setenv("VWORLD_API_KEY", api_key)
    monkeypatch.setenv("LATLON_CA_BUNDLE", "")
    monkeypatch.setattr(
        cli, "check_connection", lambda settings, url: ConnectionCheck(True, status)
    )

    assert cli.main(["check"]) == expected
    out = capsys.readouterr().out
    assert "TLS 인증서 검증" in out


def test_check_command_masks_api_key(monkeypatch, capsys, tmp_path):
    cert = tmp_path / "test.crt"
    cert.write_text(PEM_SAMPLE, encoding="utf-8")
    monkeypatch.setenv("LATLON_PROVIDER", "vworld")
    monkeypatch.setenv("VWORLD_API_KEY", "ABCD-SECRET-1234")
    monkeypatch.setenv("LATLON_CA_BUNDLE", str(cert))
    monkeypatch.setattr(
        cli, "check_connection", lambda settings, url: ConnectionCheck(str(cert), CHECK_OK)
    )

    assert cli.main(["check"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "SECRET" not in out
    assert "ABCD…" in out
    assert str(cert) in out


def test_settings_reads_ca_bundle_from_env(monkeypatch):
    monkeypatch.setenv("LATLON_CA_BUNDLE", "/etc/ssl/test.crt")
    assert Settings.from_env().ca_bundle == "/etc/ssl/test.crt"

    # requests가 이미 보는 표준 변수도 받아들인다.
    monkeypatch.delenv("LATLON_CA_BUNDLE")
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/etc/ssl/proxy.pem")
    assert Settings.from_env().ca_bundle == "/etc/ssl/proxy.pem"


def test_missing_key_still_beats_ca_bundle_check():
    """키가 없으면 인증서 검사보다 먼저 키 안내가 나와야 한다."""
    with pytest.raises(AuthError):
        VWorldProvider(Settings(provider="vworld", api_key="", ca_bundle="/없는/경로.crt"))
