"""API 통합 테스트 (개발문서 7장 인수 테스트, 8.1 테스트 계획). 모두 기준 예시 데이터에서 시작한다."""

from tests.conftest import MONTH, Seeded


# ---------- 도우미 ----------

def allocate(s: Seeded, mode: str = "reallocate"):
    """자동 배분·재배분을 호출한다."""
    return s.client.post(f"/plans/{MONTH}/allocate", params={"mode": mode})


def goal_result(plan: dict, goal_id: int) -> dict:
    """계획 응답에서 목표별 결과를 찾는다."""
    return next(g for g in plan["goals"] if g["goal_id"] == goal_id)


def set_income(s: Seeded, amount: int) -> None:
    """기준 수입(11월 급여)의 금액을 바꾼다."""
    r = s.client.put(
        f"/incomes/{s.income_id}",
        json={"amount": amount, "income_type": "salary", "income_date": "2026-11-10"},
    )
    assert r.status_code == 200, r.json()


def add_allowance(s: Seeded, amount: int = 200_000) -> None:
    """11월 용돈 수입을 추가한다."""
    r = s.client.post(
        "/incomes", json={"amount": amount, "income_type": "allowance", "income_date": "2026-11-20"}
    )
    assert r.status_code == 201, r.json()


def add_living_expense(s: Seeded, amount: int) -> dict:
    """생활비 소비를 등록하고 응답을 돌려준다."""
    r = s.client.post(
        "/expenses", json={"amount": amount, "category": "living", "expense_date": "2026-11-12"}
    )
    assert r.status_code == 201, r.json()
    return r.json()


def living_balance(s: Seeded) -> dict:
    """대시보드에서 생활비 잔액을 찾는다."""
    dashboard = s.client.get(f"/dashboard/{MONTH}").json()
    return next(b for b in dashboard["balances"] if b["category"] == "living")


# ---------- 인수 테스트 ----------

def test_AT01_register_income(client):
    """AT01: 11월 수입 900,000원 등록 → 11월 수입 합계 900,000원."""
    r = client.post(
        "/incomes", json={"amount": 900_000, "income_type": "salary", "income_date": "2026-11-10"}
    )
    assert r.status_code == 201
    incomes = client.get("/incomes", params={"month": MONTH}).json()
    assert sum(i["amount"] for i in incomes) == 900_000


def test_AT03_auto_allocate(seeded_client):
    """AT03: 자동 배분 → 고정 200,000 / 생활비 300,000 / 비상금 200,000 / 여행 200,000, 미배분 0, 정상."""
    s = seeded_client
    r = allocate(s)
    assert r.status_code == 200, r.json()
    plan = r.json()["current"]
    assert plan["status"] == "ok"
    assert plan["unallocated"] == 0
    assert plan["fixed_allocated"] == 200_000
    assert plan["living_allocated"] == 300_000
    assert goal_result(plan, s.emergency_id)["allocated"] == 200_000
    assert goal_result(plan, s.travel_id)["allocated"] == 200_000
    assert r.json()["previous"] is None


def test_AT04_income_decrease(seeded_client):
    """AT04: 수입 700,000으로 수정 후 재배분 → 부분 배분, 여행 부족액 200,000, 다음 달 필요 적립액 300,000."""
    s = seeded_client
    allocate(s)
    set_income(s, 700_000)
    plan = allocate(s).json()["current"]
    travel = goal_result(plan, s.travel_id)
    assert plan["status"] == "partial"
    assert goal_result(plan, s.emergency_id)["allocated"] == 200_000
    assert travel["allocated"] == 0
    assert travel["lacking"] == 200_000
    assert travel["next_required"] == 300_000


def test_AT05_infeasible(seeded_client):
    """AT05: 수입 400,000 → 배분 불가, 생활비 부족액 100,000원."""
    s = seeded_client
    set_income(s, 400_000)
    plan = allocate(s).json()["current"]
    assert plan["status"] == "infeasible"
    assert plan["shortage"] == 100_000
    assert plan["shortage_target"] == "living"


def test_AT06_extra_income_reallocate(seeded_client):
    """AT06: AT04 상태에서 용돈 200,000 추가 후 재배분 → 총수입 900,000, 여행 200,000, 정상."""
    s = seeded_client
    set_income(s, 700_000)
    assert allocate(s).json()["current"]["status"] == "partial"
    add_allowance(s)
    body = allocate(s, "reallocate").json()
    plan = body["current"]
    assert plan["status"] == "ok"
    assert plan["total_income"] == 900_000
    assert goal_result(plan, s.travel_id)["allocated"] == 200_000
    assert body["previous"]["status"] == "partial"  # 기존 계획과 나란히 표시 (5.5)


def test_AT07_extra_income_keep(seeded_client):
    """AT07: AT03 상태에서 용돈 200,000 추가 후 기존 유지 → 배분 그대로, 미배분 200,000."""
    s = seeded_client
    allocate(s)
    add_allowance(s)
    body = allocate(s, "keep").json()
    before, after = body["previous"], body["current"]
    assert after["unallocated"] == 200_000
    assert after["total_income"] == 1_100_000
    assert after["goals"] == before["goals"]
    assert after["total_allocated"] == before["total_allocated"] == 900_000


def test_AT08_manual_edit_exceeds_income(seeded_client):
    """AT08: AT03 상태에서 여행 배분을 400,000으로 수정 → 저장 거부, 초과 금액 200,000원."""
    s = seeded_client
    plan = allocate(s).json()["current"]
    travel_alloc = next(a for a in plan["allocations"] if a["goal_id"] == s.travel_id)
    r = s.client.put(
        f"/plans/{MONTH}/allocations",
        json={"items": [{"allocation_id": travel_alloc["id"], "allocated_amount": 400_000}]},
    )
    assert r.status_code == 400
    assert r.json()["excess"] == 200_000
    # 거부되었으므로 저장된 값은 그대로
    saved = s.client.get(f"/plans/{MONTH}").json()
    assert goal_result(saved, s.travel_id)["allocated"] == 200_000


def test_AT09_AT10_living_balance(seeded_client):
    """AT09·AT10: 생활비 소비 200,000 → 잔액 100,000. 150,000 추가 → 잔액 −50,000, 초과 소비."""
    s = seeded_client
    allocate(s)
    first = add_living_expense(s, 200_000)["balance"]
    assert first["balance"] == 100_000
    assert first["is_over"] is False
    second = add_living_expense(s, 150_000)["balance"]
    assert second["balance"] == -50_000
    assert second["is_over"] is True


# ---------- 테스트 계획 (8.1) ----------

def test_T01_negative_income(client):
    """T01: 수입 −10,000원 등록 → 422 입력 오류."""
    r = client.post(
        "/incomes", json={"amount": -10_000, "income_type": "salary", "income_date": "2026-11-10"}
    )
    assert r.status_code == 422
    assert client.get("/incomes").json() == []


def test_T02_zero_expense(client):
    """T02: 소비 0원 등록 → 422 입력 오류."""
    r = client.post(
        "/expenses", json={"amount": 0, "category": "living", "expense_date": "2026-11-10"}
    )
    assert r.status_code == 422


def test_T09_keep_rejected_after_decrease(seeded_client):
    """T09: 수입 감소 후 '기존 유지' 선택 → 409, 재배분 안내."""
    s = seeded_client
    allocate(s)
    set_income(s, 700_000)
    r = allocate(s, "keep")
    assert r.status_code == 409
    assert "재배분" in r.json()["detail"]


def test_T10_reallocate_keeps_expenses(seeded_client):
    """T10: 생활비 200,000 소비 후 최소 생활비를 150,000으로 바꿔 재배분 → 소비 기록 유지, 잔액 −50,000, 초과 소비 (N06)."""
    s = seeded_client
    allocate(s)
    add_living_expense(s, 200_000)
    s.client.put(f"/settings/{MONTH}", json={"min_living": 150_000})
    plan = allocate(s).json()["current"]
    assert plan["living_allocated"] == 150_000
    assert len(s.client.get("/expenses", params={"month": MONTH}).json()) == 1
    living = living_balance(s)
    assert living["balance"] == -50_000
    assert living["is_over"] is True


def test_T11_dashboard_month_only(seeded_client):
    """T11: 11월·12월 수입이 있을 때 11월 대시보드 → 11월 수입만 합산."""
    s = seeded_client
    s.client.post(
        "/incomes", json={"amount": 500_000, "income_type": "salary", "income_date": "2026-12-10"}
    )
    dashboard = s.client.get(f"/dashboard/{MONTH}").json()
    assert dashboard["total_income"] == 900_000
    assert dashboard["month"] == MONTH


def alloc_id(plan: dict, category: str, goal_id: int | None = None) -> int:
    """계획 응답에서 배분 항목 id를 찾는다."""
    return next(
        a["id"] for a in plan["allocations"] if a["category"] == category and a["goal_id"] == goal_id
    )


def put_allocations(s: Seeded, amounts: dict[int, int]):
    """배분 항목 id → 금액으로 수동 수정을 호출한다."""
    items = [{"allocation_id": i, "allocated_amount": v} for i, v in amounts.items()]
    return s.client.put(f"/plans/{MONTH}/allocations", json={"items": items})


def test_T12_keep_rejected_when_infeasible(seeded_client):
    """T12: 수입 400,000(배분 불가) → 용돈 200,000 추가 → 기존 유지 → 409, 재배분 안내 (C17)."""
    s = seeded_client
    set_income(s, 400_000)
    assert allocate(s).json()["current"]["status"] == "infeasible"
    add_allowance(s)
    r = allocate(s, "keep")
    assert r.status_code == 409, r.json()
    assert "재배분" in r.json()["detail"]


def test_T13_manual_edit_rejudges(seeded_client):
    """T13: 수입 700,000에서 비상금 100,000, 여행 100,000으로 수정 → 두 목표 short, R' 220,000 / 250,000, partial (C18)."""
    s = seeded_client
    set_income(s, 700_000)
    plan = allocate(s).json()["current"]
    r = put_allocations(s, {
        alloc_id(plan, "goal", s.emergency_id): 100_000,
        alloc_id(plan, "goal", s.travel_id): 100_000,
    })
    assert r.status_code == 200, r.json()
    edited = r.json()
    emergency, travel = goal_result(edited, s.emergency_id), goal_result(edited, s.travel_id)
    assert emergency["status"] == "short"
    assert emergency["next_required"] == 220_000
    assert travel["status"] == "short"
    assert travel["next_required"] == 250_000
    assert edited["status"] == "partial"
    assert edited["unallocated"] == 0


def test_T14_manual_edit_living_below_minimum(seeded_client):
    """T14: 기준 데이터 배분 후 생활비를 200,000으로 수정 → 400, 저장된 생활비 300,000 유지 (C18)."""
    s = seeded_client
    plan = allocate(s).json()["current"]
    r = put_allocations(s, {alloc_id(plan, "living"): 200_000})
    assert r.status_code == 400, r.json()
    assert s.client.get(f"/plans/{MONTH}").json()["living_allocated"] == 300_000


def test_T15_delete_goal_rejudges_plan(seeded_client):
    """T15: 수입 700,000(부분 배분)에서 여행 목표 삭제 → 204, 여행 항목 삭제, 상태 ok, 미배분 0 (C19)."""
    s = seeded_client
    set_income(s, 700_000)
    assert allocate(s).json()["current"]["status"] == "partial"
    r = s.client.delete(f"/goals/{s.travel_id}")
    assert r.status_code == 204, r.json()
    plan = s.client.get(f"/plans/{MONTH}").json()
    assert all(a["goal_id"] != s.travel_id for a in plan["allocations"])
    assert plan["status"] == "ok"
    assert plan["total_allocated"] == 700_000
    assert plan["unallocated"] == 0


def test_T16_delete_goal_with_expense(seeded_client):
    """T16: 여행 목표로 소비 50,000 등록 후 여행 목표 삭제 → 409, 목표 유지 (C19)."""
    s = seeded_client
    allocate(s)
    r = s.client.post(
        "/expenses",
        json={"amount": 50_000, "category": "goal", "goal_id": s.travel_id, "expense_date": "2026-11-15"},
    )
    assert r.status_code == 201, r.json()
    r = s.client.delete(f"/goals/{s.travel_id}")
    assert r.status_code == 409
    assert "소비 기록" in r.json()["detail"]
    assert any(g["id"] == s.travel_id for g in s.client.get("/goals").json())


def test_T17_manual_edit_rejected_when_infeasible(seeded_client):
    """T17: 수입 400,000(배분 불가)에서 목표 배분 수정 → 400, 재배분 안내 (C18)."""
    s = seeded_client
    set_income(s, 400_000)
    plan = allocate(s).json()["current"]
    r = put_allocations(s, {alloc_id(plan, "goal", s.travel_id): 0})
    assert r.status_code == 400, r.json()
    assert "재배분" in r.json()["detail"]


def test_N07_index_served(client):
    """N07: GET / → 브라우저 화면(HTML) 제공 (C21)."""
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "MoneyPlan" in r.text


def test_N05_korean_error_messages(client):
    """N05: 422 응답의 msg가 원인을 알 수 있는 한국어 메시지인지 확인 (T01·T02는 상태 코드만 확인)."""
    r = client.post(
        "/incomes", json={"amount": 0, "income_type": "salary", "income_date": "2026-11-10"}
    )
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"] == ["body", "amount"]
    assert r.json()["detail"][0]["msg"] == "0보다 커야 합니다."

    r = client.post(
        "/expenses", json={"amount": 1_000, "category": "goal", "expense_date": "2026-11-10"}
    )
    assert r.status_code == 422
    assert r.json()["detail"][0]["msg"] == "목적이 goal이면 goal_id를 입력해야 합니다."

    r = client.get("/plans/2026-13")
    assert r.status_code == 422
    assert r.json()["detail"][0]["msg"] == "YYYY-MM 형식이어야 합니다. (예: 2026-11)"
