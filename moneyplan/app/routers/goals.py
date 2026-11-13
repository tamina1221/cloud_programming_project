"""목표 관리 API (R02)."""

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Goal
from app.schemas import GoalCreate, GoalRead, GoalUpdate
from app.services import get_or_404, plan_service

router = APIRouter(prefix="/goals", tags=["목표 (R02)"])


@router.post("", response_model=GoalRead, status_code=status.HTTP_201_CREATED)
def create_goal(data: GoalCreate, db: Session = Depends(get_db)):
    """목표를 등록한다."""
    goal = Goal(**data.model_dump())
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


@router.get("", response_model=list[GoalRead])
def list_goals(db: Session = Depends(get_db)):
    """목표 목록 (우선순위 → 목표 월 → 등록 순, N04)."""
    stmt = select(Goal).order_by(Goal.priority, Goal.target_month, Goal.id)
    return db.scalars(stmt).all()


@router.put("/{goal_id}", response_model=GoalRead)
def update_goal(goal_id: int, data: GoalUpdate, db: Session = Depends(get_db)):
    """목표를 수정한다(전체 교체). 배분에 반영하려면 재배분을 실행한다 (5.5)."""
    goal = get_or_404(db, Goal, goal_id, "목표")
    for field, value in data.model_dump().items():
        setattr(goal, field, value)
    db.commit()
    db.refresh(goal)
    return goal


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_goal(goal_id: int, db: Session = Depends(get_db)):
    """목표를 삭제하고 계획을 재판정한다. 소비 기록이 있으면 409 (R02, C19, T15, T16)."""
    plan_service.delete_goal(db, goal_id)
