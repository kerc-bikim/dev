from __future__ import annotations

import json
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from fakeredis import FakeRedis

from app.config import Settings
from app.cache import set_redis
from app.nrl.client import NrlClient, NrlError
from app.runtime import apply_runtime_policy, collect_policy_issues, RuntimePolicyError
from app.tls import (
    CaBundleError,
    apply_ca_bundle,
    load_verify,
    reset_ca_bundle_for_tests,
    resolve_ca_bundle,
)


PEM_STUB = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"


def _openssl(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["openssl", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _write_inspection_ca(tmp_path: Path) -> tuple[Path, Path, Path]:
    """사내 검사 장비를 흉내 내는 CA와 그 CA가 서명한 서버 인증서를 만든다."""
    ca_key = tmp_path / "ca.key"
    ca_crt = tmp_path / "ABC.crt"
    server_key = tmp_path / "server.key"
    server_csr = tmp_path / "server.csr"
    server_crt = tmp_path / "server.crt"
    ext = tmp_path / "ext.cnf"
    ext.write_text("basicConstraints=CA:FALSE\nsubjectAltName=IP:127.0.0.1,DNS:localhost\n")
    _openssl(
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-keyout",
        str(ca_key),
        "-out",
        str(ca_crt),
        "-days",
        "1",
        "-nodes",
        "-subj",
        "/CN=PDCC Inspection CA",
        cwd=tmp_path,
    )
    _openssl(
        "req",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        str(server_key),
        "-out",
        str(server_csr),
        "-subj",
        "/CN=localhost",
        cwd=tmp_path,
    )
    _openssl(
        "x509",
        "-req",
        "-in",
        str(server_csr),
        "-CA",
        str(ca_crt),
        "-CAkey",
        str(ca_key),
        "-CAcreateserial",
        "-out",
        str(server_crt),
        "-days",
        "1",
        "-extfile",
        str(ext),
        cwd=tmp_path,
    )
    return ca_crt, server_crt, server_key


class _CatalogHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = json.dumps({"NRLCatalog": {"element": [{"name": "sensor"}]}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def _serve_tls(server_crt: Path, server_key: Path) -> tuple[HTTPServer, str]:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(server_crt), str(server_key))
    httpd = HTTPServer(("127.0.0.1", 0), _CatalogHandler)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address[:2]
    return httpd, f"https://{host}:{port}"


def test_resolve_missing_file(tmp_path: Path):
    with pytest.raises(CaBundleError, match="찾을 수 없습니다"):
        resolve_ca_bundle(str(tmp_path / "ABC.crt"))


def test_resolve_rejects_der(tmp_path: Path):
    der = tmp_path / "ABC.crt"
    der.write_bytes(b"\x30\x82\x01\x00" + b"\x00" * 16)
    with pytest.raises(CaBundleError, match="DER"):
        resolve_ca_bundle(str(der))


def test_resolve_accepts_pem(tmp_path: Path):
    pem = tmp_path / "ABC.crt"
    pem.write_text(PEM_STUB)
    assert resolve_ca_bundle(str(pem)) == str(pem.resolve())


def test_load_verify_empty_uses_default():
    assert load_verify("") is True


def test_load_verify_appends_certifi(tmp_path: Path):
    pem = tmp_path / "ABC.crt"
    pem.write_text(PEM_STUB)
    combined = Path(load_verify(str(pem)))
    blob = combined.read_bytes()
    assert b"-----BEGIN CERTIFICATE-----" in blob
    assert PEM_STUB.encode() in blob
    import certifi

    assert Path(certifi.where()).read_bytes() in blob


def test_bad_bundle_fails_runtime_policy(tmp_path: Path):
    cfg = Settings(
        app_env="development",
        app_secret="unit-test-secret-not-default",
        ssl_ca_bundle=str(tmp_path / "missing.crt"),
    )
    _, errors = collect_policy_issues(cfg)
    assert any("SSL_CA_BUNDLE" in msg for msg in errors)
    with pytest.raises(RuntimePolicyError, match="SSL_CA_BUNDLE"):
        apply_runtime_policy(cfg)


def test_inspection_ca_makes_nrl_tls_succeed(tmp_path: Path):
    reset_ca_bundle_for_tests()
    set_redis(FakeRedis(decode_responses=True))
    ca_crt, server_crt, server_key = _write_inspection_ca(tmp_path)
    httpd, base = _serve_tls(server_crt, server_key)
    try:
        blocked = NrlClient(base_url=base, timeout=3, verify=True)
        with pytest.raises(NrlError, match="인증서 검증"):
            blocked.catalog(level="element")

        trusted = NrlClient(base_url=base, timeout=3, verify=load_verify(str(ca_crt)))
        data = trusted.catalog(level="element")
        assert data["NRLCatalog"]["element"][0]["name"] == "sensor"
    finally:
        httpd.shutdown()
        set_redis(None)
        reset_ca_bundle_for_tests()


def test_apply_ca_bundle_sets_ssl_cert_file(tmp_path: Path, monkeypatch):
    reset_ca_bundle_for_tests()
    pem = tmp_path / "ABC.crt"
    pem.write_text(PEM_STUB)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    cfg = Settings(ssl_ca_bundle=str(pem), app_secret="unit-test-secret-not-default")
    path = apply_ca_bundle(cfg)
    assert path
    assert Path(path).is_file()
    import os

    assert os.environ["SSL_CERT_FILE"] == path
    assert os.environ["REQUESTS_CA_BUNDLE"] == path
    reset_ca_bundle_for_tests()
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
