"""DB 엔진·세션 생성, get_db 의존성 (개발문서 6.1 저장소, N03)."""

import os
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL 환경변수가 없습니다. .env.example을 복사해 .env를 만드세요. "
        "(형식: postgresql+psycopg://사용자:비밀번호@호스트:5432/DB이름)"
    )

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """모든 SQLAlchemy 모델의 기반 클래스."""


def get_db() -> Iterator[Session]:
    """요청마다 DB 세션을 열고, 끝나면 닫는 FastAPI 의존성."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
