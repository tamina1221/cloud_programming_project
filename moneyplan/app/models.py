"""SQLAlchemy 테이블 정의 (개발문서 6.4).

Income, Goal, FixedExpense, MonthlySetting, AllocationPlan, Allocation, Expense.
금액은 모두 정수(원) 컬럼이다 (N01). 월은 "YYYY-MM" 문자열이다.
"""

from datetime import date

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# 월 컬럼 공통 길이 ("YYYY-MM")
MONTH_LEN = 7


class Income(Base):
    """수입 기록 (R01)."""

    __tablename__ = "income"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_income_amount_positive"),
        CheckConstraint("income_type IN ('salary', 'allowance', 'etc')", name="ck_income_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    income_type: Mapped[str] = mapped_column(String(20))
    income_date: Mapped[date] = mapped_column(Date, index=True)
    memo: Mapped[str | None] = mapped_column(String(200))


class Goal(Base):
    """목표 (R02). 우선순위·목표 월이 같으면 id(등록 순)로 정렬한다 (N04, 6.4)."""

    __tablename__ = "goal"
    __table_args__ = (
        CheckConstraint("target_amount > 0", name="ck_goal_target_positive"),
        CheckConstraint("current_amount >= 0", name="ck_goal_current_nonneg"),
        CheckConstraint("priority >= 1", name="ck_goal_priority"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    goal_name: Mapped[str] = mapped_column(String(100))
    target_amount: Mapped[int] = mapped_column(BigInteger)
    current_amount: Mapped[int] = mapped_column(BigInteger, default=0)
    target_month: Mapped[str] = mapped_column(String(MONTH_LEN))
    priority: Mapped[int] = mapped_column(Integer)

    # FK는 RESTRICT: 삭제 시 서비스가 배분 항목을 먼저 지우고, 소비 기록이 있으면 409 (C19)
    allocations: Mapped[list["Allocation"]] = relationship(back_populates="goal", passive_deletes="all")


class FixedExpense(Base):
    """월별 고정 지출 항목 (R03)."""

    __tablename__ = "fixed_expense"
    __table_args__ = (CheckConstraint("amount > 0", name="ck_fixed_amount_positive"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    expense_name: Mapped[str] = mapped_column(String(100))
    amount: Mapped[int] = mapped_column(BigInteger)
    month: Mapped[str] = mapped_column(String(MONTH_LEN), index=True)


class MonthlySetting(Base):
    """월별 최소 생활비 (R04). 월당 1행."""

    __tablename__ = "monthly_setting"
    __table_args__ = (CheckConstraint("min_living > 0", name="ck_setting_min_living_positive"),)

    month: Mapped[str] = mapped_column(String(MONTH_LEN), primary_key=True)
    min_living: Mapped[int] = mapped_column(BigInteger)


class AllocationPlan(Base):
    """월별 배분 계획 (R06~R09). 월당 1개, 엔진 결과 EngineResult를 저장한다."""

    __tablename__ = "allocation_plan"
    __table_args__ = (
        CheckConstraint("status IN ('ok', 'partial', 'infeasible')", name="ck_plan_status"),
        CheckConstraint(
            "shortage_target IS NULL OR shortage_target IN ('fixed', 'living')",
            name="ck_plan_shortage_target",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    month: Mapped[str] = mapped_column(String(MONTH_LEN), unique=True)
    total_income: Mapped[int] = mapped_column(BigInteger)
    total_allocated: Mapped[int] = mapped_column(BigInteger)
    unallocated: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20))
    shortage: Mapped[int] = mapped_column(BigInteger, default=0)
    shortage_target: Mapped[str | None] = mapped_column(String(10))

    allocations: Mapped[list["Allocation"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Allocation.id",
    )


class Allocation(Base):
    """배분 항목 (category: fixed, living, goal).

    goal_status는 목표별 상태, next_required는 다음 달 필요 적립액 R' (6.4, C08).
    is_manual은 수동 수정으로 금액이 바뀐 항목 (R09, C22).
    """

    __tablename__ = "allocation"
    __table_args__ = (
        CheckConstraint("category IN ('fixed', 'living', 'goal')", name="ck_allocation_category"),
        CheckConstraint(
            "(category = 'goal') = (goal_id IS NOT NULL)", name="ck_allocation_goal_id"
        ),
        CheckConstraint("allocated_amount >= 0", name="ck_allocation_amount_nonneg"),
        CheckConstraint(
            "goal_status IS NULL OR goal_status IN "
            "('full', 'short', 'will_miss', 'achieved', 'period_error')",
            name="ck_allocation_goal_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("allocation_plan.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(10))
    goal_id: Mapped[int | None] = mapped_column(ForeignKey("goal.id", ondelete="RESTRICT"))
    required_amount: Mapped[int] = mapped_column(BigInteger)
    allocated_amount: Mapped[int] = mapped_column(BigInteger)
    is_manual: Mapped[bool] = mapped_column(Boolean, default=False)
    goal_status: Mapped[str | None] = mapped_column(String(20))
    next_required: Mapped[int | None] = mapped_column(BigInteger)

    plan: Mapped[AllocationPlan] = relationship(back_populates="allocations")
    goal: Mapped[Goal | None] = relationship(back_populates="allocations")


class Expense(Base):
    """소비 기록 (R10). category가 goal이면 goal_id가 있어야 한다."""

    __tablename__ = "expense"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_expense_amount_positive"),
        CheckConstraint("category IN ('fixed', 'living', 'goal')", name="ck_expense_category"),
        CheckConstraint("(category = 'goal') = (goal_id IS NOT NULL)", name="ck_expense_goal_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    category: Mapped[str] = mapped_column(String(10))
    goal_id: Mapped[int | None] = mapped_column(ForeignKey("goal.id", ondelete="RESTRICT"))
    expense_date: Mapped[date] = mapped_column(Date, index=True)
    memo: Mapped[str | None] = mapped_column(String(200))
