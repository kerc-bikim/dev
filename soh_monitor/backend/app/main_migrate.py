"""migrate 프로세스 실행점.

컨테이너 기동 순서에서 api·collector 보다 먼저 한 번 실행된다.
마이그레이션을 적용하고 카탈로그·기본 프로파일·초기 관리자를 넣는다.
"""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from app.config.settings import get_settings
from app.db.seed import seed_all
from app.db.session import session_scope
from app.observability.logging import configure_logging, get_logger

BACKEND_DIR = Path(__file__).resolve().parents[1]


def run_migrations() -> None:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "app" / "migrations"))
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, role="migrate", json_output=settings.is_production)
    logger = get_logger("app.migrate", role="migrate")

    logger.info("마이그레이션 시작")
    run_migrations()
    logger.info("마이그레이션 완료")

    with session_scope() as session:
        result = seed_all(session)

    logger.info(
        "초기 데이터 적재 완료",
        extra={
            "metric_definitions_inserted": result["metric_definitions_inserted"],
            "metric_definitions_updated": result["metric_definitions_updated"],
        },
    )

    generated = result.get("generated_admin_password")
    if generated:
        # SOH_BOOTSTRAP_ADMIN_PASSWORD 를 주지 않은 경우에만 1회용 비밀번호를 만들어
        # 여기서 한 번 출력한다. 저장하지 않으므로 다시 볼 수 없고, 첫 로그인 후 변경이 강제된다.
        logger.warning("초기 관리자 비밀번호를 생성했다. 아래 값을 옮겨 적고 첫 로그인 후 변경한다")
        print(f"[초기 관리자 비밀번호] {generated}", flush=True)


if __name__ == "__main__":
    main()
