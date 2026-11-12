"""수입 관리 API (R01, AT01, T01)."""

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Income
from app.routers import MonthQuery
from app.schemas import IncomeCreate, IncomeRead, IncomeUpdate
from app.services import get_or_404
from app.services.plan_service import month_range

router = APIRouter(prefix="/incomes", tags=["수입 (R01)"])


@router.post("", response_model=IncomeRead, status_code=status.HTTP_201_CREATED)
def create_income(data: IncomeCreate, db: Session = Depends(get_db)):
    """수입을 등록한다. 금액 ≤ 0이면 422 (T01)."""
    income = Income(**data.model_dump())
    db.add(income)
    db.commit()
    db.refresh(income)
    return income


@router.get("", response_model=list[IncomeRead])
def list_incomes(month: MonthQuery = None, db: Session = Depends(get_db)):
    """수입 목록. month가 있으면 그 달(income_date 기준)만 (T11)."""
    stmt = select(Income).order_by(Income.income_date, Income.id)
    if month is not None:
        start, end = month_range(month)
        stmt = stmt.where(Income.income_date >= start, Income.income_date < end)
    return db.scalars(stmt).all()


@router.get("/{income_id}", response_model=IncomeRead)
def get_income(income_id: int, db: Session = Depends(get_db)):
    """수입 하나를 조회한다."""
    return get_or_404(db, Income, income_id, "수입")


@router.put("/{income_id}", response_model=IncomeRead)
def update_income(income_id: int, data: IncomeUpdate, db: Session = Depends(get_db)):
    """수입을 수정한다(전체 교체). 배분에 반영하려면 /plans/{month}/allocate를 다시 실행한다 (R08)."""
    income = get_or_404(db, Income, income_id, "수입")
    for field, value in data.model_dump().items():
        setattr(income, field, value)
    db.commit()
    db.refresh(income)
    return income


@router.delete("/{income_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_income(income_id: int, db: Session = Depends(get_db)):
    """수입을 삭제한다."""
    db.delete(get_or_404(db, Income, income_id, "수입"))
    db.commit()
