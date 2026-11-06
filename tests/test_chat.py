from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.integrations.ai_client import AIProviderError, AITimeoutError
from app.models import Conversation, Message, User
from app.services.chat_service import ChatPersistenceError, ChatService
from app.security import hash_password
from tests.fakes import FakeAIClient
from tests.helpers import get_csrf_token, get_header_csrf_token


def create_user(db_session: Session, username: str = "whale01") -> User:
    user = User(
        username=username,
        password_hash=hash_password("Sea-shanty-9"),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def login(client: TestClient, username: str = "whale01", password: str = "Sea-shanty-9") -> None:
    csrf_token = get_csrf_token(client, "/auth/login")
    response = client.post(
        "/auth/login",
        data={"username": username, "password": password, "csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_chat_page_redirects_anonymous_user_to_login(client: TestClient) -> None:
    response = client.get("/chat", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/auth/login"


def test_chat_page_renders_for_authenticated_user(
    client: TestClient, db_session: Session
) -> None:
    create_user(db_session)
    login(client)

    response = client.get("/chat")

    assert response.status_code == 200
    assert "data-csrf-token" in response.text
    assert "chat-form" in response.text


def test_api_chat_requires_authentication(client: TestClient) -> None:
    response = client.post("/api/chat", json={"question": "안녕"})

    assert response.status_code == 401


def test_api_chat_requires_csrf_header(
    client: TestClient, db_session: Session
) -> None:
    create_user(db_session)
    login(client)

    response = client.post("/api/chat", json={"question": "안녕"})

    assert response.status_code == 403


def test_api_chat_rejects_blank_question(
    client: TestClient, db_session: Session
) -> None:
    create_user(db_session)
    login(client)
    csrf_token = get_header_csrf_token(client, "/chat")

    response = client.post(
        "/api/chat",
        json={"question": "   "},
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["request_id"]


def test_api_chat_rejects_question_over_length_limit(
    client: TestClient, db_session: Session
) -> None:
    create_user(db_session)
    login(client)
    csrf_token = get_header_csrf_token(client, "/chat")

    response = client.post(
        "/api/chat",
        json={"question": "a" * 2001},
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 422


def test_api_chat_returns_and_saves_ai_answer(
    client: TestClient, db_session: Session
) -> None:
    create_user(db_session)
    login(client)
    csrf_token = get_header_csrf_token(client, "/chat")
    client.app.state.ai_client = FakeAIClient(response="세션 기반으로 동작해요.")

    response = client.post(
        "/api/chat",
        json={"question": "  FastAPI 세션이 뭐야?  "},
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "세션 기반으로 동작해요."
    assert body["chat_id"]
    assert body["request_id"]
    assert body["created_at"]
    conversation = db_session.get(Conversation, body["chat_id"])
    assert conversation is not None
    db_session.refresh(conversation)
    assert [(message.role, message.content) for message in conversation.messages] == [
        ("user", "FastAPI 세션이 뭐야?"),
        ("assistant", "세션 기반으로 동작해요."),
    ]


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code"),
    [
        (AITimeoutError("timeout"), 504, "AI_TIMEOUT"),
        (AIProviderError(503, "unavailable"), 502, "AI_UPSTREAM_ERROR"),
    ],
)
def test_api_chat_maps_ai_errors(
    client: TestClient,
    db_session: Session,
    error: Exception,
    expected_status: int,
    expected_code: str,
) -> None:
    create_user(db_session)
    login(client)
    csrf_token = get_header_csrf_token(client, "/chat")
    client.app.state.ai_client = FakeAIClient(error=error)

    response = client.post(
        "/api/chat",
        json={"question": "질문"},
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == expected_status
    body = response.json()
    assert body["error"]["code"] == expected_code
    assert body["error"]["message"]
    assert body["error"]["request_id"]
    assert db_session.query(Conversation).count() == 0
    assert db_session.query(Message).count() == 0


def test_api_chat_maps_database_error(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_user(db_session)
    login(client)
    csrf_token = get_header_csrf_token(client, "/chat")

    async def fail_to_save(self, user_id: int, question: str, *, request_id: str | None = None):
        raise ChatPersistenceError("simulated database error")

    monkeypatch.setattr(ChatService, "ask", fail_to_save)

    response = client.post(
        "/api/chat",
        json={"question": "질문"},
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "DB_WRITE_ERROR"
    assert body["error"]["message"]
    assert body["error"]["request_id"]
