"""월별 대시보드 서비스 (R12, T11)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Goal
from app.schemas import DashboardRead, GoalProgressRead
from app.services import expense_service, plan_service


def achievement_rate(secured: int, target: int) -> float:
    """목표 달성률 = C ÷ T × 100, 소수 1자리 반올림 (5.2). 계산은 정수로 하고 마지막에만 나눈다."""
    tenths = (secured * 1000 + target // 2) // target
    return tenths / 10


def get_dashboard(db: Session, month: str) -> DashboardRead:
    """선택한 월의 수입·배분·잔액·배분 상태·목표 달성률 (R12). 다른 월 데이터는 섞지 않는다 (T11)."""
    goals = []
    for g in db.scalars(select(Goal).order_by(Goal.priority, Goal.target_month, Goal.id)):
        c = g.current_amount  # 확보액 C = 사용자가 입력한 현재 확보액 (5.1, C11, C16)
        goals.append(
            GoalProgressRead(
                goal_id=g.id,
                goal_name=g.goal_name,
                target_amount=g.target_amount,
                secured_amount=c,
                achievement_rate=achievement_rate(c, g.target_amount),
            )
        )
    return DashboardRead(
        month=month,
        total_income=plan_service.total_income(db, month),
        plan=plan_service.find_plan(db, month),
        balances=expense_service.balances(db, month),
        goals=goals,
    )
