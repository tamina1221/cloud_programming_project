"""목표 확보 API: 확보 등록·내역 조회·삭제 (R02, C31, T20)."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.routers import MonthQuery
from app.schemas import DepositCreate, DepositRead, DepositResult
from app.services import deposit_service

router = APIRouter(prefix="/goal-deposits", tags=["목표 확보 (R02)"])


@router.post("", response_model=DepositResult, status_code=status.HTTP_201_CREATED)
def create_deposit(data: DepositCreate, db: Session = Depends(get_db)):
    """확보 등록: 모은 금액을 목표의 현재 확보액에 더한다. 배분에 반영하려면 재배분한다 (5.5)."""
    return deposit_service.create_deposit(db, data)


@router.get("", response_model=list[DepositRead])
def list_deposits(month: MonthQuery = None, db: Session = Depends(get_db)):
    """확보 내역. month가 있으면 그 달만."""
    return deposit_service.list_deposits(db, month)


@router.delete("/{deposit_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_deposit(deposit_id: int, db: Session = Depends(get_db)):
    """확보 기록을 지우고 현재 확보액에서 뺀다."""
    deposit_service.delete_deposit(db, deposit_id)
