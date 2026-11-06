# region 0. import statements
# 타입 힌트를 문자열로 지연평가하게 도와줌
from __future__ import annotations

from collections.abc import Generator

# 파이썬 ORM 라이브러리인 SQLAlchemy를 사용하기 위한 모듈 임포트
from fastapi import Request
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
# endregion

# DeclarativeBase를 그대로 상속만 받아 Base 클래스 정의
class Base(DeclarativeBase):
    pass

# 데이터베이스 엔진을 생성하는 함수 정의
def create_database_engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True)

# 세션 팩토리를 생성
def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)

# 요청마다 세션을 하나 열어서 빌려주고, 요청이 끝나면 세션을 닫음
def get_db(request: Request) -> Generator[Session, None, None]:

    with request.app.state.session_factory() as session:
        yield session