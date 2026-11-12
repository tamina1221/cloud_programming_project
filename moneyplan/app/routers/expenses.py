"""소비 관리 API (R10, R11, T02)."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.routers import MonthQuery
from app.schemas import ExpenseCreate, ExpenseRead, ExpenseUpdate, ExpenseWithBalance
from app.services import expense_service

router = APIRouter(prefix="/expenses", tags=["소비 (R10, R11)"])


@router.post("", response_model=ExpenseWithBalance, status_code=status.HTTP_201_CREATED)
def create_expense(data: ExpenseCreate, db: Session = Depends(get_db)):
    """소비를 등록하고 해당 목적의 잔액·초과 여부를 함께 돌려준다 (6.2, AT09, AT10). 0원이면 422 (T02)."""
    return expense_service.create_expense(db, data)


@router.get("", response_model=list[ExpenseRead])
def list_expenses(month: MonthQuery = None, db: Session = Depends(get_db)):
    """소비 목록. month가 있으면 그 달만 (T11)."""
    return expense_service.list_expenses(db, month)


@router.put("/{expense_id}", response_model=ExpenseWithBalance)
def update_expense(expense_id: int, data: ExpenseUpdate, db: Session = Depends(get_db)):
    """소비를 수정한다(전체 교체)."""
    return expense_service.update_expense(db, expense_id, data)


@router.delete("/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expense(expense_id: int, db: Session = Depends(get_db)):
    """소비를 삭제한다."""
    expense_service.delete_expense(db, expense_id)
