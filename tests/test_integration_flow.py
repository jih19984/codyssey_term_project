from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.integrations.ai_client import AITimeoutError
from tests.fakes import FakeAIClient
from tests.helpers import get_csrf_token, get_header_csrf_token


def signup(client: TestClient, username: str, password: str) -> None:
    csrf_token = get_csrf_token(client, "/auth/signup")
    response = client.post(
        "/auth/signup",
        data={"username": username, "password": password, "csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert response.status_code == 303


def login(client: TestClient, username: str, password: str) -> None:
    csrf_token = get_csrf_token(client, "/auth/login")
    response = client.post(
        "/auth/login",
        data={"username": username, "password": password, "csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert response.status_code == 303


def ask(client: TestClient, question: str) -> dict:
    csrf_token = get_header_csrf_token(client, "/chat")
    response = client.post(
        "/api/chat",
        json={"question": question},
        headers={"X-CSRF-Token": csrf_token},
    )
    return response


def test_signup_login_ask_and_see_answer_and_history(
    client: TestClient, db_session: Session
) -> None:
    # 과제 핵심 흐름 전체를 실제 HTTP 요청으로 한 번에 훑는다:
    # 회원가입 -> 로그인 -> 질문 -> 같은 화면에서 응답 확인 -> 기록 조회.
    signup(client, "orca01", "Deep-sea-9")
    login(client, "orca01", "Deep-sea-9")
    client.app.state.ai_client = FakeAIClient(response="바다의 깊이는 평균 약 3,700m입니다.")

    first = ask(client, "바다의 평균 깊이는 얼마야?")
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["answer"] == "바다의 깊이는 평균 약 3,700m입니다."
    assert first_body["chat_id"]

    # 후속 질문도 같은 화면 흐름(csrf 토큰 재발급 포함)으로 문제없이 이어진다.
    second = ask(client, "방금 질문을 기억해?")
    assert second.status_code == 200

    history_response = client.get("/api/me/chats")
    assert history_response.status_code == 200
    history_body = history_response.json()
    assert [item["question"] for item in history_body["items"]] == [
        "방금 질문을 기억해?",
        "바다의 평균 깊이는 얼마야?",
    ]

    history_page = client.get("/history")
    assert history_page.status_code == 200
    assert "바다의 평균 깊이는 얼마야?" in history_page.text
    assert "바다의 깊이는 평균 약 3,700m입니다." in history_page.text


def test_ai_failure_returns_consistent_error_and_leaves_no_partial_history(
    client: TestClient, db_session: Session
) -> None:
    signup(client, "orca02", "Deep-sea-9")
    login(client, "orca02", "Deep-sea-9")
    client.app.state.ai_client = FakeAIClient(error=AITimeoutError("timeout"))

    response = ask(client, "AI가 응답 못하면 어떻게 돼?")

    assert response.status_code == 504
    body = response.json()
    assert body["error"]["code"] == "AI_TIMEOUT"
    assert body["error"]["request_id"]

    history_response = client.get("/api/me/chats")
    assert history_response.json()["items"] == []
