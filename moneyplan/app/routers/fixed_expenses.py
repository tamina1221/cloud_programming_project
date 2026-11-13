"""고정 지출 관리 API: 등록·조회·수정·삭제 (R03)."""

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import FixedExpense
from app.routers import MonthQuery
from app.schemas import FixedExpenseCreate, FixedExpenseRead, FixedExpenseUpdate
from app.services import get_or_404

router = APIRouter(prefix="/fixed-expenses", tags=["고정 지출 (R03)"])


@router.post("", response_model=FixedExpenseRead, status_code=status.HTTP_201_CREATED)
def create_fixed_expense(data: FixedExpenseCreate, db: Session = Depends(get_db)):
    """월별 고정 지출 항목을 등록한다."""
    item = FixedExpense(**data.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("", response_model=list[FixedExpenseRead])
def list_fixed_expenses(month: MonthQuery = None, db: Session = Depends(get_db)):
    """고정 지출 목록. month가 있으면 그 달만 (T11)."""
    stmt = select(FixedExpense).order_by(FixedExpense.month, FixedExpense.id)
    if month is not None:
        stmt = stmt.where(FixedExpense.month == month)
    return db.scalars(stmt).all()


@router.put("/{fixed_expense_id}", response_model=FixedExpenseRead)
def update_fixed_expense(
    fixed_expense_id: int, data: FixedExpenseUpdate, db: Session = Depends(get_db)
):
    """고정 지출 항목을 수정한다(전체 교체). 배분에 반영하려면 재배분을 실행한다 (R03, C28, T18)."""
    item = get_or_404(db, FixedExpense, fixed_expense_id, "고정 지출")
    for field, value in data.model_dump().items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{fixed_expense_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_fixed_expense(fixed_expense_id: int, db: Session = Depends(get_db)):
    """고정 지출 항목을 삭제한다."""
    db.delete(get_or_404(db, FixedExpense, fixed_expense_id, "고정 지출"))
    db.commit()
