"""배분 계획 서비스: 엔진 입력 수집, 자동 배분·재배분, 수동 수정, 목표 삭제 (R02, R05~R09, 개발문서 6.2)."""

from typing import Literal

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.engine import (
    EngineInput,
    EngineResult,
    GoalInput,
    GoalResult,
    evaluate,
    keep_existing,
    months_between,
)
from app.engine import allocate as engine_allocate
from app.models import Allocation, AllocationPlan, Expense, FixedExpense, Goal, Income, MonthlySetting
from app.schemas import (
    AllocateResponse,
    AllocationItem,
    AllocationRead,
    GoalResultRead,
    PlanRead,
)
from app.services import BadRequestError, ConflictError, NotFoundError, get_or_404, month_range

Mode = Literal["reallocate", "keep"]


# ---------- 공통 조회 ----------

def _goal_input(g: Goal) -> GoalInput:
    """Goal 행을 엔진 입력으로 바꾼다. 확보액 C = 현재 확보액 (5.1, C16)."""
    return GoalInput(
        goal_id=g.id,
        name=g.goal_name,
        target_amount=g.target_amount,
        secured_amount=g.current_amount,
        target_month=g.target_month,
        priority=g.priority,
        created_order=g.id,  # 등록 순 (N04)
    )


def total_income(db: Session, month: str) -> int:
    """해당 월(income_date 기준) 수입 합계 I (5.1, AT01)."""
    start, end = month_range(month)
    stmt = select(func.coalesce(func.sum(Income.amount), 0)).where(
        Income.income_date >= start, Income.income_date < end
    )
    return int(db.scalar(stmt))


def build_engine_input(db: Session, month: str) -> EngineInput:
    """DB에서 해당 월의 엔진 입력(I, F, L, 목표 목록)을 모은다 (5.1, 6.2)."""
    setting = db.get(MonthlySetting, month)
    if setting is None:
        raise NotFoundError(f"{month}의 최소 생활비를 먼저 설정하세요. (PUT /settings/{month})")

    fixed_total = db.scalar(
        select(func.coalesce(func.sum(FixedExpense.amount), 0)).where(FixedExpense.month == month)
    )
    goals = db.scalars(select(Goal).order_by(Goal.id)).all()
    return EngineInput(
        month=month,
        total_income=total_income(db, month),
        fixed_total=int(fixed_total),
        min_living=setting.min_living,
        goals=[_goal_input(g) for g in goals],
    )


def _plan_engine_input(db: Session, plan: AllocationPlan) -> EngineInput:
    """저장된 계획 기준 엔진 입력 (수동 수정·목표 삭제용, 5.6).

    I는 계획의 총수입, F·L은 고정·생활비 행의 필요 금액. 목표는 이 계획에 행이 있는 것만
    현재 Goal 값으로 넣는다. 계획 이후 등록한 목표는 재배분해야 반영된다 (8.4 U03).
    """
    rows = {a.category: a for a in plan.allocations if a.category != "goal"}
    return EngineInput(
        month=plan.month,
        total_income=plan.total_income,
        fixed_total=rows["fixed"].required_amount,
        min_living=rows["living"].required_amount,
        goals=[_goal_input(a.goal) for a in plan.allocations if a.category == "goal"],
    )


def _get_plan(db: Session, month: str) -> AllocationPlan | None:
    """해당 월 계획(월당 1개)을 조회한다."""
    return db.scalar(select(AllocationPlan).where(AllocationPlan.month == month))


def _require_plan(db: Session, month: str) -> AllocationPlan:
    """해당 월 계획이 없으면 404."""
    plan = _get_plan(db, month)
    if plan is None:
        raise NotFoundError(
            f"{month} 배분 계획이 없습니다. 먼저 POST /plans/{month}/allocate로 자동 배분을 실행하세요."
        )
    return plan


# ---------- 변환 ----------

def to_plan_read(db: Session, plan: AllocationPlan) -> PlanRead:
    """저장된 계획을 응답 형식으로 바꾼다.

    n·S는 저장하지 않으므로 목표 월과 확보액으로 다시 계산한다. lacking = max(R − a, 0).
    """
    fixed_alloc = living_alloc = 0
    goal_results: list[GoalResultRead] = []
    for a in plan.allocations:
        if a.category == "fixed":
            fixed_alloc += a.allocated_amount
        elif a.category == "living":
            living_alloc += a.allocated_amount
        else:
            g = a.goal
            goal_results.append(
                GoalResultRead(
                    goal_id=g.id,
                    name=g.goal_name,
                    status=a.goal_status,
                    remaining_months=months_between(plan.month, g.target_month),
                    shortfall_total=g.target_amount - g.current_amount,
                    required=a.required_amount,
                    allocated=a.allocated_amount,
                    lacking=max(a.required_amount - a.allocated_amount, 0),
                    next_required=a.next_required,
                )
            )
    return PlanRead(
        month=plan.month,
        status=plan.status,
        total_income=plan.total_income,
        fixed_allocated=fixed_alloc,
        living_allocated=living_alloc,
        goals=goal_results,
        total_allocated=plan.total_allocated,
        unallocated=plan.unallocated,
        shortage=plan.shortage,
        shortage_target=plan.shortage_target,
        allocations=[AllocationRead.model_validate(a) for a in plan.allocations],
    )


def _to_engine_result(plan: PlanRead) -> EngineResult:
    """저장된 계획을 엔진 EngineResult로 복원한다 ('기존 유지'용, R08)."""
    return EngineResult(
        status=plan.status,
        total_income=plan.total_income,
        fixed_allocated=plan.fixed_allocated,
        living_allocated=plan.living_allocated,
        goals=[GoalResult(**g.model_dump()) for g in plan.goals],
        total_allocated=plan.total_allocated,
        unallocated=plan.unallocated,
        shortage=plan.shortage,
        shortage_target=plan.shortage_target,
    )


def _allocation_rows(inp: EngineInput, result: EngineResult) -> list[Allocation]:
    """엔진 결과를 Allocation 행으로 만든다. 목표는 엔진 정렬 순서대로 (N04)."""
    rows = [
        Allocation(category="fixed", required_amount=inp.fixed_total,
                   allocated_amount=result.fixed_allocated, is_manual=False),
        Allocation(category="living", required_amount=inp.min_living,
                   allocated_amount=result.living_allocated, is_manual=False),
    ]
    for g in result.goals:
        rows.append(
            Allocation(
                category="goal",
                goal_id=g.goal_id,
                required_amount=g.required,
                allocated_amount=g.allocated,
                is_manual=False,
                goal_status=g.status,
                next_required=g.next_required,
            )
        )
    return rows


# ---------- 배분·재배분 (R06~R08) ----------

def allocate(db: Session, month: str, mode: Mode = "reallocate") -> AllocateResponse:
    """자동 배분·재배분을 실행하고 기존 계획과 새 계획을 함께 돌려준다 (5.5).

    - reallocate: 엔진을 다시 실행해 배분을 새로 저장한다. 수동 수정은 초기화된다 (AT04, AT06).
    - keep: 기존 배분은 그대로, 수입 증가분을 미배분 금액에 더한다 (AT07).
      수입이 줄었거나(T09) 기존 계획이 배분 불가면(T12, C17) 409.
    """
    plan = _get_plan(db, month)
    previous = to_plan_read(db, plan) if plan is not None else None

    if mode == "keep":
        if plan is None:
            raise NotFoundError(
                f"{month}에 유지할 기존 배분 계획이 없습니다. mode=reallocate로 자동 배분을 먼저 실행하세요."
            )
        try:
            kept = keep_existing(_to_engine_result(previous), total_income(db, month))
        except ValueError as e:
            raise ConflictError(str(e)) from e
        plan.total_income = kept.total_income
        plan.unallocated = kept.unallocated
    else:
        inp = build_engine_input(db, month)
        result = engine_allocate(inp)
        if plan is None:
            plan = AllocationPlan(month=month)
            db.add(plan)
        else:
            plan.allocations.clear()  # 기존 배분 삭제 (수동 수정 초기화, 5.5)
            db.flush()
        plan.total_income = result.total_income
        plan.total_allocated = result.total_allocated
        plan.unallocated = result.unallocated
        plan.status = result.status
        plan.shortage = result.shortage
        plan.shortage_target = result.shortage_target
        plan.allocations.extend(_allocation_rows(inp, result))

    db.commit()
    db.refresh(plan)
    return AllocateResponse(previous=previous, current=to_plan_read(db, plan))


def get_plan(db: Session, month: str) -> PlanRead:
    """해당 월 계획을 조회한다."""
    return to_plan_read(db, _require_plan(db, month))


def find_plan(db: Session, month: str) -> PlanRead | None:
    """해당 월 계획을 조회하고, 없으면 None (대시보드용)."""
    plan = _get_plan(db, month)
    return to_plan_read(db, plan) if plan is not None else None


# ---------- 수동 수정 (R09) ----------

def _evaluate_plan(db: Session, plan: AllocationPlan, amounts: dict[int, int]) -> EngineResult:
    """배분 항목 id → 금액(없으면 저장된 금액)으로 엔진 evaluate를 호출한다 (5.6)."""
    fixed = living = 0
    goal_allocated: dict[int, int] = {}
    for a in plan.allocations:
        amount = amounts.get(a.id, a.allocated_amount)
        if a.category == "fixed":
            fixed = amount
        elif a.category == "living":
            living = amount
        else:
            goal_allocated[a.goal_id] = amount
    try:
        return evaluate(_plan_engine_input(db, plan), fixed, living, goal_allocated)
    except ValueError as e:  # T14: 고정·생활비 감액 등
        raise BadRequestError(str(e)) from e


def _apply_result(plan: AllocationPlan, result: EngineResult, manual_ids: set[int]) -> None:
    """재판정 결과를 계획과 배분 행에 반영한다. manual_ids의 행은 수동 수정으로 표시 (R09)."""
    by_goal = {g.goal_id: g for g in result.goals}
    for a in plan.allocations:
        if a.category == "fixed":
            a.allocated_amount = result.fixed_allocated
        elif a.category == "living":
            a.allocated_amount = result.living_allocated
        else:
            g = by_goal[a.goal_id]
            a.allocated_amount = g.allocated
            a.required_amount = g.required
            a.goal_status = g.status
            a.next_required = g.next_required
        if a.id in manual_ids:
            a.is_manual = True
    plan.status = result.status
    plan.total_allocated = result.total_allocated
    plan.unallocated = result.unallocated
    plan.shortage = result.shortage
    plan.shortage_target = result.shortage_target


def update_allocations(db: Session, month: str, items: list[AllocationItem]) -> PlanRead:
    """배분 금액을 직접 고치고 상태를 다시 판정한다 (R09, 5.6, C18).

    거부: 배분 불가 계획(T17) / 없는 항목 404 / 총배분액 > 총수입(AT08, excess) /
    고정·생활비를 필요 금액보다 줄임(T14). 거부되면 DB 값은 바뀌지 않는다.
    """
    plan = _require_plan(db, month)
    if plan.status == "infeasible":
        raise BadRequestError("배분 불가 상태의 계획은 수정할 수 없습니다. 수입이나 설정을 조정한 뒤 재배분하세요.")

    by_id = {a.id: a for a in plan.allocations}
    missing = [item.allocation_id for item in items if item.allocation_id not in by_id]
    if missing:
        raise NotFoundError(f"{month} 계획에 없는 배분 항목입니다: allocation_id={missing}")

    new_amounts = {item.allocation_id: item.allocated_amount for item in items}
    new_total = sum(new_amounts.get(a.id, a.allocated_amount) for a in plan.allocations)
    if new_total > plan.total_income:
        excess = new_total - plan.total_income
        raise BadRequestError(
            f"총배분액 {new_total:,}원이 총수입 {plan.total_income:,}원보다 "
            f"{excess:,}원 많아 저장할 수 없습니다.",
            excess=excess,
        )

    result = _evaluate_plan(db, plan, new_amounts)  # 여기까지 DB는 바뀌지 않음
    changed = {i for i, v in new_amounts.items() if by_id[i].allocated_amount != v}
    _apply_result(plan, result, changed)
    db.commit()
    db.refresh(plan)
    return to_plan_read(db, plan)


# ---------- 목표 삭제 (R02) ----------

def delete_goal(db: Session, goal_id: int) -> None:
    """목표와 그 배분 항목을 지우고, 영향을 받은 계획을 다시 판정한다 (R02, C19).

    소비 기록이 있는 목표는 지우지 않는다 → 409 (T16).
    """
    goal = get_or_404(db, Goal, goal_id, "목표")
    if db.scalar(select(exists().where(Expense.goal_id == goal_id))):
        raise ConflictError(
            f"'{goal.goal_name}' 목표로 등록된 소비 기록이 있어 삭제할 수 없습니다. 소비 기록을 먼저 삭제하세요."
        )

    rows = db.scalars(select(Allocation).where(Allocation.goal_id == goal_id)).all()
    plans = list({row.plan.id: row.plan for row in rows}.values())
    for row in rows:
        row.plan.allocations.remove(row)  # delete-orphan으로 행 삭제
    db.delete(goal)
    db.flush()

    for plan in plans:
        if plan.status == "infeasible":  # 목표 배분이 없으므로 합계만 다시 계산
            plan.total_allocated = sum(a.allocated_amount for a in plan.allocations)
            plan.unallocated = plan.total_income - plan.total_allocated
        else:  # T15: 남은 금액으로 재판정
            _apply_result(plan, _evaluate_plan(db, plan, {}), set())
    db.commit()
