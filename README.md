# MoneyPlan

목표 기반 월별 자금 배분 서비스. 설계는 `docs/MoneyPlan_개발문서.md` 참고.

## 실행

```bash
cp .env.example .env
docker compose up -d --build
# API 문서: http://localhost:8000/docs
docker compose exec api python seed.py   # 기준 예시 데이터
docker compose exec api pytest           # 테스트
```

## 구조

### 프로젝트 dir 구조
```
moneyplan/
├── app/
│   ├── main.py            # 앱 생성, 라우터 등록
│   ├── database.py        # DB 연결
│   ├── models.py          # 테이블
│   ├── schemas.py         # 요청·응답 검증
│   ├── engine.py          # 배분 엔진 (순수 함수, 핵심)
│   ├── services/          # DB ↔ 엔진 연결
│   └── routers/           # API 엔드포인트
├── tests/
│   ├── test_engine.py     # 엔진 단위 테스트
│   └── test_api.py        # API 통합 테스트
├── db/init/               # 테스트 DB 생성 SQL
├── docs/                  # 개발문서
├── seed.py
├── Dockerfile
└── docker-compose.yml
```
### 동작 구조
```
요청
 │
 ▼
main.py ─── 오류 처리기 (422 입력 오류 / ServiceError → 400·404·409)
 │
 ▼
routers/ ─── 경로·월 형식 검사, schemas.py로 입력 검증
 │      └─ 단순 CRUD(수입·목표·고정 지출·생활비)는 여기서 바로 DB 저장 (C14)
 ▼
services/ ── plan_service    : DB → 엔진 입력 → 엔진 실행 → 결과 저장
 │           expense_service : 소비 저장, 목적별 잔액
 │           dashboard_service: 위 둘을 조합
 ▼
engine.py ── 순수 계산 (DB를 모름)
 │
models.py ↔ database.py ↔ PostgreSQL
```
'''
