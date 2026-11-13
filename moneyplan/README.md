# MoneyPlan

목표 기반 월별 자금 배분 서비스. 설계는 `docs/MoneyPlan_개발문서.md` 참고.

## 실행

```bash
cp .env.example .env                     # Windows PowerShell: copy .env.example .env
docker compose up -d --build
# 화면: http://localhost:8000
# API 문서: http://localhost:8000/docs
docker compose exec api python seed.py   # 기준 예시 데이터
docker compose exec api pytest           # 테스트
```

코드를 고친 뒤에는 `docker compose up -d --build`로 다시 빌드해야 반영된다.
Windows에서 빌드가 `failed to execute bake`로 실패하면 PowerShell에서 대문자 `C:\...` 경로로 이동해 다시 실행한다.

## 구조

```
moneyplan/
├── app/
│   ├── main.py            # 앱 생성, 라우터 등록, 화면 파일 제공
│   ├── database.py        # DB 연결
│   ├── models.py          # 테이블
│   ├── schemas.py         # 요청·응답 검증
│   ├── engine.py          # 배분 엔진 (순수 함수, 핵심)
│   ├── services/          # DB ↔ 엔진 연결
│   └── routers/           # API 엔드포인트
├── frontend/              # 브라우저 화면 (HTML·CSS·JS)
├── tests/
│   ├── test_engine.py     # 엔진 단위 테스트
│   └── test_api.py        # API 통합 테스트
├── db/init/               # 테스트 DB 생성 SQL
├── docs/                  # 개발문서
├── seed.py
├── Dockerfile
├── .dockerignore          # .env 등을 이미지에서 제외
└── docker-compose.yml
```
