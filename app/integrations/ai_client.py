# region 0. import statements
# from __future__ import는 파일의 첫 문장이어야 하고(주석은 예외),
# 다른 import도 상수 같은 코드보다 위에 둬야 ruff 검사(F404, E402)를 통과한다.
from __future__ import annotations
from typing import Protocol
import httpx
from app.config import Settings
# endregion

# Anthropic API 버전. 게이트웨이가 요구하는 값이라 모델/엔드포인트와 무관하게 고정한다.
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 1024

# region 1. AI 클라이언트 예외 정의
class AIClientError(Exception):
    """AI 호출이 실패했을 때의 공통 베이스 예외."""


class AITimeoutError(AIClientError):
    """지정한 시간 안에 AI 응답이 오지 않았을 때 발생한다."""


class AIConnectionError(AIClientError):
    """AI 공급자와 네트워크 연결을 맺거나 유지하지 못했을 때 발생한다."""


class AIProviderError(AIClientError):
    """AI 공급자(게이트웨이)가 오류 상태 코드를 반환했을 때 발생한다."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"AI provider error {status_code}: {message}")
        self.status_code = status_code
# endregion

# region 2. AI 클라이언트 프로토콜 정의 - 인터페이스와 동일
class AIClientProtocol(Protocol):
    # Protocol: "이 모양의 generate 메서드를 가진 객체라면 전부 AIClient로 취급한다"는
    # 구조적 타이핑(structural typing)이다. 구현 클래스가 달라도 이 모양만 맞추면
    # 호출하는 쪽 코드를 바꾸지 않고 교체할 수 있다.
    async def generate(self, messages: list[dict[str, str]]) -> str: ...
# endregion

# region 3. Anthropic 게이트웨이 클라이언트 구현
class AnthropicGatewayClient:
    """Codyssey 'Neito' 게이트웨이의 Anthropic 네이티브 엔드포인트(/v1/messages)를 호출한다."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._timeout_seconds = timeout_seconds
        # transport는 테스트에서 실제 네트워크 없이 가짜 응답을 주입하기 위한 용도.
        # 운영에서는 None으로 두면 httpx가 기본(실제) 전송 방식을 사용한다.
        self._transport = transport

    def __repr__(self) -> str:
        # api_key를 절대 노출하지 않는다 (로그에 이 객체가 찍혀도 키가 새면 안 된다).
        return f"AnthropicGatewayClient(model={self._model!r}, base_url={self._base_url!r})"

    async def generate(self, messages: list[dict[str, str]]) -> str:
        # 큰 흐름만 보이게 단계별 함수로 나눈다: 보내기 → 상태 코드 확인 → 답변 꺼내기.
        response = await self._send(messages)
        if response.status_code >= 400:
            raise AIProviderError(response.status_code, response.text)
        return self._extract_answer(response)

    async def _send(self, messages: list[dict[str, str]]) -> httpx.Response:
        # 네트워크 단계의 오류만 여기서 앱 전용 예외로 바꾼다.
        # TimeoutException은 RequestError의 하위 클래스라서 반드시 먼저 잡아야 한다.
        # 순서가 바뀌면 시간 초과도 연결 실패로 분류되어 504 대신 502가 나간다.
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds, transport=self._transport
            ) as client:
                return await client.post(
                    f"{self._base_url}/v1/messages",
                    headers=self._headers(),
                    json={
                        "model": self._model,
                        "max_tokens": DEFAULT_MAX_TOKENS,
                        "messages": messages,
                    },
                )
        except httpx.TimeoutException as exc:
            # from exc: 원래 httpx 예외를 원인으로 남겨 스택 트레이스에서 추적할 수 있게 한다.
            raise AITimeoutError(
                f"AI request timed out after {self._timeout_seconds}s"
            ) from exc
        except httpx.RequestError as exc:
            raise AIConnectionError("AI provider connection failed") from exc

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

    @staticmethod
    def _extract_answer(response: httpx.Response) -> str:
        # 응답 JSON의 모양이 예상(content[0].text)과 다르거나 답변이 비어 있으면
        # 공급자 오류로 본다.
        try:
            answer = response.json()["content"][0]["text"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise AIProviderError(
                response.status_code, "invalid response payload"
            ) from exc
        if not isinstance(answer, str) or not answer:
            raise AIProviderError(response.status_code, "empty response content")
        return answer
# endregion

# region 4. 운영 AI 클라이언트 생성
def create_ai_client(settings: Settings) -> AIClientProtocol:
    """설정값으로 운영 AI 클라이언트를 만든다."""
    return AnthropicGatewayClient(
        api_key=settings.ai_api_key,
        base_url=settings.ai_base_url,
        model=settings.ai_model,
        timeout_seconds=settings.ai_timeout_seconds,
    )
# endregion