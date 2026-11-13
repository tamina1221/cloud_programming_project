"""목표 관리 API (R02)."""

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Goal
from app.schemas import GoalCreate, GoalRead, GoalSecure, GoalUpdate
from app.services import create_row, get_or_404, plan_service, update_row

router = APIRouter(prefix="/goals", tags=["목표 (R02)"])


@router.post("", response_model=GoalRead, status_code=status.HTTP_201_CREATED)
def create_goal(data: GoalCreate, db: Session = Depends(get_db)):
    """목표를 등록한다."""
    return create_row(db, Goal, data)


@router.get("", response_model=list[GoalRead])
def list_goals(db: Session = Depends(get_db)):
    """목표 목록 (우선순위 → 목표 월 → 등록 순, N04)."""
    stmt = select(Goal).order_by(Goal.priority, Goal.target_month, Goal.id)
    return db.scalars(stmt).all()


@router.put("/{goal_id}", response_model=GoalRead)
def update_goal(goal_id: int, data: GoalUpdate, db: Session = Depends(get_db)):
    """목표를 수정한다(전체 교체). 배분에 반영하려면 재배분을 실행한다 (5.5)."""
    return update_row(db, get_or_404(db, Goal, goal_id, "목표"), data)


@router.post("/{goal_id}/secure", response_model=GoalRead)
def secure_goal(goal_id: int, data: GoalSecure, db: Session = Depends(get_db)):
    """목표 확보 등록: 실제로 모은 금액을 현재 확보액에 더한다 (C31, T20).

    목표 수정으로 현재 확보액을 바꾸는 것과 같다. 배분에 반영하려면 재배분을 실행한다 (5.5).
    """
    goal = get_or_404(db, Goal, goal_id, "목표")
    goal.current_amount += data.amount
    db.commit()
    db.refresh(goal)
    return goal


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_goal(goal_id: int, db: Session = Depends(get_db)):
    """목표를 삭제하고 계획을 재판정한다. 소비 기록이 있으면 409 (R02, C19, T15, T16)."""
    plan_service.delete_goal(db, goal_id)
