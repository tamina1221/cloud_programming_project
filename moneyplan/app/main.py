"""FastAPI 앱 생성, 시작 시 테이블 생성, 라우터 등록, 오류 응답 형식 통일 (N05)."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import models  # noqa: F401  create_all이 모든 테이블을 알도록 import
from app.database import Base
from app.database import engine as db_engine
from app.routers import dashboard, deposits, expenses, fixed_expenses, goals, incomes, plans, settings
from app.services import ServiceError


@asynccontextmanager
async def lifespan(_: FastAPI):
    """앱 시작 시 테이블을 만든다 (Alembic 미사용)."""
    Base.metadata.create_all(bind=db_engine)
    yield


app = FastAPI(
    title="MoneyPlan",
    description="목표 기반 월별 자금 배분 서비스: 수입이 들어오거나 바뀌었을 때 이번 달 어디에 얼마를 넣어야 하는지 계산한다.",
    lifespan=lifespan,
)


@app.exception_handler(ServiceError)
async def service_error_handler(_: Request, exc: ServiceError) -> JSONResponse:
    """서비스 오류 → {"detail": 메시지, ...추가 필드} (예: AT08의 excess)."""
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, **exc.extra})


def _korean_message(err: dict) -> str:
    """Pydantic 검증 오류를 원인을 알 수 있는 한국어 메시지로 바꾼다 (N05, 5.6)."""
    kind, ctx = err.get("type", ""), err.get("ctx") or {}
    messages = {
        "missing": "필수 항목입니다.",
        "greater_than": f"{ctx.get('gt')}보다 커야 합니다.",
        "greater_than_equal": f"{ctx.get('ge')} 이상이어야 합니다.",
        "int_type": "정수(원 단위)여야 합니다.",
        "int_parsing": "정수(원 단위)여야 합니다.",
        "int_from_float": "소수가 아닌 정수(원 단위)여야 합니다.",
        "string_pattern_mismatch": "YYYY-MM 형식이어야 합니다. (예: 2026-11)",
        "literal_error": f"허용된 값이 아닙니다. 가능한 값: {ctx.get('expected')}",
        "date_from_datetime_parsing": "YYYY-MM-DD 형식의 날짜여야 합니다.",
        "date_parsing": "YYYY-MM-DD 형식의 날짜여야 합니다.",
        "date_type": "YYYY-MM-DD 형식의 날짜여야 합니다.",
        "string_too_short": "비어 있으면 안 됩니다.",
        "string_too_long": f"{ctx.get('max_length')}자 이하여야 합니다.",
        "too_short": f"최소 {ctx.get('min_length')}개 이상이어야 합니다.",
        "json_invalid": "JSON 형식이 올바르지 않습니다.",
    }
    if kind == "value_error":  # model_validator에서 쓴 한국어 메시지
        return str(err.get("msg", "")).removeprefix("Value error, ")
    return messages.get(kind, err.get("msg", "입력값이 올바르지 않습니다."))


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    """입력 오류는 422로, 위치(loc)와 한국어 메시지를 돌려준다 (T01, T02)."""
    detail = [
        {"loc": err.get("loc"), "msg": _korean_message(err), "type": err.get("type"), "input": err.get("input")}
        for err in exc.errors()
    ]
    return JSONResponse(status_code=422, content=jsonable_encoder({"detail": detail}))


@app.middleware("http")
async def revalidate_frontend(request: Request, call_next):
    """화면 파일은 매번 서버에 새 버전이 있는지 확인하게 한다. 코드를 고친 뒤 브라우저가 예전 app.js를 쓰지 않도록."""
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.endswith((".html", ".js", ".css")):
        response.headers["Cache-Control"] = "no-cache"
    return response


for module in (incomes, goals, deposits, fixed_expenses, settings, plans, expenses, dashboard):
    app.include_router(module.router)


@app.get("/health", tags=["상태"])
def health() -> dict[str, str]:
    """서버 상태 확인."""
    return {"status": "ok"}


# 브라우저 화면 (N07, C21). "/"에 마운트하므로 모든 API 경로를 등록한 뒤 맨 마지막에 둔다.
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
