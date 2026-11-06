# region 0. import statements
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.access_control import (
    get_or_create_csrf_token,
    require_form_csrf,
    require_page_user,
)
from app.db import get_db
from app.models import User
from app.services.auth_service import (
    AuthService,
    InvalidCredentialFormatError,
    InvalidCredentialsError,
    UsernameAlreadyExistsError,
)
from app.templating import templates
# endregion

# APIRouter = 경로들의 묶음. main.py에서 include_router()로 앱에 연결한다.
# prefix="/auth"를 주면 아래 "/signup"은 실제로 "/auth/signup"이 된다.
router = APIRouter(prefix="/auth", tags=["auth"])

INVALID_CREDENTIALS_MESSAGE = "아이디 또는 비밀번호가 올바르지 않습니다."


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "error": None,
            "username": "",
            "csrf_token": get_or_create_csrf_token(request),
        },
    )


@router.post("/login", response_class=HTMLResponse)
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    _csrf: None = Depends(require_form_csrf),
    db: Session = Depends(get_db),
):
    service = AuthService(db)
    try:
        user = service.authenticate(username, password)
    except InvalidCredentialFormatError as exc:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "error": str(exc),
                "username": exc.username,
                "csrf_token": get_or_create_csrf_token(request),
            },
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    except InvalidCredentialsError as exc:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "error": INVALID_CREDENTIALS_MESSAGE,
                "username": exc.username,
                "csrf_token": get_or_create_csrf_token(request),
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    request.session.clear()
    request.session["user_id"] = user.id
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/logout")
def logout(
    request: Request,
    _current_user: User = Depends(require_page_user),
    _csrf: None = Depends(require_form_csrf),
):
    request.session.clear()
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(
        "session",
        path="/",
        secure=request.app.state.settings.is_production,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/signup", response_class=HTMLResponse)
def signup_form(request: Request):
    # GET: 빈 회원가입 폼 화면만 보여준다.
    return templates.TemplateResponse(
        request=request,
        name="signup.html",
        context={
            "error": None,
            "csrf_token": get_or_create_csrf_token(request),
        },
    )


@router.post("/signup", response_class=HTMLResponse)
def signup(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),  # Form(...)의 ...은 필수값이라는 뜻
    _csrf: None = Depends(require_form_csrf),
    db: Session = Depends(get_db),  # get_db가 세션을 자동으로 넣어준다.
):
    service = AuthService(db)
    try:
        service.register(username, password)
    except InvalidCredentialFormatError as exc:
        return templates.TemplateResponse(
            request=request,
            name="signup.html",
            context={
                "error": str(exc),
                "csrf_token": get_or_create_csrf_token(request),
            },
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    except UsernameAlreadyExistsError:
        return templates.TemplateResponse(
            request=request,
            name="signup.html",
            context={
                "error": "이미 사용 중인 아이디입니다.",
                "csrf_token": get_or_create_csrf_token(request),
            },
            status_code=status.HTTP_409_CONFLICT,
        )

    # 303 See Other: POST 처리 결과를 GET으로 다시 보여주라는 뜻.
    # 새로고침해도 폼이 중복 제출되지 않는다.
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
