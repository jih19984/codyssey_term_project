from __future__ import annotations

import logging
import sys

# region 1. 앱 전용 이벤트 로거 정의
# 앱 전용 이벤트 로거. 루트 로거 설정(uvicorn 등)과 섞이지 않게 이름을 분리해서,
# 테스트에서도 caplog.set_level(..., logger="app.events")로 이 로거만 골라 볼 수 있다.
logger = logging.getLogger("app.events")
logger.setLevel(logging.INFO)

# 루트 로거에 핸들러가 없으면 INFO 레벨 기록은 어디에도 출력되지 않고 조용히
# 사라진다 (uvicorn은 자기 로거만 설정하고 root는 그대로 둔다). 그래서 이
# 로거에는 핸들러를 직접 붙여, 루트/uvicorn 설정과 무관하게 항상 출력되게 한다.
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    logger.addHandler(_handler)
    # propagate는 기본값(True)을 그대로 둔다 — pytest의 caplog는 root 로거에
    # 붙은 핸들러로 레코드를 모으기 때문에, 전파를 끊으면 caplog가 못 잡는다.
# endregion

# region 2. 과제가 요구하는 이벤트명. 로그를 검색/필터링할 때 이 이름으로 찾는다.
REQUEST_RECEIVED = "request_received"
AI_CALL_START = "ai_call_start"
AI_CALL_SUCCESS = "ai_call_success"
AI_CALL_FAILURE = "ai_call_failure"
DB_SAVE_SUCCESS = "db_save_success"
DB_SAVE_FAILURE = "db_save_failure"
UNHANDLED_ERROR = "unhandled_error"
# endregion


def log_event(event: str, **fields: object) -> None:
    """검색 가능한 필드(request_id, user_id, 경로, 처리 시간 등)만 남긴다.

    호출하는 쪽에서 비밀번호, 세션 값, API 키, 질문·답변 원문을 fields로
    절대 넘기지 않아야 한다 — 이 함수는 받은 값을 그대로 찍을 뿐, 어떤 내용을
    걸러내지 않는다.
    """
    rendered = " ".join(f"{key}={value}" for key, value in fields.items())
    logger.info("%s %s", event, rendered)

def log_exception(event: str, exc: BaseException, **fields: object) -> None:
    """스택 트레이스가 필요한 실패(알 수 없는 오류)에 사용한다."""
    rendered = " ".join(f"{key}={value}" for key, value in fields.items())
    logger.error("%s %s", event, rendered, exc_info=exc)
