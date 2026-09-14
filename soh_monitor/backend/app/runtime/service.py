"""주기 실행 프로세스의 공통 골격.

Collector 와 Edge Agent 가 함께 쓴다. 두 프로세스 모두 다음을 지켜야 한다.

  * SIGTERM 을 받으면 진행 중인 작업을 끝낸 뒤 종료한다. 컨테이너 재시작 때
    수집 결과를 잃지 않기 위한 것이다.
  * Tick 하나가 실패해도 루프는 계속 돈다. 한 장비의 예외로 전체가 멈추면 안 된다.
  * Tick 이 예정 주기보다 오래 걸리면 겹쳐 실행하지 않고 지연을 기록한다.
"""
from __future__ import annotations

import asyncio
import signal
import time
from typing import Awaitable, Callable

from app.observability.logging import get_logger

TickHandler = Callable[[], Awaitable[None]]


class PeriodicService:
    def __init__(
        self,
        name: str,
        interval_seconds: float,
        handler: TickHandler,
        *,
        max_ticks: int | None = None,
    ) -> None:
        self.name = name
        self.interval_seconds = interval_seconds
        self.handler = handler
        self.max_ticks = max_ticks
        self.tick_count = 0
        self.failure_count = 0
        self._stop = asyncio.Event()
        self._logger = get_logger(f"app.runtime.{name}", role=name)

    def request_stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        self._logger.info(
            "프로세스 시작", extra={"interval_seconds": self.interval_seconds}
        )
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                await self.handler()
            except Exception as exc:  # noqa: BLE001 - 루프를 죽이지 않는 것이 목적
                self.failure_count += 1
                self._logger.exception("Tick 실패", extra={"error": str(exc)})

            self.tick_count += 1
            elapsed = time.monotonic() - started
            if elapsed > self.interval_seconds:
                self._logger.warning(
                    "Tick 이 주기를 초과했다",
                    extra={"elapsed_seconds": round(elapsed, 3)},
                )

            if self.max_ticks is not None and self.tick_count >= self.max_ticks:
                break

            remaining = max(0.0, self.interval_seconds - elapsed)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                continue

        self._logger.info(
            "프로세스 종료",
            extra={"ticks": self.tick_count, "failures": self.failure_count},
        )


def install_signal_handlers(service: PeriodicService) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, service.request_stop)
        except NotImplementedError:
            # 일부 플랫폼(Windows)에서는 지원되지 않는다. 그때는 KeyboardInterrupt 로 처리된다.
            pass
