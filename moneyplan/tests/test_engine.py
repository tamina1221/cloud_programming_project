"""배분 엔진 단위 테스트 (DB 없음). 개발문서 7장 인수 테스트·8.1 테스트 계획."""

from dataclasses import replace

import pytest

from app.engine import (
    EngineInput,
    GoalInput,
    allocate,
    evaluate,
    keep_existing,
    months_between,
    required_amount,
)

EMERGENCY_ID = 1
TRAVEL_ID = 2


@pytest.fixture
def base_input() -> EngineInput:
    """기준 예시 데이터 (개발문서 2장, C07)."""
    return EngineInput(
        month="2026-11",
        total_income=900_000,
        fixed_total=200_000,
        min_living=300_000,
        goals=[
            GoalInput(EMERGENCY_ID, "비상금", 1_200_000, 0, "2027-04", 1, 1),
            GoalInput(TRAVEL_ID, "여행", 900_000, 300_000, "2027-01", 2, 2),
        ],
    )


def goal_of(result, goal_id):
    """결과에서 goal_id에 해당하는 목표 결과를 찾는다."""
    return next(g for g in result.goals if g.goal_id == goal_id)


def test_AT02_required_amount(base_input):
    """AT02: 여행 n = 3, 월 필요 적립액 200,000원."""
    assert months_between("2026-11", "2027-01") == 3
    assert required_amount(900_000 - 300_000, 3) == 200_000
    travel = goal_of(allocate(base_input), TRAVEL_ID)
    assert travel.remaining_months == 3
    assert travel.required == 200_000


def test_AT03_auto_allocate(base_input):
    """AT03: 고정 200,000 / 생활비 300,000 / 비상금 200,000 / 여행 200,000, 미배분 0, 정상."""
    result = allocate(base_input)
    assert result.fixed_allocated == 200_000
    assert result.living_allocated == 300_000
    assert goal_of(result, EMERGENCY_ID).allocated == 200_000
    assert goal_of(result, TRAVEL_ID).allocated == 200_000
    assert result.unallocated == 0
    assert result.total_allocated == 900_000
    assert result.status == "ok"


def test_AT04_income_decrease(base_input):
    """AT04: 수입 700,000 → 비상금 200,000, 여행 0, 부분 배분, 여행 부족액 200,000, R' 300,000."""
    result = allocate(replace(base_input, total_income=700_000))
    travel = goal_of(result, TRAVEL_ID)
    assert goal_of(result, EMERGENCY_ID).allocated == 200_000
    assert travel.allocated == 0
    assert result.status == "partial"
    assert travel.status == "short"
    assert travel.lacking == 200_000
    assert travel.required == 200_000
    assert travel.next_required == 300_000


def test_AT05_infeasible_living(base_input):
    """AT05: 수입 400,000 → 배분 불가, 생활비 부족액 100,000원."""
    result = allocate(replace(base_input, total_income=400_000))
    assert result.status == "infeasible"
    assert result.shortage == 100_000
    assert result.shortage_target == "living"
    assert result.fixed_allocated == 200_000
    assert result.living_allocated == 200_000
    assert all(g.allocated == 0 for g in result.goals)
    assert result.unallocated == 0


def test_AT06_reallocate_after_extra_income(base_input):
    """AT06: AT04 상태에서 용돈 200,000 추가 후 재배분 → 총수입 900,000, 여행 200,000, 정상."""
    decreased = allocate(replace(base_input, total_income=700_000))
    assert decreased.status == "partial"
    result = allocate(replace(base_input, total_income=700_000 + 200_000))
    assert result.total_income == 900_000
    assert goal_of(result, TRAVEL_ID).allocated == 200_000
    assert result.status == "ok"


def test_AT07_keep_existing(base_input):
    """AT07: AT03 상태에서 용돈 200,000 추가 후 기존 유지 → 배분 동일, 미배분 200,000."""
    before = allocate(base_input)
    after = keep_existing(before, 1_100_000)
    assert after.goals == before.goals
    assert after.fixed_allocated == before.fixed_allocated
    assert after.living_allocated == before.living_allocated
    assert after.total_allocated == before.total_allocated
    assert after.total_income == 1_100_000
    assert after.unallocated == 200_000


def test_T03_goal_already_achieved(base_input):
    """T03: 확보액 ≥ 목표 금액 → 목표 달성 상태, 배분 제외."""
    done = GoalInput(3, "노트북", 500_000, 500_000, "2027-01", 1, 3)
    result = allocate(replace(base_input, goals=[*base_input.goals, done]))
    g = goal_of(result, 3)
    assert g.status == "achieved"
    assert g.allocated == 0


def test_T04_period_error(base_input):
    """T04: 목표 월(2026-10)이 기준 월보다 이전 → 목표 기간 오류, 배분 제외."""
    past = GoalInput(3, "지난 목표", 500_000, 0, "2026-10", 1, 3)
    result = allocate(replace(base_input, goals=[*base_input.goals, past]))
    g = goal_of(result, 3)
    assert g.remaining_months == 0
    assert g.status == "period_error"
    assert g.allocated == 0


def test_T05_target_month_is_this_month():
    """T05: n = 1, 부족액 500,000, 배분 가능 300,000 → 300,000 배분, 목표 미달 예정."""
    inp = EngineInput(
        month="2026-11",
        total_income=800_000,
        fixed_total=200_000,
        min_living=300_000,
        goals=[GoalInput(1, "이번 달 목표", 500_000, 0, "2026-11", 1, 1)],
    )
    result = allocate(inp)
    g = goal_of(result, 1)
    assert g.remaining_months == 1
    assert g.required == 500_000
    assert g.allocated == 300_000
    assert g.status == "will_miss"
    assert g.next_required is None
    assert result.status == "partial"


def test_T06_required_amount_rounds_up():
    """T06: 부족액 1,000,000, n = 3 → 월 필요 적립액 333,334원 (올림)."""
    assert required_amount(1_000_000, 3) == 333_334


def test_T07_same_priority_earlier_month_first():
    """T07: 우선순위가 같으면 목표 월이 빠른 목표부터 배분 (등록 순서와 무관)."""
    inp = EngineInput(
        month="2026-11",
        total_income=700_000,  # 배분 가능 200,000: 한 목표만 채울 수 있음
        fixed_total=200_000,
        min_living=300_000,
        goals=[
            GoalInput(1, "늦은 목표", 1_200_000, 0, "2027-04", 1, 1),  # R = 200,000
            GoalInput(2, "빠른 목표", 600_000, 0, "2027-01", 1, 2),    # R = 200,000
        ],
    )
    result = allocate(inp)
    assert [g.goal_id for g in result.goals] == [2, 1]
    assert goal_of(result, 2).allocated == 200_000
    assert goal_of(result, 1).allocated == 0


def test_T08_deterministic(base_input):
    """T08: 같은 입력으로 엔진 2회 실행 → 두 결과가 완전히 같음 (N04)."""
    assert allocate(base_input) == allocate(base_input)


def test_T09_keep_rejected_on_income_decrease(base_input):
    """T09: 수입 감소 후 '기존 유지' 선택 → 거부, 재배분 안내."""
    before = allocate(base_input)
    with pytest.raises(ValueError, match="재배분"):
        keep_existing(before, 700_000)


def test_T12_keep_rejected_when_infeasible(base_input):
    """T12: 배분 불가(수입 400,000) 후 600,000으로 늘리고 '기존 유지' → 거부, 재배분 안내 (C17)."""
    before = allocate(replace(base_input, total_income=400_000))
    assert before.status == "infeasible"
    with pytest.raises(ValueError, match="재배분"):
        keep_existing(before, 600_000)


def test_T13_evaluate_after_manual_edit(base_input):
    """T13: 수입 700,000에서 비상금 100,000, 여행 100,000으로 수정 → 두 목표 short, 계획 partial (5.6 예)."""
    inp = replace(base_input, total_income=700_000)
    result = evaluate(inp, 200_000, 300_000, {EMERGENCY_ID: 100_000, TRAVEL_ID: 100_000})
    emergency, travel = goal_of(result, EMERGENCY_ID), goal_of(result, TRAVEL_ID)
    assert emergency.status == "short"
    assert emergency.next_required == 220_000
    assert travel.status == "short"
    assert travel.next_required == 250_000
    assert result.status == "partial"
    assert result.unallocated == 0


def test_T13_evaluate_goal_over_required(base_input):
    """T13: 비상금에 R보다 많은 400,000, 여행 0 → 비상금 full, 여행 short(R' 300,000), 계획 partial."""
    result = evaluate(base_input, 200_000, 300_000, {EMERGENCY_ID: 400_000, TRAVEL_ID: 0})
    emergency, travel = goal_of(result, EMERGENCY_ID), goal_of(result, TRAVEL_ID)
    assert emergency.status == "full"
    assert emergency.allocated == 400_000
    assert emergency.lacking == 0
    assert travel.status == "short"
    assert travel.next_required == 300_000
    assert result.status == "partial"


def test_T14_evaluate_rejects_living_below_minimum(base_input):
    """T14: 생활비를 최소 생활비(300,000)보다 적은 200,000으로 수정 → 거부 (C18)."""
    with pytest.raises(ValueError, match="줄일 수 없습니다"):
        evaluate(base_input, 200_000, 200_000, {EMERGENCY_ID: 200_000, TRAVEL_ID: 200_000})


def test_evaluate_matches_allocate(base_input):
    """allocate 결과의 금액을 그대로 evaluate에 넣으면 같은 판정이 나온다 (5.6)."""
    r = allocate(base_input)
    e = evaluate(
        base_input, r.fixed_allocated, r.living_allocated, {g.goal_id: g.allocated for g in r.goals}
    )
    assert e.status == r.status
    assert e.goals == r.goals
    assert e.unallocated == r.unallocated
