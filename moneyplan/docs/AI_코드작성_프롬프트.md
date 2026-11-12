# MoneyPlan 코드 작성용 AI 프롬프트

## 사용 방법

- 프롬프트를 **0 → 1 → 2 → 3 → 4 순서로 하나씩** 보낸다. 한 번에 다 보내면 코드가 길어지고 검증이 어렵다.
- 매 단계마다 **[0] 공통 컨텍스트**를 맨 앞에 붙이고, 개발문서(`docs/MoneyPlan_개발문서.md`) 전체도 함께 첨부한다.
- 한 단계가 끝나면 `pytest`를 직접 돌려 통과를 확인한 뒤 다음 단계로 간다. 실패한 경우는 개발문서 8.2 개선 기록에 적는다(평가 20%).
- AI가 문서와 다르게 구현했다면, 코드를 문서에 맞추거나 문서를 고치고 8.3 변경 기록에 남긴다(설계 = 구현).

---

## [0] 공통 컨텍스트 (모든 단계 앞에 붙이기)

```
너는 대학 과제용 백엔드 프로젝트 "MoneyPlan"을 구현하는 Python 개발자다.
첨부한 개발문서가 유일한 명세다. 문서에 없는 기능은 만들지 말고, 문서와 다르게 판단해야 하는 부분이 있으면 코드를 쓰기 전에 먼저 알려줘.

[프로젝트 핵심]
수입이 들어오거나 바뀌었을 때, 목표를 지키려면 이번 달 어디에 얼마를 넣어야 하는지 계산한다.
중심은 배분 엔진(app/engine.py) 하나이고, 나머지는 엔진의 입력·출력·보조다.

[기술 스택]
Python 3.12, FastAPI, SQLAlchemy 2.0 (Mapped/mapped_column 스타일, 동기), psycopg 3, Pydantic v2, PostgreSQL 16, pytest, Docker Compose.
Alembic, 인증, 프론트엔드는 사용하지 않는다. 테이블은 앱 시작 시 Base.metadata.create_all로 만든다.

[이미 만들어진 디렉터리 구조 — 이 파일들만 채운다]
moneyplan/
├── app/
│   ├── main.py              # FastAPI 앱, 시작 시 create_all, 라우터 등록
│   ├── database.py          # engine, SessionLocal, Base, get_db
│   ├── models.py            # SQLAlchemy 모델
│   ├── schemas.py           # Pydantic 스키마
│   ├── engine.py            # 배분 엔진 (순수 함수, DB·FastAPI import 금지)
│   ├── services/
│   │   ├── plan_service.py      # 엔진 입력 수집, 배분·재배분·수동 수정·확정
│   │   ├── expense_service.py   # 소비 저장, 목적별 잔액
│   │   └── dashboard_service.py # 월별 대시보드
│   └── routers/
│       ├── incomes.py  goals.py  fixed_expenses.py  settings.py
│       ├── plans.py  expenses.py  dashboard.py
├── tests/
│   ├── conftest.py   test_engine.py   test_api.py
├── seed.py
├── requirements.txt  Dockerfile  docker-compose.yml  .env.example
환경변수: DATABASE_URL, TEST_DATABASE_URL (형식: postgresql+psycopg://...)

[공통 규칙]
- 금액은 모두 int(원). float 사용 금지. 올림은 정수 연산으로: -(-a // b)
- 월은 "YYYY-MM" 문자열로 다룬다. 형식이 틀리면 422.
- 계층 의존: routers → services → engine / models. engine은 아무것도 import하지 않는다(표준 라이브러리 제외).
- 오류 메시지는 한국어로, 원인을 알 수 있게 쓴다.
- 함수와 클래스에 짧은 한국어 docstring을 단다. 개발문서의 ID(R05, AT04, T06 등)를 주석으로 연결한다.
- 출력 형식: 파일마다 경로를 제목으로 쓰고 전체 코드를 준다. 마지막에 실행·테스트 방법을 3줄 이내로 쓴다.
```

---

## [1] 배분 엔진 + 엔진 단위 테스트

```
이번 단계에서는 app/engine.py 와 tests/test_engine.py 만 작성해. DB는 쓰지 않는다.
개발문서 5장(배분 엔진 설계)을 그대로 구현한다.

[데이터 구조] (dataclass, frozen=True)
- GoalInput: goal_id:int, name:str, target_amount:int, secured_amount:int, target_month:str, priority:int, created_order:int
- EngineInput: month:str, total_income:int, fixed_total:int, min_living:int, goals:list[GoalInput]
- GoalResult: goal_id, name, status, remaining_months, shortfall_total(S), required(R), allocated(a), lacking(R-a, 0 이상), next_required(R' 또는 None)
- EngineResult: status, total_income, fixed_allocated, living_allocated, goals:list[GoalResult], total_allocated, unallocated, shortage(배분 불가일 때 부족액, 아니면 0), shortage_target("fixed" | "living" | None)

[함수]
- months_between(month, target_month) -> int : n = (Dy*12+Dm) - (My*12+Mm) + 1
- required_amount(shortfall, n) -> int : ceil(shortfall / n)
- allocate(inp: EngineInput) -> EngineResult : 메인 함수
- keep_existing(previous: EngineResult, new_total_income:int) -> EngineResult : "기존 유지" 모드

[allocate 규칙]
1. I < F → status="infeasible", shortage=F-I, shortage_target="fixed", fixed_allocated=I, 나머지 0
2. I-F < L → status="infeasible", shortage=L-(I-F), shortage_target="living", fixed_allocated=F, living_allocated=I-F, 목표 배분 0
3. 목표 정렬: priority 오름차순 → target_month 빠른 순 → created_order 순 (N04)
4. 목표별 상태(status):
   - S ≤ 0 → "achieved", 배분 제외
   - n < 1 → "period_error", 배분 제외
   - 그 외 a = min(R, 남은 금액). a == R → "full", a < R 이고 n == 1 → "will_miss"(next_required=None), a < R 이고 n > 1 → "short"(next_required = ceil((S-a)/(n-1)))
5. 계획 status: 목표 중 short 또는 will_miss가 하나라도 있으면 "partial", 아니면 "ok"
6. unallocated = I - total_allocated. 항상 total_allocated + unallocated == I 를 assert로 확인한다.
7. 같은 입력이면 같은 결과(부작용·랜덤·현재 시각 사용 금지)

[keep_existing 규칙]
- new_total_income < previous.total_allocated → ValueError("수입이 감소해 기존 배분을 유지할 수 없습니다. 재배분을 실행하세요.") (T09)
- 그 외 배분은 그대로, unallocated = new_total_income - total_allocated

[tests/test_engine.py] 기준 예시 데이터를 픽스처로 만든다:
기준 월 2026-11, 수입 900,000, 고정 200,000, 생활비 300,000,
비상금(우선순위1) 목표 1,200,000 / 확보 0 / 2027-04, 여행(우선순위2) 목표 900,000 / 확보 300,000 / 2027-01

다음 테스트를 각각 별도 함수로 작성하고, 함수 이름에 ID를 넣는다(예: test_AT04_income_decrease).
- AT02: 여행 n=3, R=200,000
- AT03: 고정 200,000 / 생활비 300,000 / 비상금 200,000 / 여행 200,000, 미배분 0, status ok
- AT04: 수입 700,000 → 비상금 200,000, 여행 0, partial, 여행 lacking 200,000, next_required 300,000
- AT05: 수입 400,000 → infeasible, shortage 100,000, shortage_target living
- AT06: AT04 후 수입 900,000으로 allocate → ok, 여행 200,000
- AT07: AT03 결과에 keep_existing(…, 1,100,000) → 배분 동일, 미배분 200,000
- T03: 확보액 ≥ 목표 → achieved, 배분 0
- T04: 목표 월 2026-10 → period_error, 배분 0
- T05: n=1, 부족액 500,000, 배분 가능 300,000 → allocated 300,000, will_miss, next_required None
- T06: 부족액 1,000,000, n=3 → R 333,334
- T07: 우선순위 같은 목표 2개, 남은 돈이 하나만 채울 만큼 → 목표 월 빠른 쪽이 먼저
- T08: 같은 입력 2회 → 결과 동일(==)
- T09: 수입 감소 후 keep_existing → ValueError
```

---

## [2] DB 연결 · 모델 · 스키마

```
1단계의 app/engine.py 는 완성되어 있다(첨부). 이번 단계에서는 app/database.py, app/models.py, app/schemas.py 만 작성해.

[database.py]
- DATABASE_URL 환경변수로 engine 생성, SessionLocal, DeclarativeBase 상속 Base, get_db() 제너레이터

[models.py] 개발문서 6.4를 따른다.
- Income: id, amount(int), income_type("salary"|"allowance"|"etc"), income_date(date), memo(nullable)
- Goal: id, goal_name, target_amount, current_amount, target_month(str "YYYY-MM"), priority(int), created_at
- FixedExpense: id, expense_name, amount, month
- MonthlySetting: month(PK), min_living
- AllocationPlan: id, month(unique), total_income, total_allocated, unallocated, status("ok"|"partial"|"infeasible"), confirmed(bool, 기본 False), shortage, shortage_target(nullable)
- Allocation: id, plan_id(FK, cascade 삭제), category("fixed"|"living"|"goal"), goal_id(FK nullable), required_amount, allocated_amount, is_manual(bool)
  - 목표별 상태와 next_required도 응답에 필요하므로 goal_status(nullable), next_required(nullable) 컬럼을 추가한다.
    (개발문서 6.4에 없는 컬럼이므로 추가 사실을 답변 끝에 알려줘 — 문서에 반영할 것이다.)
- Expense: id, amount, category("fixed"|"living"|"goal"), goal_id(FK nullable), expense_date, memo
- 관계: AllocationPlan 1:N Allocation, Goal 1:N Allocation, Goal 1:N Expense
- Goal 삭제 시 연결된 Allocation·Expense가 있으면 삭제를 막는다(409로 처리할 수 있게 서비스에서 확인).

[schemas.py] 생성·수정·응답 스키마를 나눈다(…Create, …Update, …Read).
- 금액 필드: int, gt=0 (N02, T01, T02). current_amount만 ge=0.
- 월 필드: pattern r"^\d{4}-(0[1-9]|1[0-2])$"
- Expense: category가 "goal"이면 goal_id 필수, 아니면 goal_id 없어야 함(model_validator)
- 배분 응답 PlanRead: 엔진의 EngineResult 필드 + month, confirmed, allocations 목록
- 배분 수동 수정 요청 AllocationUpdate: items: list[{allocation_id:int, allocated_amount:int(ge=0)}]
- 대시보드 응답 DashboardRead: month, total_income, plan(PlanRead | None), balances(목적별 배분·소비·잔액·is_over), goals(목표별 달성률 %, 소수 1자리)
```

---

## [3] 서비스 · 라우터 · main

```
engine.py, database.py, models.py, schemas.py 는 완성되어 있다(첨부). 이번 단계에서는 app/services/*, app/routers/*, app/main.py 를 작성해.
API 경로는 개발문서 6.3 표와 정확히 같아야 한다.

[plan_service.py]
- build_engine_input(db, month): 해당 월 수입 합계(income_date가 그 월), 고정 지출 합계(month 일치), MonthlySetting.min_living(없으면 404 "최소 생활비를 먼저 설정하세요"), 목표 목록
  - 확보액 C = goal.current_amount + (month보다 이전 월의 confirmed=True 계획에서 그 목표에 배분된 금액 합계) (개발문서 5.1)
- allocate(db, month, mode):
  - mode="reallocate"(기본): 엔진 allocate 실행 → 기존 계획이 있으면 Allocation을 모두 지우고 새로 저장, confirmed=False로 되돌림, is_manual 초기화(5.5)
  - mode="keep": 기존 계획이 없으면 404. 기존 계획을 EngineResult로 복원해 keep_existing 실행, ValueError면 409와 그 메시지(T09)
  - 응답: {"previous": 이전 계획 또는 null, "current": 새 계획} — 기존 계획과 나란히 보여주기 위함(5.5)
- update_allocations(db, month, items): 금액 변경 후 total_allocated > total_income 이면 롤백하고 400 {"detail": "...", "excess": 초과액} (AT08). 통과하면 is_manual=True, unallocated 재계산
- confirm(db, month): status가 "infeasible"이면 400, 아니면 confirmed=True

[expense_service.py]
- 소비 CRUD
- balances(db, month): 해당 월 계획의 목적별(fixed, living, 목표별) 배분액 - 해당 월 소비 합계. 음수면 is_over=True (AT09, AT10, N06)
- 소비 등록 응답에 해당 목적의 잔액과 is_over를 함께 담는다(6.2 소비 등록 흐름)

[dashboard_service.py]
- get_dashboard(db, month): 수입 합계, 계획, balances, 목표별 달성률(C÷T×100). 다른 월 데이터가 섞이면 안 된다(T11)

[routers]
- incomes: POST, GET(?month= 필터), GET /{id}, PUT /{id}, DELETE /{id}
- goals: POST, GET, PUT /{id}, DELETE /{id}
- fixed-expenses: POST, GET(?month=), DELETE /{id}
- settings: PUT /settings/{month} body {min_living}, GET /settings/{month}
- plans: POST /plans/{month}/allocate?mode=reallocate|keep, GET /plans/{month}, PUT /plans/{month}/allocations, POST /plans/{month}/confirm
- expenses: POST, GET(?month=), PUT /{id}, DELETE /{id}
- dashboard: GET /dashboard/{month}
- 없는 id는 404, 각 라우터에 tags 지정

[main.py]
- FastAPI(title="MoneyPlan"), lifespan에서 create_all, 모든 라우터 등록, GET /health → {"status":"ok"}
```

---

## [4] API 통합 테스트 · 시드 데이터

```
앱 코드는 완성되어 있다(첨부). 이번 단계에서는 tests/conftest.py, tests/test_api.py, seed.py 를 작성해.

[conftest.py]
- TEST_DATABASE_URL로 별도 엔진 생성, 테스트 함수마다 drop_all → create_all
- app.dependency_overrides[get_db]로 테스트 세션 주입, TestClient 픽스처 제공
- 기준 예시 데이터를 API로 넣는 seeded_client 픽스처 (2026-11 수입 900,000 / 고정 200,000 / 생활비 300,000 / 목표 2개)

[test_api.py] 함수 이름에 ID를 넣는다.
- AT01: 수입 900,000 등록 → GET /incomes?month=2026-11 합계 900,000
- AT03: allocate → status ok, 미배분 0
- AT04: 수입을 700,000으로 수정 후 allocate → partial, 여행 next_required 300,000
- AT05: 수입 400,000 → infeasible, shortage 100,000
- AT06: AT04 후 용돈 200,000 추가, reallocate → ok
- AT07: AT03 후 용돈 200,000 추가, keep → 미배분 200,000
- AT08: AT03 후 여행 배분 400,000으로 수정 → 400, excess 200,000
- AT09·AT10: 생활비 소비 200,000 → 잔액 100,000, 추가 150,000 → 잔액 -50,000, is_over True
- T01: 수입 -10,000 → 422 / T02: 소비 0 → 422
- T09: 수입 감소 후 mode=keep → 409
- T10: 생활비 소비 200,000 후 최소 생활비를 150,000으로 바꾸고 reallocate → 소비 기록 유지, 잔액 -50,000
- T11: 11월·12월 수입이 있을 때 /dashboard/2026-11 → 11월 수입만 합산

[seed.py]
- DATABASE_URL에 기준 예시 데이터를 넣는다. 이미 데이터가 있으면 아무것도 하지 않고 안내 메시지를 출력한다.
- 실행: docker compose exec api python seed.py

AT11(컨테이너 재시작 후 데이터 유지)은 자동 테스트가 아니라 수동 확인 절차를 3단계로 써줘.
```

---

## 단계별 확인 체크리스트

| 단계 | 확인 명령 | 통과 기준 |
| --- | --- | --- |
| 1 | `docker compose exec api pytest tests/test_engine.py` | 엔진 테스트 13개 통과 |
| 2 | `docker compose up -d --build` 후 `docker compose logs api` | 오류 없이 시작, DB에 테이블 7개 생성 |
| 3 | `http://localhost:8000/docs` | 6.3의 API가 모두 보이고 수동 호출 성공 |
| 4 | `docker compose exec api pytest` | 전체 테스트 통과, `seed.py` 실행 성공 |
