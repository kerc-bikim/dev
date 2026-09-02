"""프로세스 골격과 비밀번호 처리 검증."""
from __future__ import annotations

import asyncio

import pytest

from app.auth.passwords import generate_password, hash_password, verify_password
from app.runtime.service import PeriodicService


class Test주기실행:
    async def test_지정한_횟수만큼_실행하고_멈춘다(self):
        calls = 0

        async def tick() -> None:
            nonlocal calls
            calls += 1

        service = PeriodicService("t", interval_seconds=0.01, handler=tick, max_ticks=3)
        await service.run()
        assert calls == 3
        assert service.failure_count == 0

    async def test_Tick이_실패해도_루프는_계속_돈다(self):
        """한 장비의 예외로 전체 수집이 멈추면 안 된다."""
        calls = 0

        async def tick() -> None:
            nonlocal calls
            calls += 1
            raise RuntimeError("장비 하나가 터졌다")

        service = PeriodicService("t", interval_seconds=0.01, handler=tick, max_ticks=3)
        await service.run()
        assert calls == 3
        assert service.failure_count == 3

    async def test_종료요청을_받으면_멈춘다(self):
        calls = 0

        async def tick() -> None:
            nonlocal calls
            calls += 1

        service = PeriodicService("t", interval_seconds=0.05, handler=tick)

        async def stop_soon() -> None:
            await asyncio.sleep(0.06)
            service.request_stop()

        await asyncio.gather(service.run(), stop_soon())
        assert 1 <= calls <= 3

    async def test_진행중인_Tick을_끝낸_뒤_종료한다(self):
        finished = False

        async def tick() -> None:
            nonlocal finished
            await asyncio.sleep(0.05)
            finished = True

        service = PeriodicService("t", interval_seconds=0.01, handler=tick, max_ticks=1)
        task = asyncio.create_task(service.run())
        await asyncio.sleep(0.01)
        service.request_stop()
        await task
        assert finished is True


class Test비밀번호:
    def test_해시와_검증(self):
        # 테스트 속도를 위해 비용을 낮춘다. 운영 기본값은 모듈 상수에 있다.
        stored = hash_password("관측소-비밀번호-1", n=2**10)
        assert verify_password("관측소-비밀번호-1", stored) is True
        assert verify_password("틀린비밀번호", stored) is False

    def test_같은_비밀번호도_해시가_다르다(self):
        first = hash_password("same-password", n=2**10)
        second = hash_password("same-password", n=2**10)
        assert first != second

    def test_저장형식에_파라미터가_포함된다(self):
        stored = hash_password("x", n=2**10, r=8, p=1)
        scheme, n, r, p, salt, digest = stored.split("$")
        assert scheme == "scrypt"
        assert (int(n), int(r), int(p)) == (2**10, 8, 1)
        assert len(bytes.fromhex(salt)) == 16
        assert len(bytes.fromhex(digest)) == 32

    def test_평문이_저장값에_남지_않는다(self):
        stored = hash_password("비밀번호평문", n=2**10)
        assert "비밀번호평문" not in stored

    @pytest.mark.parametrize("broken", ["", "not-a-hash", "scrypt$abc", "bcrypt$1$2$3$4$5"])
    def test_깨진_저장값은_거부한다(self, broken):
        assert verify_password("anything", broken) is False

    def test_빈_비밀번호는_해싱하지_않는다(self):
        with pytest.raises(ValueError):
            hash_password("")

    def test_생성된_비밀번호_길이(self):
        assert len(generate_password(24)) == 24
