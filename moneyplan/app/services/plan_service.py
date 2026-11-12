"""배분 계획 서비스: 엔진 입력 수집, 자동 배분·재배분, 수동 수정, 확정 (R05~R09, 개발문서 6.2)."""

from datetime import date
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engine import (
    EngineInput,
    EngineResult,
    GoalInput,
    GoalResult,
    keep_existing,
    months_between,
)
from app.engine import allocate as engine_allocate
from app.models import Allocation, AllocationPlan, FixedExpense, Goal, Income, MonthlySetting
from app.schemas import (
    AllocateResponse,
    AllocationItem,
    AllocationRead,
    GoalResultRead,
    PlanRead,
)
from app.services import BadRequestError, ConflictError, NotFoundError

Mode = Literal["reallocate", "keep"]


# ---------- 공통 조회 ----------

def month_range(month: str) -> tuple[date, date]:
    """'YYYY-MM'의 [첫날, 다음 달 첫날) 범위. 날짜 컬럼을 월로 거를 때 쓴다 (T11)."""
    year, mon = int(month[:4]), int(month[5:7])
    start = date(year, mon, 1)
    end = date(year + 1, 1, 1) if mon == 12 else date(year, mon + 1, 1)
    return start, end


def total_income(db: Session, month: str) -> int:
    """해당 월(income_date 기준) 수입 합계 I (5.1, AT01)."""
    start, end = month_range(month)
    stmt = select(func.coalesce(func.sum(Income.amount), 0)).where(
        Income.income_date >= start, Income.income_date < end
    )
    return int(db.scalar(stmt))


def secured_from_confirmed(db: Session, month: str) -> dict[int, int]:
    """month보다 이전 월의 확정(confirmed) 계획에서 목표별로 배분된 금액 합계 (5.1)."""
    stmt = (
        select(Allocation.goal_id, func.sum(Allocation.allocated_amount))
        .join(AllocationPlan, Allocation.plan_id == AllocationPlan.id)
        .where(
            AllocationPlan.confirmed.is_(True),
            AllocationPlan.month < month,  # "YYYY-MM"은 문자열 비교 = 시간 순서
            Allocation.category == "goal",
        )
        .group_by(Allocation.goal_id)
    )
    return {goal_id: int(total) for goal_id, total in db.execute(stmt)}


def secured_amount(goal: Goal, confirmed: dict[int, int]) -> int:
    """확보액 C = 사용자가 입력한 현재 확보액 + 이전 달까지 확정된 배분 합계 (5.1)."""
    return goal.current_amount + confirmed.get(goal.id, 0)


def build_engine_input(db: Session, month: str) -> EngineInput:
    """DB에서 해당 월의 엔진 입력(I, F, L, 목표 목록)을 모은다 (5.1, 6.2)."""
    setting = db.get(MonthlySetting, month)
    if setting is None:
        raise NotFoundError(f"{month}의 최소 생활비를 먼저 설정하세요. (PUT /settings/{month})")

    fixed_total = db.scalar(
        select(func.coalesce(func.sum(FixedExpense.amount), 0)).where(FixedExpense.month == month)
    )
    confirmed = secured_from_confirmed(db, month)
    goals = db.scalars(select(Goal).order_by(Goal.id)).all()
    goal_inputs = [
        GoalInput(
            goal_id=g.id,
            name=g.goal_name,
            target_amount=g.target_amount,
            secured_amount=secured_amount(g, confirmed),
            target_month=g.target_month,
            priority=g.priority,
            created_order=g.id,  # 등록 순 (N04)
        )
        for g in goals
    ]
    return EngineInput(
        month=month,
        total_income=total_income(db, month),
        fixed_total=int(fixed_total),
        min_living=setting.min_living,
        goals=goal_inputs,
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
    confirmed = secured_from_confirmed(db, plan.month)
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
                    shortfall_total=g.target_amount - secured_amount(g, confirmed),
                    required=a.required_amount,
                    allocated=a.allocated_amount,
                    lacking=max(a.required_amount - a.allocated_amount, 0),
                    next_required=a.next_required,
                )
            )
    return PlanRead(
        month=plan.month,
        confirmed=plan.confirmed,
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

    - reallocate: 엔진을 다시 실행해 배분을 새로 저장한다. 수동 수정·확정은 초기화된다 (AT04, AT06).
    - keep: 기존 배분은 그대로, 수입 증가분을 미배분 금액에 더한다 (AT07). 수입이 줄었으면 409 (T09).
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
        plan.confirmed = False
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

def update_allocations(db: Session, month: str, items: list[AllocationItem]) -> PlanRead:
    """배분 금액을 직접 고친다. 총배분액이 총수입을 넘으면 저장 거부하고 초과액을 알려준다 (AT08)."""
    plan = _require_plan(db, month)
    by_id = {a.id: a for a in plan.allocations}
    missing = [item.allocation_id for item in items if item.allocation_id not in by_id]
    if missing:
        raise NotFoundError(f"{month} 계획에 없는 배분 항목입니다: allocation_id={missing}")

    new_amounts = {item.allocation_id: item.allocated_amount for item in items}
    new_total = sum(new_amounts.get(a.id, a.allocated_amount) for a in plan.allocations)
    if new_total > plan.total_income:
        excess = new_total - plan.total_income
        db.rollback()
        raise BadRequestError(
            f"총배분액 {new_total:,}원이 총수입 {plan.total_income:,}원보다 "
            f"{excess:,}원 많아 저장할 수 없습니다.",
            excess=excess,
        )

    for alloc_id, amount in new_amounts.items():
        by_id[alloc_id].allocated_amount = amount
        by_id[alloc_id].is_manual = True
    plan.total_allocated = new_total
    plan.unallocated = plan.total_income - new_total
    db.commit()
    db.refresh(plan)
    return to_plan_read(db, plan)


# ---------- 확정 (R08) ----------

def confirm(db: Session, month: str) -> PlanRead:
    """배분 계획을 확정한다. 확정된 목표 배분은 다음 달부터 확보액 C에 더해진다 (5.1)."""
    plan = _require_plan(db, month)
    if plan.status == "infeasible":
        subject, obj = (
            ("고정 지출이", "고정 지출을") if plan.shortage_target == "fixed"
            else ("최소 생활비가", "최소 생활비를")
        )
        raise BadRequestError(
            f"배분 불가 상태의 계획은 확정할 수 없습니다. "
            f"{subject} {plan.shortage:,}원 부족합니다. 수입이나 {obj} 조정한 뒤 재배분하세요."
        )
    plan.confirmed = True
    db.commit()
    db.refresh(plan)
    return to_plan_read(db, plan)
