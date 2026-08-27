"""재시도 정책.

무엇을 다시 시도하지 **않을지** 정하는 것이 더 중요하다.

  * 인증 실패를 반복하면 장비 계정이 잠길 수 있다.
  * 신원 불일치는 설정 문제다. 다시 물어도 답이 같다.
  * 본문 오류도 같은 응답이 다시 온다.

이런 실패는 즉시 포기하고 운영자에게 보이는 편이 낫다. 회선 문제만 다시 시도한다.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.domain.enums import PollErrorCode

RETRYABLE_ERRORS = frozenset(
    {
        PollErrorCode.CONNECT_TIMEOUT,
        PollErrorCode.REQUEST_TIMEOUT,
        PollErrorCode.CONNECTION_REFUSED,
        PollErrorCode.DNS_FAILURE,
        PollErrorCode.HTTP_ERROR,
        PollErrorCode.STORAGE_ERROR,
    }
)

NON_RETRYABLE_ERRORS = frozenset(
    {
        PollErrorCode.AUTH_ERROR,
        PollErrorCode.IDENTITY_MISMATCH,
        PollErrorCode.INVALID_PAYLOAD,
        PollErrorCode.ADAPTER_ERROR,
        PollErrorCode.TLS_ERROR,
    }
)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 2
    delay_seconds: float = 10.0
    backoff_multiplier: float = 2.0
    max_delay_seconds: float = 60.0

    def should_retry(self, error_code: PollErrorCode | None, attempt: int) -> bool:
        if error_code is None:
            return False
        if attempt >= self.max_attempts:
            return False
        return error_code in RETRYABLE_ERRORS

    def delay_for(self, attempt: int) -> float:
        """1회차 실패 후 대기 시간. 회선이 흔들릴 때 몰아치지 않게 늘려 간다."""
        delay = self.delay_seconds * (self.backoff_multiplier ** max(0, attempt - 1))
        return min(delay, self.max_delay_seconds)
