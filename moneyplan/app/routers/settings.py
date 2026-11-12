"""최소 생활비 설정 API (R04)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import MonthlySetting
from app.routers import MonthPath
from app.schemas import SettingRead, SettingUpdate
from app.services import NotFoundError

router = APIRouter(prefix="/settings", tags=["최소 생활비 (R04)"])


@router.put("/{month}", response_model=SettingRead)
def put_setting(month: MonthPath, data: SettingUpdate, db: Session = Depends(get_db)):
    """해당 월 최소 생활비를 설정한다. 이미 있으면 덮어쓴다."""
    setting = db.get(MonthlySetting, month)
    if setting is None:
        setting = MonthlySetting(month=month, min_living=data.min_living)
        db.add(setting)
    else:
        setting.min_living = data.min_living
    db.commit()
    db.refresh(setting)
    return setting


@router.get("/{month}", response_model=SettingRead)
def get_setting(month: MonthPath, db: Session = Depends(get_db)):
    """해당 월 최소 생활비를 조회한다."""
    setting = db.get(MonthlySetting, month)
    if setting is None:
        raise NotFoundError(f"{month}의 최소 생활비가 설정되지 않았습니다.")
    return setting
