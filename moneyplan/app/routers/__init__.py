"""라우터 공통: 경로·쿼리의 월 파라미터 형식 검증 ("YYYY-MM", 틀리면 422)."""

from typing import Annotated

from fastapi import Path, Query

from app.schemas import MONTH_PATTERN

MonthPath = Annotated[str, Path(pattern=MONTH_PATTERN, description="YYYY-MM", examples=["2026-11"])]
MonthQuery = Annotated[
    str | None, Query(pattern=MONTH_PATTERN, description="YYYY-MM (생략하면 전체)")
]
