"""역할과 권한.

ADMIN 은 설정 전체, OPERATOR 는 장애 확인·유지보수·연결 시험, VIEWER 는 조회만.
이 매핑이 API 의존성에서 강제된다. 화면에서 버튼을 숨기는 것만으로는 부족하다.
"""
from __future__ import annotations

from enum import Enum

from app.db.models import UserRole


class Permission(str, Enum):
    READ = "read"
    OPERATE = "operate"
    CONFIGURE = "configure"
    ADMINISTER = "administer"


ROLE_PERMISSIONS: dict[UserRole, frozenset[Permission]] = {
    UserRole.VIEWER: frozenset({Permission.READ}),
    UserRole.OPERATOR: frozenset({Permission.READ, Permission.OPERATE}),
    UserRole.ADMIN: frozenset(
        {Permission.READ, Permission.OPERATE, Permission.CONFIGURE, Permission.ADMINISTER}
    ),
}


def has_permission(role: UserRole, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())
