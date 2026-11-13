# MoneyPlan

목표 기반 월별 자금 배분 서비스.
수입이 들어오거나 바뀌었을 때, 목표를 지키려면 이번 달 어디에 얼마를 넣어야 하는지 계산해 준다.

- 수입을 고정 지출 → 최소 생활비 → 목표(우선순위 순) 순서로 자동 배분
- 수입이 줄거나 늘면 재배분, 또는 기존 배분 유지 선택
- 목적별 소비를 기록하고 잔액·초과 소비 확인

설계와 테스트 기록은 [개발문서](moneyplan/docs/MoneyPlan_개발문서.md)에 있다.

---

## 1. 준비물

- Docker Desktop (Docker Compose 포함)
- 브라우저 (Chrome, Edge 등)

Python과 PostgreSQL은 컨테이너 안에서 실행되므로 따로 설치하지 않아도 된다.

## 2. 실행

모든 명령은 `moneyplan` 폴더에서 실행한다.

```bash
cd moneyplan

# 1) 환경변수 파일 만들기 (Windows PowerShell: copy .env.example .env)
cp .env.example .env

# 2) DB와 서버 실행
docker compose up -d --build

# 3) (선택) 기준 예시 데이터 넣기
docker compose exec api python seed.py
```

| 주소 | 내용 |
| --- | --- |
| http://localhost:8000 | 화면 |
| http://localhost:8000/docs | API 문서 (직접 호출 가능) |
| http://localhost:8000/health | 서버 상태 확인 |

테스트 실행:

```bash
docker compose exec api pytest
```

종료:

```bash
docker compose down      # 데이터는 유지
docker compose down -v   # 데이터까지 삭제
```

코드를 고친 뒤에는 `docker compose up -d --build`로 다시 빌드해야 반영된다.

## 3. 사용 방법

화면 위쪽에서 월을 고른 뒤 탭을 차례로 사용한다.

1. **입력**: 수입, 고정 지출, 최소 생활비, 목표(목표 금액·현재 확보액·목표 월·우선순위)를 등록한다.
2. **배분**: [자동 배분]을 누르면 상태(정상·부분 배분·배분 불가)와 배분 표가 나온다.
   - 목표 금액을 직접 고치고 [수정 저장]을 누르면 상태를 다시 판정한다.
   - 수입이 바뀌면 [자동 배분] 또는 [기존 유지]를 고른다.
3. **소비**: 소비를 등록하면 그 목적의 잔액이 바로 표시된다.
4. **대시보드**: 목적별 잔액, 초과 소비, 목표 달성률을 확인한다.

시드 데이터(`seed.py`)로 시작하면 개발문서 2장의 시나리오 1~4를 그대로 따라 해 볼 수 있다.

## 4. 자주 나는 오류

| 증상 | 해결 |
| --- | --- |
| Windows에서 `failed to execute bake` 로 빌드 실패 | PowerShell에서 대문자 `C:\...` 경로로 이동한 뒤 다시 실행 |
| 화면이 안 열리는데 컨테이너는 `Up` | `docker compose logs api`로 오류 확인 |
| `DATABASE_URL 환경변수가 없습니다` | `.env` 파일을 만들지 않음. 2장의 1) 실행 |
| `column ... does not exist` | `docker compose down -v` 후 다시 실행 |

---

## 5. 프로젝트 구조

```
cloud_programming_project/
├── README.md                    # 이 파일
└── moneyplan/
    ├── app/
    │   ├── main.py              # 앱 생성, 라우터 등록, 오류 메시지 처리, 화면 파일 제공
    │   ├── database.py          # DB 연결
    │   ├── models.py            # 테이블 정의
    │   ├── schemas.py           # 요청·응답 형식과 입력 검사
    │   ├── engine.py            # 배분 엔진 (계산만 담당, DB를 쓰지 않음)
    │   ├── services/            # 계산이 필요한 기능 처리
    │   │   ├── plan_service.py      # 자동 배분·재배분·수동 수정·목표 삭제
    │   │   ├── expense_service.py   # 소비 저장, 목적별 잔액
    │   │   └── dashboard_service.py # 월별 대시보드
    │   └── routers/             # API 경로
    │       ├── incomes.py  goals.py  fixed_expenses.py  settings.py
    │       └── plans.py  expenses.py  dashboard.py
    ├── frontend/                # 브라우저 화면
    │   ├── index.html
    │   ├── style.css
    │   └── app.js
    ├── tests/
    │   ├── conftest.py          # 테스트용 DB 준비
    │   ├── test_engine.py       # 엔진 테스트 (18개)
    │   └── test_api.py          # API 테스트 (24개)
    ├── db/init/
    │   └── 01_create_test_db.sql  # 테스트용 DB 생성
    ├── docs/
    │   └── MoneyPlan_개발문서.md
    ├── seed.py                  # 기준 예시 데이터 입력
    ├── requirements.txt
    ├── Dockerfile
    ├── docker-compose.yml
    ├── .env.example             # 환경변수 예시 (.env로 복사해 사용)
    └── .dockerignore            # .env 등을 이미지에서 제외
```

### 동작 구조

```
브라우저 화면 (frontend/)
 │  API 호출
 ▼
routers/ ─── 요청 처리: 경로·월 형식 확인, schemas.py로 입력 검사
 │      └─ 계산이 없는 저장·조회(수입·고정 지출·최소 생활비, 목표 등록·조회·수정)는 여기서 바로 DB 사용
 ▼
services/ ── 기능 처리: DB에서 값을 모아 엔진에 넘기고 결과를 저장
 │           (배분·재배분·수동 수정·목표 삭제, 소비와 잔액, 대시보드)
 ▼
engine.py ── 배분 계산 (같은 입력이면 항상 같은 결과)

models.py ↔ database.py ↔ PostgreSQL (pgdata 볼륨에 저장, 재실행해도 유지)
```

잘못된 입력은 422, 처리할 수 없는 요청은 400·404·409로 응답하며, 오류 메시지는 한국어로 표시된다.
