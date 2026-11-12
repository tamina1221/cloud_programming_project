"""배분 계획 API: 자동 배분·재배분, 조회, 수동 수정, 확정 (R05~R09)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.routers import MonthPath
from app.schemas import AllocateResponse, AllocationUpdate, PlanRead
from app.services import plan_service

router = APIRouter(prefix="/plans", tags=["배분 계획 (R05~R09)"])


@router.post("/{month}/allocate", response_model=AllocateResponse)
def allocate(
    month: MonthPath,
    mode: Annotated[
        plan_service.Mode, Query(description="reallocate: 다시 계산 / keep: 기존 배분 유지")
    ] = "reallocate",
    db: Session = Depends(get_db),
):
    """자동 배분·재배분을 실행한다 (R06~R08, AT03~AT07). 수입 감소 후 keep이면 409 (T09)."""
    return plan_service.allocate(db, month, mode)


@router.get("/{month}", response_model=PlanRead)
def get_plan(month: MonthPath, db: Session = Depends(get_db)):
    """해당 월 배분 계획을 조회한다."""
    return plan_service.get_plan(db, month)


@router.put("/{month}/allocations", response_model=PlanRead)
def update_allocations(month: MonthPath, data: AllocationUpdate, db: Session = Depends(get_db)):
    """배분 금액을 수동 수정한다. 총배분액 > 총수입이면 400과 초과액 (R09, AT08)."""
    return plan_service.update_allocations(db, month, data.items)


@router.post("/{month}/confirm", response_model=PlanRead)
def confirm(month: MonthPath, db: Session = Depends(get_db)):
    """배분 계획을 확정한다. 배분 불가 상태면 400 (R08)."""
    return plan_service.confirm(db, month)
