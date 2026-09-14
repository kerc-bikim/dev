"""토지 정보 제공자 구현."""

from __future__ import annotations

from ..config import Settings
from ..errors import InputError
from .base import LandDataProvider
from .mock import MockProvider
from .vworld import VWorldProvider

__all__ = ["LandDataProvider", "MockProvider", "VWorldProvider", "build_provider"]


def build_provider(settings: Settings) -> LandDataProvider:
    """설정의 `provider` 값에 맞는 제공자를 만든다."""
    name = (settings.provider or "mock").lower()
    if name == "mock":
        return MockProvider()
    if name == "vworld":
        return VWorldProvider(settings)
    raise InputError(f"알 수 없는 provider 입니다: {settings.provider} (mock 또는 vworld)")
