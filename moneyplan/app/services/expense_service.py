"""소비 서비스: 소비 CRUD와 목적별 잔액 (R10, R11, 개발문서 6.2 소비 등록 흐름)."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AllocationPlan, Expense, Goal
from app.schemas import (
    BalanceRead,
    ExpenseCreate,
    ExpenseRead,
    ExpenseUpdate,
    ExpenseWithBalance,
)
from app.services import NotFoundError, get_or_404
from app.services.plan_service import month_range

CATEGORY_NAMES = {"fixed": "고정 지출", "living": "생활비"}
Key = tuple[str, int | None]  # (category, goal_id)


def _check_goal(db: Session, goal_id: int | None) -> None:
    """목표 소비이면 목표가 실제로 있는지 확인한다."""
    if goal_id is not None and db.get(Goal, goal_id) is None:
        raise NotFoundError(f"목표를 찾을 수 없습니다. (goal_id={goal_id})")


def list_expenses(db: Session, month: str | None) -> list[Expense]:
    """소비 목록. month가 있으면 그 달(expense_date 기준)만 (T11)."""
    stmt = select(Expense).order_by(Expense.expense_date, Expense.id)
    if month is not None:
        start, end = month_range(month)
        stmt = stmt.where(Expense.expense_date >= start, Expense.expense_date < end)
    return list(db.scalars(stmt))


def get_expense(db: Session, expense_id: int) -> Expense:
    """소비 하나를 조회한다."""
    return get_or_404(db, Expense, expense_id, "소비 기록")


def create_expense(db: Session, data: ExpenseCreate) -> ExpenseWithBalance:
    """소비를 저장하고, 해당 목적의 잔액·초과 여부를 함께 돌려준다 (6.2, AT09, AT10)."""
    _check_goal(db, data.goal_id)
    expense = Expense(**data.model_dump())
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return _with_balance(db, expense)


def update_expense(db: Session, expense_id: int, data: ExpenseUpdate) -> ExpenseWithBalance:
    """소비를 수정한다 (전체 교체)."""
    expense = get_expense(db, expense_id)
    _check_goal(db, data.goal_id)
    for field, value in data.model_dump().items():
        setattr(expense, field, value)
    db.commit()
    db.refresh(expense)
    return _with_balance(db, expense)


def delete_expense(db: Session, expense_id: int) -> None:
    """소비를 삭제한다."""
    db.delete(get_expense(db, expense_id))
    db.commit()


def _with_balance(db: Session, expense: Expense) -> ExpenseWithBalance:
    """소비와 그 목적의 잔액을 묶는다."""
    month = expense.expense_date.strftime("%Y-%m")
    key = (expense.category, expense.goal_id)
    balance = next(b for b in balances(db, month) if (b.category, b.goal_id) == key)
    return ExpenseWithBalance(expense=ExpenseRead.model_validate(expense), balance=balance)


def balances(db: Session, month: str) -> list[BalanceRead]:
    """목적별 잔액 = 해당 월 계획의 배분액 − 해당 월 소비 합계 (R11).

    음수이면 is_over=True(초과 소비). 재배분으로 배분액이 줄어도 소비 기록은 그대로 둔다 (N06, T10).
    계획이 없으면 배분액 0으로 본다.
    """
    allocated: dict[Key, int] = {("fixed", None): 0, ("living", None): 0}
    names: dict[Key, str] = {}

    plan = db.scalar(select(AllocationPlan).where(AllocationPlan.month == month))
    if plan is not None:
        for a in plan.allocations:
            key = (a.category, a.goal_id)
            allocated[key] = allocated.get(key, 0) + a.allocated_amount
            if a.goal is not None:
                names[key] = a.goal.goal_name

    start, end = month_range(month)
    spent_rows = db.execute(
        select(Expense.category, Expense.goal_id, func.sum(Expense.amount))
        .where(Expense.expense_date >= start, Expense.expense_date < end)
        .group_by(Expense.category, Expense.goal_id)
    )
    spent: dict[Key, int] = {(c, g): int(total) for c, g, total in spent_rows}

    # 계획에 없는 목표에 소비한 경우도 표시한다 (배분 0 → 초과 소비)
    keys = list(allocated) + sorted(k for k in spent if k not in allocated)
    extra_goal_ids = [g for c, g in keys if g is not None and (c, g) not in names]
    if extra_goal_ids:
        for goal in db.scalars(select(Goal).where(Goal.id.in_(extra_goal_ids))):
            names[("goal", goal.id)] = goal.goal_name

    result = []
    for key in keys:
        category, goal_id = key
        alloc, used = allocated.get(key, 0), spent.get(key, 0)
        result.append(
            BalanceRead(
                category=category,
                goal_id=goal_id,
                name=CATEGORY_NAMES.get(category) or names.get(key, f"목표 {goal_id}"),
                allocated=alloc,
                spent=used,
                balance=alloc - used,
                is_over=alloc - used < 0,
            )
        )
    return result
