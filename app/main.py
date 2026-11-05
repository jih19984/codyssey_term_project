from __future__ import annotations

import uuid

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import Settings, get_settings
from app.asgi_logging import ASGILoggingMiddleware
from app.access_control import get_current_user, get_or_create_csrf_token
from app.db import create_database_engine, create_session_factory
from app.integrations.ai_client import create_ai_client
from app.logging_utils import REQUEST_RECEIVED, UNHANDLED_ERROR, log_event, log_exception
from app.models import User
from app.routers import auth, chat, history
from app.templating import TEMPLATES_DIR, templates


# request_id가 없으면 새로 만들어 반환. 있으면 그대로 반환
def _request_id(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    return request_id if isinstance(request_id, str) else uuid.uuid4().hex


def _extract_validation_message(exc: RequestValidationError) -> str:
    # pydantic의 field_validator에서 raise ValueError(message)로 던진 경우,
    # exc.errors()[0]["msg"]에는 "Value error, message" 형태로 접두어가 붙는다.
    # ctx.error에 원래 예외 객체가 그대로 들어있어서, 그걸 str()하면 접두어 없는
    # 원본 메시지를 그대로 쓸 수 있다.
    first_error = exc.errors()[0]
    original_error = first_error.get("ctx", {}).get("error")
    if original_error is not None:
        return str(original_error)
    return first_error.get("msg", "요청 값이 올바르지 않습니다.")

# FastAPI 애플리케이션을 생성하는 함수
def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = create_database_engine(settings.database_url)
    app = FastAPI(title="AI Chatbot", version="0.1.0")
    app.state.settings = settings
    app.state.engine = engine
    # 운영 ai_client 생성 후 app.state.ai_client에 저장.
    app.state.ai_client = create_ai_client(settings)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        session_cookie="session",
        max_age=60 * 60 * 8,
        same_site="lax",
        https_only=settings.is_production,
    )

    # get_db()가 request.app.state.session_factory로 이걸 꺼내 쓴다.
    app.state.session_factory = create_session_factory(engine)
    app.mount("/static", StaticFiles(directory=TEMPLATES_DIR.parent / "static"), name="static")

    """
    미들웨어 본체: 브라우저가 보낸 요청이 서버에 도착하면 가장 먼저 만나는 단계
    """
    #region 1. ID 정하기 + 요청 수신 로그 + 다음 단계로 넘기기
    @app.middleware("http")
    # request: 들어온 요청 정보
    # call_next: "다음 단계(라우터)로 넘기기" 함수
    async def log_request(request: Request, call_next):
        request.state.request_id = _request_id(request)
        # 요청에 고유 id(번호표)를 붙인다. 예: "a1b2c3..."
        # request.state는 요청에 임시로 값을 붙여두는 공간
        log_event(
            REQUEST_RECEIVED, # 이벤트 이름: "요청 받음"
            request_id=request.state.request_id, # 번호표
            method=request.method, # GET, POST 등
            path=request.url.path, # /api/chat 등
        )
        # 터미널에 "요청 받음, id=..., POST /api/chat" 같은 로그를 남긴다.

        return await call_next(request)
    #endregion
    
    
    # 마지막에 등록해 기존 HTTP/세션 미들웨어 바깥에서 관찰한다.
    # Starlette의 최외곽 ServerErrorMiddleware가 생성하는 500 응답은 관찰 범위 밖이다.
    if settings.app_env == "development":
        app.add_middleware(ASGILoggingMiddleware)

    # 기능별 라우터에 정의한 경로들을 앱에 연결한다.
    app.include_router(auth.router)
    app.include_router(chat.router)
    app.include_router(history.router)

    # region 2. 예외 처리기 등록
    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # plan.md가 정한 공통 오류 응답 포맷: {"error": {code, message, request_id}}.
        # FastAPI 기본 핸들러는 {"detail": [...]} 형태라 API 계약과 안 맞아서 덮어쓴다.
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": _extract_validation_message(exc),
                    "request_id": _request_id(request),
                }
            },
        )
    # endregion
    
    # region 3. 기타 예외 처리
    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # 여기까지 오는 건 access_control의 401/403이나 pydantic 검증처럼 "예상된"
        # 오류가 아니라, 미리 분류해두지 못한 버그·장애다. 클라이언트에는 내부
        # 정보를 숨긴 일반 메시지만 주고, 스택 트레이스는 서버 로그에만 남긴다.
        request_id = _request_id(request)
        log_exception(UNHANDLED_ERROR, exc, request_id=request_id, path=request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "알 수 없는 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
                    "request_id": request_id,
                }
            },
        )
    # endregion
    
    @app.get("/", response_class=HTMLResponse)
    def index(
        request: Request,
        current_user: User | None = Depends(get_current_user),
    ):
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "app_env": settings.app_env,
                "is_authenticated": current_user is not None,
                "csrf_token": (
                    get_or_create_csrf_token(request)
                    if current_user is not None
                    else None
                ),
            },
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
