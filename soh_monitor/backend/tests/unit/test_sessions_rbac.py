"""세션 서명과 역할 권한."""
from __future__ import annotations

import time
import uuid

import pytest

from app.auth.rbac import Permission, has_permission
from app.auth.sessions import SessionError, issue_session, verify_session
from app.db.models import UserRole


def test_세션을_발급하고_검증한다():
    user_id = uuid.uuid4()
    token = issue_session(user_id, "secret")
    claims = verify_session(token, "secret")
    assert claims.user_id == user_id
    assert "secret" not in token
    assert str(user_id) not in token.split(".")[1]


def test_서명이_다르면_거부한다():
    token = issue_session(uuid.uuid4(), "secret")
    with pytest.raises(SessionError):
        verify_session(token, "other")


def test_만료된_세션은_거부한다():
    token = issue_session(uuid.uuid4(), "secret", now=1)
    with pytest.raises(SessionError, match="만료"):
        verify_session(token, "secret", now=int(time.time()))


def test_빈_토큰은_거부한다():
    with pytest.raises(SessionError):
        verify_session(None, "secret")


def test_역할별_권한():
    assert has_permission(UserRole.VIEWER, Permission.READ)
    assert not has_permission(UserRole.VIEWER, Permission.OPERATE)
    assert not has_permission(UserRole.VIEWER, Permission.CONFIGURE)
    assert has_permission(UserRole.OPERATOR, Permission.OPERATE)
    assert not has_permission(UserRole.OPERATOR, Permission.CONFIGURE)
    assert has_permission(UserRole.ADMIN, Permission.ADMINISTER)
    assert has_permission(UserRole.ADMIN, Permission.CONFIGURE)
