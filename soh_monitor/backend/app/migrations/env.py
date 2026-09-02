"""Alembic 실행 환경.

접속 문자열은 설정에서 만든다. alembic.ini 에 비밀번호를 적지 않는다.
`SOH_DATABASE_URL_OVERRIDE` 를 주면 그 값을 쓴다. SQLite 로 스키마를 검증할 때 쓴다.
"""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config.settings import get_settings
from app.db.base import Base
from app.db import models  # noqa: F401  모델 등록을 위한 import

config = context.config

# CLI 로 직접 실행할 때만 alembic.ini 의 로깅 설정을 쓴다. migrate 프로세스가
# 프로그램에서 호출할 때는 이미 구조화 로깅이 잡혀 있으므로 덮어쓰지 않는다.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    return get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
