# region import statements
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.integrations.ai_client import AIClientError, AIClientProtocol, AITimeoutError
from app.logging_utils import (
    AI_CALL_FAILURE,
    AI_CALL_START,
    AI_CALL_SUCCESS,
    DB_SAVE_FAILURE,
    DB_SAVE_SUCCESS,
    log_event,
)
from app.repositories.chat_repository import (
    add_message,
    create_conversation,
    list_recent_messages,
)
# endregion

DEFAULT_CONTEXT_CONVERSATIONS = 5

# region 서비스 계층 예외 정의
class ChatServiceError(Exception):
    """채팅 처리 실패를 라우터에 전달하는 서비스 계층 예외."""


class ChatTimeoutError(ChatServiceError):
    """AI 응답이 제한 시간 안에 오지 않은 경우."""


class ChatUpstreamError(ChatServiceError):
    """AI 공급자가 요청 처리에 실패한 경우."""


class ChatPersistenceError(ChatServiceError):
    """문맥 조회 또는 새 대화 저장에 실패한 경우."""
# endregion

@dataclass(frozen=True)
class ChatResult:
    """ChatService.ask()가 반환하는 결과 객체."""
    chat_id: int
    answer: str
    created_at: datetime


class ChatService:
    def __init__(
        self,
        session: Session,
        ai_client: AIClientProtocol,
        ai_model: str,
        context_conversations: int = DEFAULT_CONTEXT_CONVERSATIONS,
    ) -> None:
        self._session = session
        self._ai_client = ai_client
        self._ai_model = ai_model
        self._context_conversations = context_conversations

    async def ask(
        self, user_id: int, question: str, *, request_id: str | None = None
    ) -> ChatResult:
        # request_id가 없으면(기존 호출부·테스트 호환용) 로그에 적을 값만 하나 만든다.
        # 실제 서비스 경로(routers/chat.py)는 항상 요청별 request_id를 넘긴다.
        request_id = request_id or uuid.uuid4().hex

        try:
            history = list_recent_messages(
                self._session,
                user_id,
                conversation_limit=self._context_conversations,
            )
            messages = [
                {"role": message.role, "content": message.content}
                for message in history
            ]
            # 읽기 쿼리가 연 트랜잭션과 DB 연결을 긴 AI 호출 동안 유지하지 않는다.
            self._session.rollback()
        except SQLAlchemyError as exc:
            self._session.rollback()
            log_event(
                DB_SAVE_FAILURE,
                request_id=request_id,
                user_id=user_id,
                stage="context_read",
                error_type=type(exc).__name__,
            )
            raise ChatPersistenceError("대화 문맥을 조회하지 못했습니다.") from exc

        messages.append({"role": "user", "content": question})
        log_event(
            AI_CALL_START,
            request_id=request_id,
            user_id=user_id,
            context_messages=len(history),
        )
        started_at = perf_counter()
        try:
            answer = await self._ai_client.generate(messages)
        except AITimeoutError as exc:
            log_event(
                AI_CALL_FAILURE,
                request_id=request_id,
                user_id=user_id,
                error_type=type(exc).__name__,
            )
            raise ChatTimeoutError("AI 응답 시간이 초과되었습니다.") from exc
        except AIClientError as exc:
            log_event(
                AI_CALL_FAILURE,
                request_id=request_id,
                user_id=user_id,
                error_type=type(exc).__name__,
            )
            raise ChatUpstreamError("AI 공급자 요청에 실패했습니다.") from exc
        latency_ms = max(0, round((perf_counter() - started_at) * 1000))
        log_event(
            AI_CALL_SUCCESS,
            request_id=request_id,
            user_id=user_id,
            latency_ms=latency_ms,
        )

        try:
            # 1. 대화 1개 만들기
            conversation = create_conversation(self._session, user_id)
            # 2. 질문 저장
            add_message(
                self._session,
                user_id,
                conversation.id,
                "user",
                question,
            )
            # 3. 답변 저장
            assistant_message = add_message(
                self._session,
                user_id,
                conversation.id,
                "assistant",
                answer,
                ai_model=self._ai_model,
                latency_ms=latency_ms,
            )
            # 4. 한 번에 확정
            self._session.commit()
        # 5. 실패하면 전부 롤백
        except SQLAlchemyError as exc:
            self._session.rollback()
            log_event(
                DB_SAVE_FAILURE,
                request_id=request_id,
                user_id=user_id,
                stage="persist",
                error_type=type(exc).__name__,
            )
            raise ChatPersistenceError("대화를 저장하지 못했습니다.") from exc

        log_event(
            DB_SAVE_SUCCESS,
            request_id=request_id,
            user_id=user_id,
            chat_id=conversation.id,
        )
        return ChatResult(
            chat_id=conversation.id,
            answer=assistant_message.content,
            created_at=assistant_message.created_at,
        )
