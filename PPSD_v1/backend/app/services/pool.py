"""Shared thread pool for parallel PPSD computation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

from ..config import settings


@lru_cache(maxsize=1)
def get_executor() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(
        max_workers=settings.MAX_WORKERS,
        thread_name_prefix="ppsd",
    )
