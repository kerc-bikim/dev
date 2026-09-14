"""응답 캐시 검증."""

from __future__ import annotations

import time

from latlon_converter.cache import NullCache, ResponseCache, build_cache, make_key


def test_key_ignores_credentials():
    base = {"pnu": "1168010100108080000", "format": "json"}
    assert make_key("vworld", "u", {**base, "key": "A", "domain": "http://a"}) == make_key(
        "vworld", "u", {**base, "key": "B", "domain": "http://b"}
    )


def test_key_changes_with_request_params():
    assert make_key("vworld", "u", {"pnu": "1"}) != make_key("vworld", "u", {"pnu": "2"})


def test_roundtrip(tmp_path):
    cache = ResponseCache(tmp_path / "cache.sqlite")
    params = {"pnu": "1168010100108080000"}
    assert cache.get("vworld", "url", params) is None

    cache.set("vworld", "url", params, {"response": {"status": "OK"}})
    assert cache.get("vworld", "url", params) == {"response": {"status": "OK"}}
    cache.close()


def test_expired_entry_is_dropped(tmp_path):
    cache = ResponseCache(tmp_path / "cache.sqlite", ttl_days=1)
    params = {"pnu": "1"}
    cache.set("vworld", "url", params, {"a": 1})
    # 저장 시각을 이틀 전으로 되돌린다.
    cache._conn.execute("UPDATE response_cache SET fetched_at = ?", (time.time() - 2 * 86400,))
    cache._conn.commit()
    assert cache.get("vworld", "url", params) is None
    cache.close()


def test_zero_ttl_never_expires(tmp_path):
    cache = ResponseCache(tmp_path / "cache.sqlite", ttl_days=0)
    cache.set("vworld", "url", {"pnu": "1"}, {"a": 1})
    cache._conn.execute("UPDATE response_cache SET fetched_at = ?", (time.time() - 3650 * 86400,))
    cache._conn.commit()
    assert cache.get("vworld", "url", {"pnu": "1"}) == {"a": 1}
    cache.close()


def test_build_cache_switches_to_null(tmp_path):
    assert isinstance(build_cache("", 30), NullCache)
    assert isinstance(build_cache(str(tmp_path / "c.sqlite"), 30, enabled=False), NullCache)
    cache = build_cache(str(tmp_path / "c.sqlite"), 30)
    assert isinstance(cache, ResponseCache)
    cache.close()


def test_provider_reuses_cached_response(tmp_path):
    """캐시가 있으면 같은 요청을 두 번 보내지 않는다."""
    from latlon_converter.config import Settings
    from latlon_converter.providers.vworld import VWorldProvider

    class CountingSession:
        def __init__(self, payload):
            self.payload = payload
            self.calls = 0

        def get(self, url, params=None, timeout=None):
            self.calls += 1
            return _Response(self.payload)

    payload = {
        "response": {
            "status": "OK",
            "result": {
                "featureCollection": {
                    "features": [
                        {
                            "properties": {
                                "pnu": "1168010100108080000",
                                "jibun": "808 대",
                                "addr": "서울특별시 강남구 역삼동 808",
                            }
                        }
                    ]
                }
            },
        }
    }
    session = CountingSession(payload)
    cache = ResponseCache(tmp_path / "cache.sqlite")
    settings = Settings(provider="vworld", api_key="KEY", domain="http://localhost")
    provider = VWorldProvider(settings, cache=cache, session=session)

    first = provider.get_parcel(37.50435, 127.02505)
    second = provider.get_parcel(37.50435, 127.02505)
    assert first is not None and second is not None
    assert first.pnu == second.pnu
    assert session.calls == 1
    cache.close()


class _Response:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload
