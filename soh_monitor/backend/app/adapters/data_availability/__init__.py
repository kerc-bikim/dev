"""SeedLink/FDSN 데이터 연속성 검사. 기록계 Adapter 가 아니다."""

from .checker import DataAvailabilityChecker, attach_availability, merge_availability

__all__ = ("DataAvailabilityChecker", "attach_availability", "merge_availability")
