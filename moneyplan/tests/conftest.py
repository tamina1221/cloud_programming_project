"""테스트용 DB·TestClient 픽스처.

- TEST_DATABASE_URL의 별도 DB를 쓰고, 테스트 함수마다 drop_all → create_all로 비운다.
- 앱의 get_db를 테스트 세션으로 바꿔 끼운다. 개발 DB(DATABASE_URL)는 건드리지 않는다.
"""

import os
import warnings
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from starlette.exceptions import StarletteDeprecationWarning

with warnings.catch_warnings():
    # starlette TestClient의 httpx 지원 중단 예정 경고 — 테스트 결과와 무관 (8.2)
    warnings.simplefilter("ignore", StarletteDeprecationWarning)
    from fastapi.testclient import TestClient

from app.database import Base, get_db
from app.main import app

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    raise RuntimeError(
        "TEST_DATABASE_URL 환경변수가 없습니다. .env에 테스트 DB 주소를 넣으세요. "
        "(예: postgresql+psycopg://moneyplan:moneyplan@db:5432/moneyplan_test)"
    )

test_engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)

MONTH = "2026-11"


def override_get_db() -> Iterator[Session]:
    """요청마다 테스트 DB 세션을 연다."""
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client() -> Iterator[TestClient]:
    """빈 테스트 DB에 연결된 TestClient. lifespan(개발 DB create_all)은 실행하지 않는다."""
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@dataclass
class Seeded:
    """기준 예시 데이터가 들어간 클라이언트와 생성된 id들."""

    client: TestClient
    income_id: int
    emergency_id: int
    travel_id: int


@pytest.fixture
def seeded_client(client: TestClient) -> Seeded:
    """기준 예시 데이터(개발문서 2장)를 API로 넣는다: 2026-11 수입 900,000 / 고정 200,000 / 생활비 300,000 / 목표 2개."""
    income = client.post(
        "/incomes", json={"amount": 900_000, "income_type": "salary", "income_date": "2026-11-10"}
    )
    fixed = client.post(
        "/fixed-expenses", json={"expense_name": "통신비·교통비", "amount": 200_000, "month": MONTH}
    )
    setting = client.put(f"/settings/{MONTH}", json={"min_living": 300_000})
    emergency = client.post(
        "/goals",
        json={"goal_name": "비상금", "target_amount": 1_200_000, "current_amount": 0,
              "target_month": "2027-04", "priority": 1},
    )
    travel = client.post(
        "/goals",
        json={"goal_name": "여행", "target_amount": 900_000, "current_amount": 300_000,
              "target_month": "2027-01", "priority": 2},
    )
    for r in (income, fixed, emergency, travel):
        assert r.status_code == 201, r.json()
    assert setting.status_code == 200, setting.json()
    return Seeded(client, income.json()["id"], emergency.json()["id"], travel.json()["id"])
