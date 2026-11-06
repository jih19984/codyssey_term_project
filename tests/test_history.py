from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import User
from app.repositories.chat_repository import add_message, create_conversation
from app.security import hash_password
from tests.helpers import get_csrf_token


def create_user(db_session: Session, username: str) -> User:
    user = User(
        username=username,
        password_hash=hash_password("Sea-shanty-9"),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
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


def add_pair(
    db_session: Session,
    user_id: int,
    question: str,
    answer: str,
) -> int:
    conversation = create_conversation(db_session, user_id)
    add_message(db_session, user_id, conversation.id, "user", question)
    add_message(db_session, user_id, conversation.id, "assistant", answer)
    db_session.commit()
    return conversation.id


def test_history_page_redirects_anonymous_user_to_login(client: TestClient) -> None:
    response = client.get("/history", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/auth/login"


def test_history_api_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/me/chats")

    assert response.status_code == 401


def test_history_api_returns_only_current_users_chats_newest_first(
    client: TestClient,
    db_session: Session,
) -> None:
    alice = create_user(db_session, "alice")
    bob = create_user(db_session, "bob")
    first_id = add_pair(db_session, alice.id, "첫 질문", "첫 답변")
    second_id = add_pair(db_session, alice.id, "둘째 질문", "둘째 답변")
    add_pair(db_session, bob.id, "비밀 질문", "비밀 답변")
    login(client, alice.username)

    response = client.get("/api/me/chats")

    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 20
    assert body["offset"] == 0
    assert body["has_more"] is False
    assert [item["chat_id"] for item in body["items"]] == [second_id, first_id]
    assert [(item["question"], item["answer"]) for item in body["items"]] == [
        ("둘째 질문", "둘째 답변"),
        ("첫 질문", "첫 답변"),
    ]
    assert all(item["created_at"] for item in body["items"])
    assert "비밀 질문" not in response.text


def test_history_api_paginates_and_reports_has_more(
    client: TestClient,
    db_session: Session,
) -> None:
    user = create_user(db_session, "alice")
    chat_ids = [
        add_pair(db_session, user.id, f"질문 {index}", f"답변 {index}")
        for index in range(3)
    ]
    login(client, user.username)

    first_page = client.get("/api/me/chats", params={"limit": 2, "offset": 0})
    second_page = client.get("/api/me/chats", params={"limit": 2, "offset": 2})

    assert first_page.status_code == 200
    assert [item["chat_id"] for item in first_page.json()["items"]] == [
        chat_ids[2],
        chat_ids[1],
    ]
    assert first_page.json()["has_more"] is True
    assert [item["chat_id"] for item in second_page.json()["items"]] == [
        chat_ids[0]
    ]
    assert second_page.json()["has_more"] is False


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
    ],
)
def test_history_api_rejects_invalid_pagination(
    client: TestClient,
    db_session: Session,
    params: dict[str, int],
) -> None:
    user = create_user(db_session, "alice")
    login(client, user.username)

    response = client.get("/api/me/chats", params=params)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_history_page_shows_empty_state_and_navigation(
    client: TestClient,
    db_session: Session,
) -> None:
    user = create_user(db_session, "alice")
    login(client, user.username)

    response = client.get("/history")

    assert response.status_code == 200
    assert "아직 저장된 대화가 없습니다." in response.text
    assert 'href="/chat"' in response.text
    assert 'href="/"' in response.text


def test_history_page_escapes_user_content_and_renders_local_time_hook(
    client: TestClient,
    db_session: Session,
) -> None:
    user = create_user(db_session, "alice")
    add_pair(
        db_session,
        user.id,
        "<script>alert('question')</script>",
        '<img src=x onerror="alert(1)">',
    )
    login(client, user.username)

    response = client.get("/history")

    assert response.status_code == 200
    assert "<script>alert('question')</script>" not in response.text
    assert "&lt;script&gt;alert(&#39;question&#39;)&lt;/script&gt;" in response.text
    assert '&lt;img src=x onerror=&#34;alert(1)&#34;&gt;' in response.text
    assert "data-local-time" in response.text
    assert "/static/js/history.js" in response.text


def test_history_page_renders_previous_and_next_links(
    client: TestClient,
    db_session: Session,
) -> None:
    user = create_user(db_session, "alice")
    for index in range(3):
        add_pair(db_session, user.id, f"질문 {index}", f"답변 {index}")
    login(client, user.username)

    first_page = client.get("/history", params={"limit": 2, "offset": 0})
    second_page = client.get("/history", params={"limit": 2, "offset": 2})

    assert "이전" not in first_page.text
    assert 'href="/history?limit=2&offset=2"' in first_page.text
    assert 'href="/history?limit=2&offset=0"' in second_page.text
    assert "다음" not in second_page.text


def test_home_and_chat_pages_link_to_history(
    client: TestClient,
    db_session: Session,
) -> None:
    user = create_user(db_session, "alice")
    login(client, user.username)

    assert 'href="/history"' in client.get("/").text
    assert 'href="/history"' in client.get("/chat").text
