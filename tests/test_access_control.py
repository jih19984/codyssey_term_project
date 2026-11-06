from __future__ import annotations

import base64
from collections.abc import Generator
import json

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner
from sqlalchemy.orm import Session

from app.access_control import (
    require_header_csrf,
    require_page_user,
    require_user,
)
from app.config import Settings
from app.db import get_db
from app.main import create_app
from app.models import User
from app.repositories.chat_repository import create_conversation, get_conversation
from app.security import hash_password
from tests.helpers import get_csrf_token


def create_user(db: Session, username: str) -> User:
    user = User(
        username=username,
        password_hash=hash_password("Sea-shanty-9"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def login(client: TestClient, username: str) -> None:
    csrf_token = get_csrf_token(client, "/auth/login")
    response = client.post(
        "/auth/login",
        data={
            "username": username,
            "password": "Sea-shanty-9",
            "csrf_token": csrf_token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def encode_session_cookie(payload: dict[str, object], secret: str) -> str:
    encoded = base64.b64encode(json.dumps(payload).encode("utf-8"))
    return TimestampSigner(secret).sign(encoded).decode("utf-8")


@pytest.fixture
def security_client(settings: Settings) -> Generator[TestClient, None, None]:
    app: FastAPI = create_app(settings)

    @app.get("/__test__/protected-page")
    def protected_page(current_user: User = Depends(require_page_user)) -> dict[str, int]:
        return {"user_id": current_user.id}

    @app.get("/__test__/protected-api")
    def protected_api(
        user_id: int | None = None,
        current_user: User = Depends(require_user),
    ) -> dict[str, int]:
        # A client-provided user_id never replaces the authenticated identity.
        return {"user_id": current_user.id}

    @app.post("/__test__/protected-api")
    def protected_api_post(
        current_user: User = Depends(require_user),
        _csrf: None = Depends(require_header_csrf),
    ) -> dict[str, int]:
        return {"user_id": current_user.id}

    @app.get("/__test__/conversations/{conversation_id}")
    def protected_conversation(
        conversation_id: int,
        current_user: User = Depends(require_user),
        db: Session = Depends(get_db),
    ) -> dict[str, int]:
        conversation = get_conversation(db, current_user.id, conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404)
        return {"conversation_id": conversation.id}

    with TestClient(app) as test_client:
        yield test_client


def test_anonymous_page_redirects_to_login(security_client: TestClient) -> None:
    response = security_client.get(
        "/__test__/protected-page",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/auth/login"


def test_anonymous_api_returns_401(security_client: TestClient) -> None:
    response = security_client.get("/__test__/protected-api")

    assert response.status_code == 401
    assert response.json() == {"detail": "로그인이 필요합니다."}


def test_authenticated_identity_cannot_be_overridden(
    security_client: TestClient,
    db_session: Session,
) -> None:
    user = create_user(db_session, "whale01")
    other_user = create_user(db_session, "whale02")
    login(security_client, user.username)

    response = security_client.get(
        "/__test__/protected-api",
        params={"user_id": other_user.id},
    )

    assert response.status_code == 200
    assert response.json() == {"user_id": user.id}


def test_deleted_user_session_is_rejected_and_cleared(
    security_client: TestClient,
    db_session: Session,
) -> None:
    user = create_user(db_session, "whale01")
    login(security_client, user.username)
    db_session.delete(user)
    db_session.commit()

    response = security_client.get("/__test__/protected-api")

    assert response.status_code == 401
    assert "session" not in security_client.cookies


def test_invalid_user_id_type_is_rejected_and_session_is_cleared(
    security_client: TestClient,
    settings: Settings,
) -> None:
    cookie = encode_session_cookie(
        {"user_id": "1", "csrf_token": "should-also-be-cleared"},
        settings.session_secret,
    )
    security_client.cookies.set(
        "session",
        cookie,
        domain="testserver.local",
        path="/",
    )

    response = security_client.get("/__test__/protected-api")

    assert response.status_code == 401
    assert "session" not in security_client.cookies


def test_other_users_conversation_is_hidden(
    security_client: TestClient,
    db_session: Session,
) -> None:
    user = create_user(db_session, "whale01")
    other_user = create_user(db_session, "whale02")
    conversation = create_conversation(db_session, other_user.id, "private")
    db_session.commit()
    login(security_client, user.username)

    response = security_client.get(
        f"/__test__/conversations/{conversation.id}",
    )

    assert response.status_code == 404


def test_auth_forms_render_csrf_token(security_client: TestClient) -> None:
    assert get_csrf_token(security_client, "/auth/login")
    assert get_csrf_token(security_client, "/auth/signup")


def test_logout_form_renders_csrf_token(
    security_client: TestClient,
    db_session: Session,
) -> None:
    user = create_user(db_session, "whale01")
    login(security_client, user.username)

    assert get_csrf_token(security_client, "/")


@pytest.mark.parametrize("path", ["/auth/login", "/auth/signup"])
def test_public_form_post_without_csrf_is_rejected(
    security_client: TestClient,
    path: str,
) -> None:
    response = security_client.post(
        path,
        data={"username": "whale01", "password": "Sea-shanty-9"},
    )

    assert response.status_code == 403


def test_invalid_form_csrf_is_rejected(security_client: TestClient) -> None:
    get_csrf_token(security_client, "/auth/signup")

    response = security_client.post(
        "/auth/signup",
        data={
            "username": "whale01",
            "password": "Sea-shanty-9",
            "csrf_token": "invalid-token",
        },
    )

    assert response.status_code == 403


def test_csrf_token_from_another_client_is_rejected(
    security_client: TestClient,
) -> None:
    first_token = get_csrf_token(security_client, "/auth/signup")

    with TestClient(security_client.app) as other_client:
        get_csrf_token(other_client, "/auth/signup")
        response = other_client.post(
            "/auth/signup",
            data={
                "username": "whale01",
                "password": "Sea-shanty-9",
                "csrf_token": first_token,
            },
        )

    assert response.status_code == 403


def test_logout_without_csrf_is_rejected(
    security_client: TestClient,
    db_session: Session,
) -> None:
    user = create_user(db_session, "whale01")
    login(security_client, user.username)

    response = security_client.post("/auth/logout", follow_redirects=False)

    assert response.status_code == 403


def test_api_header_csrf_is_required(
    security_client: TestClient,
    db_session: Session,
) -> None:
    user = create_user(db_session, "whale01")
    login(security_client, user.username)
    csrf_token = get_csrf_token(security_client, "/")

    missing = security_client.post("/__test__/protected-api")
    invalid = security_client.post(
        "/__test__/protected-api",
        headers={"X-CSRF-Token": "invalid-token"},
    )
    valid = security_client.post(
        "/__test__/protected-api",
        headers={"X-CSRF-Token": csrf_token},
    )

    assert missing.status_code == 403
    assert invalid.status_code == 403
    assert valid.status_code == 200
    assert valid.json() == {"user_id": user.id}


def test_login_rotates_csrf_token(
    security_client: TestClient,
    db_session: Session,
) -> None:
    user = create_user(db_session, "whale01")
    before_login = get_csrf_token(security_client, "/auth/login")

    response = security_client.post(
        "/auth/login",
        data={
            "username": user.username,
            "password": "Sea-shanty-9",
            "csrf_token": before_login,
        },
        follow_redirects=False,
    )
    after_login = get_csrf_token(security_client, "/")

    assert response.status_code == 303
    assert after_login != before_login
