"""서비스 계층 공통: FastAPI에 의존하지 않는 서비스 오류와 조회 도우미.

서비스는 ServiceError를 던지고, main.py의 예외 처리기가 HTTP 응답으로 바꾼다 (N05).
"""

from typing import Any, TypeVar

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
