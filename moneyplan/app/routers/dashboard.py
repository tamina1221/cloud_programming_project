"""월별 대시보드 API (R11, R12, T11)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.routers import MonthPath
from app.schemas import DashboardRead
from app.services import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["대시보드 (R12)"])


@router.get("/{month}", response_model=DashboardRead)
def get_dashboard(month: MonthPath, db: Session = Depends(get_db)):
    """선택한 월의 수입·배분·소비·잔액·배분 상태·목표 달성률 (R12)."""
    return dashboard_service.get_dashboard(db, month)
