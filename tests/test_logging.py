from __future__ import annotations

import asyncio
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings
from app.integrations.ai_client import AIProviderError, AITimeoutError
from app.main import create_app
from app.models import User
from app.security import hash_password
from app.services import chat_service as chat_service_module
from app.services.chat_service import ChatPersistenceError, ChatService
from tests.fakes import FakeAIClient
from tests.helpers import get_csrf_token, get_header_csrf_token

EVENT_LOGGER = "app.events"


def create_user(db_session: Session, username: str = "whale01") -> User:
    user = User(username=username, password_hash=hash_password("Sea-shanty-9"))
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


def test_get_request_logs_request_received(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger=EVENT_LOGGER):
        client.get("/health")

    assert "request_received" in caplog.text
    assert "path=/health" in caplog.text


def test_successful_chat_logs_ai_and_db_events_without_leaking_content(
    client: TestClient,
    db_session: Session,
    settings: Settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    create_user(db_session)
    login(client)
    csrf_token = get_header_csrf_token(client, "/chat")
    client.app.state.ai_client = FakeAIClient(response="절대 로그에 남으면 안 되는 답변")
    session_cookie_value = client.cookies["session"]

    with caplog.at_level(logging.INFO, logger=EVENT_LOGGER):
        response = client.post(
            "/api/chat",
            json={"question": "절대 로그에 남으면 안 되는 질문"},
            headers={"X-CSRF-Token": csrf_token},
        )

    assert response.status_code == 200
    assert "ai_call_start" in caplog.text
    assert "ai_call_success" in caplog.text
    assert "db_save_success" in caplog.text

    # 완료 조건: 비밀번호·세션·API 키·대화 원문은 로그에 남지 않는다.
    assert "Sea-shanty-9" not in caplog.text
    assert session_cookie_value not in caplog.text
    assert settings.ai_api_key not in caplog.text
    assert "절대 로그에 남으면 안 되는 질문" not in caplog.text
    assert "절대 로그에 남으면 안 되는 답변" not in caplog.text


@pytest.mark.parametrize(
    "error",
    [AITimeoutError("timeout"), AIProviderError(503, "unavailable")],
)
def test_ai_failure_logs_ai_call_failure(
    client: TestClient,
    db_session: Session,
    caplog: pytest.LogCaptureFixture,
    error: Exception,
) -> None:
    create_user(db_session)
    login(client)
    csrf_token = get_header_csrf_token(client, "/chat")
    client.app.state.ai_client = FakeAIClient(error=error)

    with caplog.at_level(logging.INFO, logger=EVENT_LOGGER):
        client.post(
            "/api/chat",
            json={"question": "질문"},
            headers={"X-CSRF-Token": csrf_token},
        )

    assert "ai_call_failure" in caplog.text
    assert type(error).__name__ in caplog.text


def test_persistence_failure_logs_db_save_failure(
    db_session: Session,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(username="whale02", password_hash=hash_password("Sea-shanty-9"))
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    def fail_on_save(*args, **kwargs):
        raise SQLAlchemyError("simulated write failure")

    monkeypatch.setattr(chat_service_module, "add_message", fail_on_save)
    client = FakeAIClient(response="answer")
    service = ChatService(db_session, client, ai_model="test-model")

    with caplog.at_level(logging.INFO, logger=EVENT_LOGGER):
        with pytest.raises(ChatPersistenceError):
            asyncio.run(service.ask(user.id, "question", request_id="req-123"))

    assert "db_save_failure" in caplog.text
    assert "request_id=req-123" in caplog.text


def test_unexpected_error_returns_generic_response_and_logs_stack_trace(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    app: FastAPI = create_app(settings)

    @app.get("/__test__/boom")
    def boom() -> None:
        raise RuntimeError("something only the server log should see")

    with TestClient(app, raise_server_exceptions=False) as test_client:
        with caplog.at_level(logging.INFO, logger=EVENT_LOGGER):
            response = test_client.get("/__test__/boom")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert body["error"]["request_id"]
    # 클라이언트 응답에는 내부 메시지가 절대 노출되지 않는다.
    assert "something only the server log should see" not in response.text

    # 서버 로그에는 스택 트레이스와 request_id가 남아 있어야 진단이 가능하다.
    assert "unhandled_error" in caplog.text
    assert "something only the server log should see" in caplog.text
