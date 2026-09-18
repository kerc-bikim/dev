"""SSRF 화이트리스트 단위 시험."""
from __future__ import annotations

import pytest

from app.net.ssrf import SsrfError, is_allowed_host, resolve_safe_host

RFC1918 = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]


class Test주소판정:
    @pytest.mark.parametrize("host", ["10.1.2.3", "172.16.0.9", "192.168.1.20"])
    def test_사설망은_허용한다(self, host):
        assert is_allowed_host(host, RFC1918) is True

    @pytest.mark.parametrize("host", ["8.8.8.8", "1.1.1.1", "example.org"])
    def test_공인주소와_이름은_여기서_거부한다(self, host):
        assert is_allowed_host(host, RFC1918) is False

    def test_메타데이터_주소는_허용_대역에_넣어도_거부한다(self):
        with pytest.raises(SsrfError, match="메타데이터"):
            resolve_safe_host("169.254.169.254", RFC1918 + ["169.254.0.0/16"])

    def test_URL_형태는_거부한다(self):
        with pytest.raises(SsrfError, match="URL"):
            resolve_safe_host("http://10.1.2.3", RFC1918)

    def test_빈_호스트는_거부한다(self):
        with pytest.raises(SsrfError):
            resolve_safe_host("  ", RFC1918)

    def test_허용_대역이_비면_거부한다(self):
        with pytest.raises(SsrfError, match="비어"):
            resolve_safe_host("10.1.2.3", [])

    def test_루프백은_기본_대역에서_거부한다(self):
        with pytest.raises(SsrfError, match="허용 대역"):
            resolve_safe_host("127.0.0.1", RFC1918)

    def test_루프백을_허용_목록에_넣으면_통과한다(self):
        resolved = resolve_safe_host("127.0.0.1", RFC1918 + ["127.0.0.0/8"])
        assert "127.0.0.1" in resolved.addresses

    def test_이름은_모든_해석_결과가_허용돼야_한다(self, monkeypatch):
        monkeypatch.setattr(
            "app.net.ssrf.socket.getaddrinfo",
            lambda *args, **kwargs: [
                (0, 0, 0, 0, ("10.0.0.8", 0)),
                (0, 0, 0, 0, ("8.8.8.8", 0)),
            ],
        )
        with pytest.raises(SsrfError, match="허용 대역"):
            resolve_safe_host("recorder.internal", RFC1918)

    def test_이름_해석_실패는_거부한다(self, monkeypatch):
        import socket

        def boom(*args, **kwargs):
            raise socket.gaierror("not found")

        monkeypatch.setattr("app.net.ssrf.socket.getaddrinfo", boom)
        with pytest.raises(SsrfError, match="해석"):
            resolve_safe_host("no-such-host.invalid", RFC1918)
