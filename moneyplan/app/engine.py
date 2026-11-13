"""배분 엔진: DB를 사용하지 않는 순수 계산 함수 (개발문서 5장).

- 금액은 모두 int(원). 올림은 정수 연산 -(-a // b) 로 한다. (N01)
- 부작용·랜덤·현재 시각을 쓰지 않으므로 같은 입력에는 같은 결과를 낸다. (N04, T08)
"""

from dataclasses import dataclass, replace

# 계획 상태 (5.4)
PLAN_OK = "ok"                  # 정상
PLAN_PARTIAL = "partial"        # 부분 배분
PLAN_INFEASIBLE = "infeasible"  # 배분 불가

# 목표 상태 (5.3, 5.6)
GOAL_FULL = "full"                  # 필요 적립액을 모두 받음
GOAL_SHORT = "short"                # 일부만 받음, 다음 달 필요 적립액 R' 표시
GOAL_WILL_MISS = "will_miss"        # n = 1인데 다 못 받음 → 목표 미달 예정 (T05)
GOAL_ACHIEVED = "achieved"          # S ≤ 0 → 목표 달성, 배분 제외 (T03)
GOAL_PERIOD_ERROR = "period_error"  # n < 1 → 목표 기간 오류, 배분 제외 (T04)


@dataclass(frozen=True)
class GoalInput:
    """엔진에 넣는 목표 하나 (5.1). secured_amount는 확보액 C."""

    goal_id: int
    name: str
    target_amount: int
    secured_amount: int
    target_month: str
    priority: int
    created_order: int


@dataclass(frozen=True)
class EngineInput:
    """엔진 입력 (5.1): 기준 월 M, 총수입 I, 고정 지출 F, 최소 생활비 L, 목표 목록."""

    month: str
    total_income: int
    fixed_total: int
    min_living: int
    goals: list[GoalInput]


@dataclass(frozen=True)
class GoalResult:
    """목표별 배분 결과 (R05, R07)."""

    goal_id: int
    name: str
    status: str
    remaining_months: int       # n
    shortfall_total: int        # S = T − C
    required: int               # R = ⌈S ÷ n⌉
    allocated: int              # a
    lacking: int                # R − a (0 이상)
    next_required: int | None   # R' = ⌈(S − a) ÷ (n − 1)⌉, 해당 없으면 None


@dataclass(frozen=True)
class EngineResult:
    """배분 계획 전체 결과 (R06, R07)."""

    status: str
    total_income: int
    fixed_allocated: int
    living_allocated: int
    goals: list[GoalResult]
    total_allocated: int
    unallocated: int
    shortage: int                 # 배분 불가일 때 부족액, 아니면 0
    shortage_target: str | None   # "fixed" | "living" | None


def _month_index(month: str) -> int:
    """'YYYY-MM' 문자열을 (연도×12 + 월) 정수로 바꾼다."""
    try:
        year_str, mon_str = month.split("-")
        year, mon = int(year_str), int(mon_str)
    except (ValueError, AttributeError):
        raise ValueError(f"월 형식이 올바르지 않습니다: {month!r} (YYYY-MM 형식이어야 합니다)")
    if len(year_str) != 4 or len(mon_str) != 2 or not 1 <= mon <= 12:
        raise ValueError(f"월 형식이 올바르지 않습니다: {month!r} (YYYY-MM 형식이어야 합니다)")
    return year * 12 + mon


def _ceil_div(a: int, b: int) -> int:
    """정수 올림 나눗셈 (N01)."""
    return -(-a // b)


def months_between(month: str, target_month: str) -> int:
    """남은 개월 수 n (기준 월 포함). n = (Dy×12+Dm) − (My×12+Mm) + 1 (5.2, AT02)."""
    return _month_index(target_month) - _month_index(month) + 1


def required_amount(shortfall: int, n: int) -> int:
    """월 필요 적립액 R = ⌈S ÷ n⌉ (R05, T06). n ≥ 1이어야 한다."""
    if n < 1:
        raise ValueError(f"남은 개월 수는 1 이상이어야 합니다: n={n}")
    return _ceil_div(shortfall, n)


def _goal_sort_key(goal: GoalInput) -> tuple[int, int, int]:
    """정렬 기준: 우선순위 → 목표 월 빠른 순 → 등록 순 (N04, T07)."""
    return (goal.priority, _month_index(goal.target_month), goal.created_order)


def _goal_required(month: str, goal: GoalInput) -> int:
    """목표의 이번 달 필요 적립액 R. 목표 달성(S ≤ 0)·기간 오류(n < 1)는 배분 제외라 0 (5.7)."""
    n = months_between(month, goal.target_month)
    s = goal.target_amount - goal.secured_amount
    return 0 if s <= 0 or n < 1 else required_amount(s, n)


def _judge_goal(month: str, goal: GoalInput, allocated: int) -> GoalResult:
    """배분액 a로 목표 상태와 다음 달 필요 적립액 R'을 판정한다 (5.3 5단계, 5.6)."""
    n = months_between(month, goal.target_month)
    s = goal.target_amount - goal.secured_amount
    a = allocated

    if s <= 0:  # T03: 목표 달성
        return GoalResult(goal.goal_id, goal.name, GOAL_ACHIEVED, n, s, 0, a, 0, None)
    if n < 1:  # T04: 목표 기간 오류
        return GoalResult(goal.goal_id, goal.name, GOAL_PERIOD_ERROR, n, s, 0, a, 0, None)

    r = required_amount(s, n)
    if a >= r:  # 수동 수정으로 R보다 많이 넣어도 충족 (T13)
        status, next_required = GOAL_FULL, None
    elif n == 1:  # T05: 목표 미달 예정
        status, next_required = GOAL_WILL_MISS, None
    else:  # AT04, T13: 다음 달 필요 적립액 R'
        status, next_required = GOAL_SHORT, _ceil_div(s - a, n - 1)
    return GoalResult(goal.goal_id, goal.name, status, n, s, r, a, max(r - a, 0), next_required)


def _plan_status(goal_results: list[GoalResult]) -> str:
    """5.4: 부족한 목표가 하나라도 있으면 부분 배분, 없으면 정상."""
    lacking = any(g.status in (GOAL_SHORT, GOAL_WILL_MISS) for g in goal_results)
    return PLAN_PARTIAL if lacking else PLAN_OK


def allocate(inp: EngineInput) -> EngineResult:
    """자동 배분 (R06, R07): 고정 지출 → 최소 생활비 → 목표(우선순위 순). 재배분도 이 함수를 다시 호출한다 (R08)."""
    income, fixed, living = inp.total_income, inp.fixed_total, inp.min_living
    ordered = sorted(inp.goals, key=_goal_sort_key)

    if income < fixed:  # 5.3 2단계: 고정 지출 부족
        status, shortage, target = PLAN_INFEASIBLE, fixed - income, "fixed"
        fixed_alloc, living_alloc, available = income, 0, 0
    elif income - fixed < living:  # 5.3 3단계: 생활비 부족 (AT05)
        status, shortage, target = PLAN_INFEASIBLE, living - (income - fixed), "living"
        fixed_alloc, living_alloc, available = fixed, income - fixed, 0
    else:
        status, shortage, target = None, 0, None
        fixed_alloc, living_alloc, available = fixed, living, income - fixed - living  # A = I − F − L

    # 배분 불가여도 목표 목록은 배분 0원으로 결과에 담는다 (available = 0).
    goal_results: list[GoalResult] = []
    remaining = available
    for goal in ordered:
        a = min(_goal_required(inp.month, goal), remaining)  # 5.3 4단계: min(R, 남은 금액)
        goal_results.append(_judge_goal(inp.month, goal, a))
        remaining -= a

    if status is None:
        status = _plan_status(goal_results)

    total_allocated = fixed_alloc + living_alloc + sum(g.allocated for g in goal_results)
    unallocated = income - total_allocated
    assert total_allocated + unallocated == income  # 5.3 7단계
    assert unallocated >= 0

    return EngineResult(
        status=status,
        total_income=income,
        fixed_allocated=fixed_alloc,
        living_allocated=living_alloc,
        goals=goal_results,
        total_allocated=total_allocated,
        unallocated=unallocated,
        shortage=shortage,
        shortage_target=target,
    )


def evaluate(
    inp: EngineInput,
    fixed_allocated: int,
    living_allocated: int,
    goal_allocated: dict[int, int],
) -> EngineResult:
    """주어진 배분 금액으로 상태를 다시 판정한다 (수동 수정·목표 삭제용, R09, 5.6, C18).

    goal_allocated에 없는 목표는 0원으로 판정한다.
    """
    if fixed_allocated < inp.fixed_total or living_allocated < inp.min_living:  # T14
        raise ValueError(
            "고정 지출과 최소 생활비는 필요 금액보다 줄일 수 없습니다. "
            f"(고정 지출 {inp.fixed_total:,}원, 최소 생활비 {inp.min_living:,}원)"
        )

    ordered = sorted(inp.goals, key=_goal_sort_key)
    goal_results = [_judge_goal(inp.month, g, goal_allocated.get(g.goal_id, 0)) for g in ordered]

    total_allocated = fixed_allocated + living_allocated + sum(g.allocated for g in goal_results)
    if total_allocated > inp.total_income:  # AT08: 서비스에서도 먼저 확인
        raise ValueError(f"총배분액이 총수입보다 {total_allocated - inp.total_income:,}원 많습니다.")

    return EngineResult(
        status=_plan_status(goal_results),
        total_income=inp.total_income,
        fixed_allocated=fixed_allocated,
        living_allocated=living_allocated,
        goals=goal_results,
        total_allocated=total_allocated,
        unallocated=inp.total_income - total_allocated,
        shortage=0,
        shortage_target=None,
    )


def keep_existing(previous: EngineResult, new_total_income: int) -> EngineResult:
    """'기존 유지' 재배분 (R08, 5.5, AT07): 배분은 그대로 두고 증가분을 미배분 금액에 더한다.

    배분 불가 계획(T12, C17)이거나 새 수입이 기존 총배분액보다 적으면(T09) 유지할 수 없으므로 ValueError.
    """
    if previous.status == PLAN_INFEASIBLE:  # 상태·부족액이 갱신되지 않아 결과가 모순됨 (C17)
        raise ValueError("배분 불가 상태의 계획은 유지할 수 없습니다. 재배분을 실행하세요.")
    if new_total_income < previous.total_allocated:
        raise ValueError("수입이 감소해 기존 배분을 유지할 수 없습니다. 재배분을 실행하세요.")
    unallocated = new_total_income - previous.total_allocated
    assert previous.total_allocated + unallocated == new_total_income
    return replace(
        previous,
        total_income=new_total_income,
        goals=list(previous.goals),
        unallocated=unallocated,
    )
