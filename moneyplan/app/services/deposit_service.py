"""목표 확보 서비스: 확보 기록 저장·삭제와 현재 확보액 갱신 (R02, C31).

확보 기록과 목표의 현재 확보액을 한 번에 바꿔야 하므로 서비스에서 처리한다.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Goal, GoalDeposit
from app.schemas import DepositCreate, DepositRead, DepositResult, GoalRead
from app.services import ConflictError, get_or_404, month_range


def create_deposit(db: Session, data: DepositCreate) -> DepositResult:
    """확보 기록을 저장하고 목표의 현재 확보액에 더한다 (T20)."""
    goal = get_or_404(db, Goal, data.goal_id, "목표")
    deposit = GoalDeposit(**data.model_dump())
    goal.current_amount += data.amount
    db.add(deposit)
    db.commit()
    db.refresh(deposit)
    db.refresh(goal)
    return DepositResult(deposit=DepositRead.model_validate(deposit), goal=GoalRead.model_validate(goal))


def list_deposits(db: Session, month: str | None) -> list[GoalDeposit]:
    """확보 기록 목록. month가 있으면 그 달(deposit_date 기준)만."""
    stmt = select(GoalDeposit).order_by(GoalDeposit.deposit_date, GoalDeposit.id)
    if month is not None:
        start, end = month_range(month)
        stmt = stmt.where(GoalDeposit.deposit_date >= start, GoalDeposit.deposit_date < end)
    return list(db.scalars(stmt))


def delete_deposit(db: Session, deposit_id: int) -> None:
    """확보 기록을 지우고 목표의 현재 확보액에서 뺀다.

    목표 수정으로 현재 확보액을 이미 줄여서 빼면 음수가 되는 경우는 409.
    """
    deposit = get_or_404(db, GoalDeposit, deposit_id, "확보 기록")
    goal = db.get(Goal, deposit.goal_id)
    if goal.current_amount < deposit.amount:
        raise ConflictError(
            f"'{goal.goal_name}'의 현재 확보액({goal.current_amount:,}원)이 이 기록({deposit.amount:,}원)보다 "
            "적어 삭제할 수 없습니다. 목표의 현재 확보액을 먼저 확인하세요."
        )
    goal.current_amount -= deposit.amount
    db.delete(deposit)
    db.commit()
