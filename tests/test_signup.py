from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User
from app.security import verify_password
from app.validation import USERNAME_MAX_LENGTH, USERNAME_MIN_LENGTH
from tests.helpers import get_csrf_token


def signup(client: TestClient, username: str, password: str):
    csrf_token = get_csrf_token(client, "/auth/signup")
    return client.post(
        "/auth/signup",
        data={
            "username": username,
            "password": password,
            "csrf_token": csrf_token,
        },
        follow_redirects=False,
    )


def test_signup_success_hashes_password(client: TestClient, db_session: Session) -> None:
    response = signup(client, "whale01", "Sea-shanty-9")

    assert response.status_code == 303

    # DB에 직접 들어가서 저장된 값을 확인 — 완료 조건 1번 검증
    user = db_session.scalar(select(User).where(User.username == "whale01"))
    assert user is not None
    assert user.password_hash != "Sea-shanty-9"  # 평문 그대로면 안 된다
    assert verify_password("Sea-shanty-9", user.password_hash)


def test_signup_rejects_duplicate_username(client: TestClient) -> None:
    # 완료 조건 2번 검증: 같은 아이디로 두 번 가입하면 두 번째는 거부
    signup(client, "whale02", "Sea-shanty-9")

    response = signup(client, "whale02", "Sea-shanty-9")

    assert response.status_code == 409


def test_signup_rejects_short_password(client: TestClient) -> None:
    # 입력 검증 요구사항: 최소 1개 이상의 검증 로직이 있어야 한다
    response = signup(client, "whale03", "short")

    assert response.status_code == 422


def test_signup_rejects_password_over_max_length(client: TestClient) -> None:
    response = signup(client, "whale04", "Aa!" + "a" * 98)

    assert response.status_code == 422
    assert "8~100자" in response.text


@pytest.mark.parametrize(
    "password",
    [
        "sea-shanty-9",  # 대문자 없음
        "SEA-SHANTY-9",  # 소문자 없음
        "SeaShanty9",  # 특수문자 없음
        "Sea 바다 shanty",  # 공백·한글은 특수문자로 치지 않음
    ],
)
def test_signup_rejects_password_missing_required_characters(
    client: TestClient, db_session: Session, password: str
) -> None:
    response = signup(client, "whale06", password)

    assert response.status_code == 422
    assert "대문자" in response.text
    assert db_session.scalar(select(User).where(User.username == "whale06")) is None


def test_signup_accepts_password_with_required_characters(client: TestClient) -> None:
    response = signup(client, "whale07", "Aa!" + "a" * 5)

    assert response.status_code == 303


@pytest.mark.parametrize(
    "length",
    [USERNAME_MIN_LENGTH - 1, USERNAME_MAX_LENGTH + 1],
)
def test_signup_rejects_username_outside_length_range(
    client: TestClient, length: int
) -> None:
    response = signup(client, "a" * length, "Sea-shanty-9")

    assert response.status_code == 422
    assert "3~20자" in response.text


@pytest.mark.parametrize(
    "length",
    [USERNAME_MIN_LENGTH, USERNAME_MAX_LENGTH],
)
def test_signup_accepts_username_at_length_boundary(
    client: TestClient, length: int
) -> None:
    response = signup(client, "a" * length, "Sea-shanty-9")

    assert response.status_code == 303


@pytest.mark.parametrize("username", ["whale 01", "whale!", "고래01", "whale🐳"])
def test_signup_rejects_username_with_disallowed_characters(
    client: TestClient,
    db_session: Session,
    username: str,
) -> None:
    response = signup(client, username, "Sea-shanty-9")

    assert response.status_code == 422
    assert "영문, 숫자" in response.text
    assert db_session.scalar(select(User).where(User.username == username)) is None


def test_signup_does_not_sanitize_password_before_hashing(
    client: TestClient, db_session: Session
) -> None:
    raw_password = "  바다 🐳 Whale! 9  "
    response = signup(client, "whale05", raw_password)

    assert response.status_code == 303
    user = db_session.scalar(select(User).where(User.username == "whale05"))
    assert user is not None
    assert verify_password(raw_password, user.password_hash)
    assert not verify_password(raw_password.strip(), user.password_hash)
