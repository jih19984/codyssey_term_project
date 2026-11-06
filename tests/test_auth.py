from __future__ import annotations

import base64
import json

from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner
from sqlalchemy.orm import Session

from app.config import Settings
from app.main import create_app
from app.models import User
from app.security import hash_password
from tests.helpers import get_csrf_token


def create_user(db_session: Session, username: str = "whale01") -> User:
    user = User(
        username=username,
        password_hash=hash_password("Sea-shanty-9"),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def login(client: TestClient, username: str = "whale01", password: str = "Sea-shanty-9"):
    csrf_token = get_csrf_token(client, "/auth/login")
    return client.post(
        "/auth/login",
        data={
            "username": username,
            "password": password,
            "csrf_token": csrf_token,
        },
        follow_redirects=False,
    )


def decode_session_cookie(cookie: str, secret: str) -> dict[str, int]:
    signed_data = TimestampSigner(secret).unsign(cookie.encode("utf-8"))
    return json.loads(base64.b64decode(signed_data))


def test_login_success_sets_minimal_session_cookie(
    client: TestClient,
    db_session: Session,
    settings: Settings,
) -> None:
    user = create_user(db_session)

    response = login(client)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert decode_session_cookie(client.cookies["session"], settings.session_secret) == {
        "user_id": user.id
    }
    set_cookie = response.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "max-age=28800" in set_cookie
    assert "secure" not in set_cookie


def test_login_trims_username(client: TestClient, db_session: Session) -> None:
    create_user(db_session)

    response = login(client, username="  whale01  ")

    assert response.status_code == 303


def test_login_uses_same_error_for_unknown_user_and_wrong_password(
    client: TestClient,
    db_session: Session,
    settings: Settings,
) -> None:
    create_user(db_session)

    unknown_user = login(client, username="unknown")
    wrong_password = login(client, password="wrong-pass-9")

    assert unknown_user.status_code == 401
    assert wrong_password.status_code == 401
    assert "아이디 또는 비밀번호가 올바르지 않습니다." in unknown_user.text
    assert "아이디 또는 비밀번호가 올바르지 않습니다." in wrong_password.text
    session = decode_session_cookie(client.cookies["session"], settings.session_secret)
    assert "user_id" not in session


def test_login_rejects_invalid_length(client: TestClient) -> None:
    response = login(client, username="ab")

    assert response.status_code == 422
    assert "3~20자" in response.text


def test_login_rejects_username_with_disallowed_characters(client: TestClient) -> None:
    response = login(client, username="whale 01")

    assert response.status_code == 422
    assert "영문, 숫자" in response.text


def test_login_rejects_password_outside_length_range(client: TestClient) -> None:
    response = login(client, password="short")

    assert response.status_code == 422
    assert "8~100자" in response.text


def test_index_switches_actions_after_login(
    client: TestClient,
    db_session: Session,
) -> None:
    create_user(db_session)

    anonymous_home = client.get("/")
    assert ">회원가입<" in anonymous_home.text
    assert ">로그인<" in anonymous_home.text
    assert ">로그아웃<" not in anonymous_home.text

    login(client)
    authenticated_home = client.get("/")
    assert ">로그아웃<" in authenticated_home.text
    assert ">회원가입<" not in authenticated_home.text
    assert ">로그인<" not in authenticated_home.text


def test_logout_clears_session_and_is_idempotent(
    client: TestClient,
    db_session: Session,
) -> None:
    create_user(db_session)
    login(client)

    csrf_token = get_csrf_token(client, "/")
    first_logout = client.post(
        "/auth/logout",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )
    second_logout = client.post(
        "/auth/logout",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )

    assert first_logout.status_code == 303
    assert first_logout.headers["location"] == "/"
    assert "session" not in client.cookies
    assert "expires=thu, 01 jan 1970" in first_logout.headers["set-cookie"].lower()
    assert second_logout.status_code == 303
    assert second_logout.headers["location"] == "/auth/login"
    assert ">로그인<" in client.get("/").text


def test_production_cookie_is_secure(
    settings: Settings,
    db_session: Session,
) -> None:
    create_user(db_session)
    production_settings = Settings(
        _env_file=None,
        app_env="production",
        database_url=settings.database_url,
        session_secret=settings.session_secret,
        ai_api_key=settings.ai_api_key,
    )

    with TestClient(
        create_app(production_settings),
        base_url="https://testserver",
    ) as production_client:
        response = login(production_client)

    assert response.status_code == 303
    assert "secure" in response.headers["set-cookie"].lower()


def test_tampered_cookie_is_ignored_on_logout(client: TestClient) -> None:
    client.cookies.set("session", "tampered-cookie", domain="testserver.local", path="/")

    response = client.post("/auth/logout", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/auth/login"
    assert ">로그인<" in client.get("/").text
