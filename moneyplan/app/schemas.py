"""Pydantic 요청·응답 스키마와 입력 검증 규칙 (개발문서 6.1, N02, N05).

- 금액은 strict int: 0 이하·소수·문자열이면 422 (N02, 5.6, T01, T02)
- 월은 "YYYY-MM" 형식만 허용 (형식이 틀리면 422)
- PUT 수정은 전체 교체 방식이므로 …Update는 …Create와 같은 필드를 받는다.
"""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"

# 공통 타입
Month = Annotated[str, Field(pattern=MONTH_PATTERN, examples=["2026-11"], description="YYYY-MM")]
PositiveAmount = Annotated[int, Field(gt=0, strict=True, description="원 단위 정수, 0보다 커야 함")]
NonNegativeAmount = Annotated[int, Field(ge=0, strict=True, description="원 단위 정수, 0 이상")]
Memo = Annotated[str | None, Field(default=None, max_length=200)]
Name = Annotated[str, Field(min_length=1, max_length=100)]

IncomeType = Literal["salary", "allowance", "etc"]
Category = Literal["fixed", "living", "goal"]
PlanStatus = Literal["ok", "partial", "infeasible"]
GoalStatus = Literal["full", "short", "will_miss", "achieved", "period_error"]


class ReadModel(BaseModel):
    """ORM 객체에서 바로 변환되는 응답 모델의 기반."""

    model_config = ConfigDict(from_attributes=True)


# ---------- 수입 (R01) ----------

class IncomeCreate(BaseModel):
    """수입 등록 요청 (R01, T01)."""

    amount: PositiveAmount
    income_type: IncomeType
    income_date: date
    memo: Memo = None


class IncomeUpdate(IncomeCreate):
    """수입 수정 요청 (전체 교체)."""


class IncomeRead(ReadModel):
    """수입 응답."""

    id: int
    amount: int
    income_type: IncomeType
    income_date: date
    memo: str | None


# ---------- 목표 (R02) ----------

class GoalCreate(BaseModel):
    """목표 등록 요청 (R02). current_amount만 0 허용."""

    goal_name: Name
    target_amount: PositiveAmount
    current_amount: NonNegativeAmount = 0
    target_month: Month
    priority: Annotated[int, Field(ge=1, strict=True, description="1이 가장 높음")]


class GoalUpdate(GoalCreate):
    """목표 수정 요청 (전체 교체)."""


class GoalRead(ReadModel):
    """목표 응답."""

    id: int
    goal_name: str
    target_amount: int
    current_amount: int
    target_month: str
    priority: int


class GoalSecure(BaseModel):
    """목표 확보 등록 요청: 실제로 모은 금액 (C31, T20)."""

    amount: PositiveAmount


# ---------- 고정 지출 (R03) ----------

class FixedExpenseCreate(BaseModel):
    """고정 지출 등록 요청 (R03)."""

    expense_name: Name
    amount: PositiveAmount
    month: Month


class FixedExpenseUpdate(FixedExpenseCreate):
    """고정 지출 수정 요청 (전체 교체, C28)."""


class FixedExpenseRead(ReadModel):
    """고정 지출 응답."""

    id: int
    expense_name: str
    amount: int
    month: str


# ---------- 최소 생활비 (R04) ----------

class SettingUpdate(BaseModel):
    """최소 생활비 설정 요청 (R04). 월은 경로 파라미터로 받는다."""

    min_living: PositiveAmount


class SettingRead(ReadModel):
    """최소 생활비 응답."""

    month: str
    min_living: int


# ---------- 배분 계획 (R05~R09) ----------

class GoalResultRead(ReadModel):
    """목표별 배분 결과 — 엔진 GoalResult와 같은 필드 (R05, R07)."""

    goal_id: int
    name: str
    status: GoalStatus
    remaining_months: int
    shortfall_total: int
    required: int
    allocated: int
    lacking: int
    next_required: int | None


class AllocationRead(ReadModel):
    """저장된 배분 항목 (6.4 Allocation)."""

    id: int
    category: Category
    goal_id: int | None
    required_amount: int
    allocated_amount: int
    is_manual: bool
    goal_status: GoalStatus | None
    next_required: int | None


class PlanRead(BaseModel):
    """배분 계획 응답: 엔진 EngineResult 필드 + month, allocations."""

    month: str
    status: PlanStatus
    total_income: int
    fixed_allocated: int
    living_allocated: int
    goals: list[GoalResultRead]
    total_allocated: int
    unallocated: int
    shortage: int
    shortage_target: Literal["fixed", "living"] | None
    allocations: list[AllocationRead]


class AllocateResponse(BaseModel):
    """자동 배분·재배분 응답: 기존 계획과 새 계획을 나란히 보여준다 (5.5)."""

    previous: PlanRead | None
    current: PlanRead


class AllocationItem(BaseModel):
    """수동 수정 항목 하나 (R09)."""

    allocation_id: int
    allocated_amount: NonNegativeAmount


class AllocationUpdate(BaseModel):
    """배분 수동 수정 요청 (R09, AT08)."""

    items: Annotated[list[AllocationItem], Field(min_length=1)]

    @model_validator(mode="after")
    def check_unique_ids(self) -> "AllocationUpdate":
        """같은 배분 항목을 두 번 수정하지 못하게 한다."""
        ids = [item.allocation_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("같은 allocation_id가 여러 번 들어 있습니다.")
        return self


# ---------- 소비 (R10, R11) ----------

class ExpenseCreate(BaseModel):
    """소비 등록 요청 (R10, T02). category가 goal이면 goal_id 필수, 아니면 없어야 한다."""

    amount: PositiveAmount
    category: Category
    goal_id: int | None = None
    expense_date: date
    memo: Memo = None

    @model_validator(mode="after")
    def check_goal_id(self) -> "ExpenseCreate":
        """목적(category)과 goal_id 조합을 검증한다."""
        if self.category == "goal" and self.goal_id is None:
            raise ValueError("목적이 goal이면 goal_id를 입력해야 합니다.")
        if self.category != "goal" and self.goal_id is not None:
            raise ValueError(f"목적이 {self.category}이면 goal_id를 입력하면 안 됩니다.")
        return self


class ExpenseUpdate(ExpenseCreate):
    """소비 수정 요청 (전체 교체)."""


class ExpenseRead(ReadModel):
    """소비 응답."""

    id: int
    amount: int
    category: Category
    goal_id: int | None
    expense_date: date
    memo: str | None


class BalanceRead(BaseModel):
    """목적별 잔액 = 배분액 − 소비 합계, 음수이면 초과 소비 (R11, AT09, AT10, N06)."""

    category: Category
    goal_id: int | None
    name: str
    allocated: int
    spent: int
    balance: int
    is_over: bool


class ExpenseWithBalance(BaseModel):
    """소비 등록 응답: 등록된 소비 + 해당 목적의 잔액 (6.2 소비 등록 흐름)."""

    expense: ExpenseRead
    balance: BalanceRead


# ---------- 대시보드 (R12) ----------

class GoalProgressRead(BaseModel):
    """목표 달성률 = C ÷ T × 100, 소수 1자리 (5.2, R12). 비율이므로 float."""

    goal_id: int
    goal_name: str
    target_amount: int
    secured_amount: int
    achievement_rate: float


class DashboardRead(BaseModel):
    """월별 대시보드 응답 (R12, T11)."""

    month: str
    total_income: int
    plan: PlanRead | None
    balances: list[BalanceRead]
    goals: list[GoalProgressRead]
