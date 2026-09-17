from __future__ import annotations

import logging
from contextvars import ContextVar

from .config import INSECURE_SECRET, Settings, settings
from .tls import CaBundleError, apply_ca_bundle, configured_ca_bundle, load_verify

log = logging.getLogger("pdcc.runtime")

request_id_var: ContextVar[str] = ContextVar("pdcc_request_id", default="-")

STUB_USERNAMES = frozenset({"stub", "stub2"})


class RuntimePolicyError(RuntimeError):
    """프로덕션 기동을 막아야 하는 설정 오류."""


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get("-")
        return True


def is_production(env: str | None = None) -> bool:
    value = (env if env is not None else settings.app_env).strip().lower()
    return value in {"prod", "production"}


def cookie_secure(cfg: Settings | None = None) -> bool:
    cfg = cfg or settings
    if cfg.session_cookie_secure is not None:
        return bool(cfg.session_cookie_secure)
    return is_production(cfg.app_env)


def cookie_samesite(cfg: Settings | None = None) -> str:
    cfg = cfg or settings
    value = (cfg.session_cookie_samesite or "lax").strip().lower()
    if value not in {"lax", "strict", "none"}:
        return "lax"
    return value


def cors_origin_list(cfg: Settings | None = None) -> list[str]:
    cfg = cfg or settings
    raw = (cfg.cors_origins or "").strip()
    if raw:
        return [part.strip() for part in raw.split(",") if part.strip()]
    if is_production(cfg.app_env):
        return []
    return ["http://localhost:3000", "http://127.0.0.1:3000"]


def stub_login_allowed(cfg: Settings | None = None) -> bool:
    cfg = cfg or settings
    if is_production(cfg.app_env):
        return False
    return bool(cfg.allow_stub_login)


def collect_policy_issues(
    cfg: Settings | None = None,
) -> tuple[list[str], list[str]]:
    cfg = cfg or settings
    warnings: list[str] = []
    errors: list[str] = []
    prod = is_production(cfg.app_env)
    secret = (cfg.app_secret or "").strip()
    if not secret or secret == INSECURE_SECRET:
        msg = "APP_SECRET 가 비어 있거나 기본값입니다. 배포 시 반드시 교체하세요."
        (errors if prod else warnings).append(msg)
    if prod and cfg.dev_bootstrap_admin:
        errors.append("프로덕션에서 DEV_BOOTSTRAP_ADMIN=true 는 허용되지 않습니다.")
    if prod and cfg.allow_stub_login:
        errors.append("프로덕션에서 스텁 로그인(ALLOW_STUB_LOGIN)은 허용되지 않습니다.")
    if cfg.dev_bootstrap_admin and not prod:
        warnings.append("DEV_BOOTSTRAP_ADMIN=true — admin/admin 로그인이 허용됩니다.")
    if cookie_samesite(cfg) == "none" and not cookie_secure(cfg):
        errors.append("SameSite=None 쿠키는 Secure 플래그가 필요합니다.")
    try:
        load_verify(configured_ca_bundle(cfg))
    except CaBundleError as exc:
        errors.append(str(exc))
    return warnings, errors


def apply_runtime_policy(cfg: Settings | None = None) -> None:
    warnings, errors = collect_policy_issues(cfg)
    for msg in warnings:
        log.warning("%s", msg)
    if errors:
        for msg in errors:
            log.error("%s", msg)
        raise RuntimePolicyError(" ".join(errors))
    apply_ca_bundle(cfg)
