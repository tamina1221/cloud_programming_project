"""서비스 계층 공통: FastAPI에 의존하지 않는 서비스 오류와 조회 도우미.

서비스는 ServiceError를 던지고, main.py의 예외 처리기가 HTTP 응답으로 바꾼다 (N05).
"""

from datetime import date
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import Base


class ServiceError(Exception):
    """서비스 오류. status_code·한국어 메시지·추가 응답 필드(extra)를 담는다."""

    status_code = 400

    def __init__(self, detail: str, **extra: Any) -> None:
        super().__init__(detail)
        self.detail = detail
        self.extra = extra


class BadRequestError(ServiceError):
    """잘못된 요청 (400)."""

    status_code = 400


class NotFoundError(ServiceError):
    """대상을 찾을 수 없음 (404)."""

    status_code = 404


class ConflictError(ServiceError):
    """현재 상태와 충돌 (409)."""

    status_code = 409


ModelT = TypeVar("ModelT", bound=Base)


def get_or_404(db: Session, model: type[ModelT], obj_id: Any, label: str) -> ModelT:
    """id로 조회하고 없으면 NotFoundError(404)."""
    obj = db.get(model, obj_id)
    if obj is None:
        raise NotFoundError(f"{label}을(를) 찾을 수 없습니다. (id={obj_id})")
    return obj


def create_row(db: Session, model: type[ModelT], data: BaseModel) -> ModelT:
    """요청 본문으로 행을 만들어 저장한다 (단순 등록 공통)."""
    obj = model(**data.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def update_row(db: Session, obj: ModelT, data: BaseModel) -> ModelT:
    """요청 본문의 모든 필드로 행을 바꿔 저장한다 (PUT 전체 교체 공통)."""
    for field, value in data.model_dump().items():
        setattr(obj, field, value)
    db.commit()
    db.refresh(obj)
    return obj


def delete_row(db: Session, obj: Base) -> None:
    """행을 삭제한다 (단순 삭제 공통)."""
    db.delete(obj)
    db.commit()


def month_range(month: str) -> tuple[date, date]:
    """'YYYY-MM'의 [첫날, 다음 달 첫날) 범위. 날짜 컬럼을 월로 거를 때 쓴다 (T11)."""
    year, mon = int(month[:4]), int(month[5:7])
    start = date(year, mon, 1)
    end = date(year + 1, 1, 1) if mon == 12 else date(year, mon + 1, 1)
    return start, end
