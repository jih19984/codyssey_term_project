from __future__ import annotations

import re
import string

# 아이디 정책: 영문 대소문자/숫자/밑줄/하이픈만 허용, 3~20자.
# - 공백·한글·이모지 등 다른 유니코드 문자는 허용하지 않는다 (ASCII로 제한).
# - 대소문자를 구분한다 (예: "Whale01"과 "whale01"은 다른 아이디다).
# - HTML(login.html, signup.html)의 minlength/maxlength/pattern, DB 컬럼(String(20))과
#   길이를 반드시 동일하게 맞춘다 — 셋 중 하나만 바꾸면 다시 불일치가 생긴다.
USERNAME_MIN_LENGTH = 3
USERNAME_MAX_LENGTH = 20
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")

# 비밀번호 정책: 8~100자이고, 영문 대문자·영문 소문자·특수문자를 각각 1개 이상 포함한다.
# - 특수문자는 ASCII 특수기호(!"#$%&'()*+,-./:;<=>?@[\]^_`{|}~)만 인정한다.
# - 위 조건만 채우면 나머지 문자(숫자·공백·한글·이모지 등)는 자유롭게 섞어 쓸 수 있다.
# - 조합 규칙은 회원가입에서만 검사한다. 로그인은 길이만 검사해서, 정책이 바뀌기 전에
#   가입한 사용자도 기존 비밀번호로 계속 로그인할 수 있게 한다.
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 100
PASSWORD_UPPERCASE_PATTERN = re.compile(r"[A-Z]")
PASSWORD_LOWERCASE_PATTERN = re.compile(r"[a-z]")
PASSWORD_SPECIAL_PATTERN = re.compile(f"[{re.escape(string.punctuation)}]")

USERNAME_POLICY_MESSAGE = (
    f"아이디는 영문, 숫자, '_', '-'만 사용해 "
    f"{USERNAME_MIN_LENGTH}~{USERNAME_MAX_LENGTH}자로 입력해주세요."
)
PASSWORD_POLICY_MESSAGE = (
    f"비밀번호는 {PASSWORD_MIN_LENGTH}~{PASSWORD_MAX_LENGTH}자이며, "
    f"영문 대문자, 영문 소문자, 특수문자를 각각 1개 이상 포함해야 합니다."
)


def is_valid_username(username: str) -> bool:
    return (
        USERNAME_MIN_LENGTH <= len(username) <= USERNAME_MAX_LENGTH
        and USERNAME_PATTERN.fullmatch(username) is not None
    )


def is_valid_password(password: str) -> bool:
    # 길이만 검사한다 (로그인·회원가입 공통). 비밀번호는 여기서도, 호출하는 쪽
    # (services/auth_service.py)에서도 strip()이나 다른 가공을 하지 않고
    # 원문 그대로 hash_password에 넘긴다.
    return PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH


def is_strong_password(password: str) -> bool:
    # 회원가입 전용: 길이 + 문자 조합(대문자·소문자·특수문자 각 1개 이상)을 검사한다.
    return (
        is_valid_password(password)
        and PASSWORD_UPPERCASE_PATTERN.search(password) is not None
        and PASSWORD_LOWERCASE_PATTERN.search(password) is not None
        and PASSWORD_SPECIAL_PATTERN.search(password) is not None
    )
