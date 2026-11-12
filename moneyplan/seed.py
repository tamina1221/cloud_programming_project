"""기준 예시 데이터(개발문서 2장) 입력 스크립트.

실행: docker compose exec api python seed.py
DATABASE_URL의 DB에 넣는다. 이미 데이터가 있으면 아무것도 하지 않는다.
"""

from datetime import date

from sqlalchemy import select

from app.database import Base, SessionLocal, engine
from app.models import FixedExpense, Goal, Income, MonthlySetting

MONTH = "2026-11"


def has_data(db) -> bool:
    """입력 테이블 중 하나라도 데이터가 있는지 확인한다."""
    return any(
        db.scalar(select(model).limit(1)) is not None
        for model in (Income, Goal, FixedExpense, MonthlySetting)
    )


def seed() -> None:
    """기준 예시 데이터를 넣는다: 수입 900,000 / 고정 200,000 / 생활비 300,000 / 목표 2개."""
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        if has_data(db):
            print("이미 데이터가 있어 기준 예시 데이터를 넣지 않았습니다.")
            print("처음부터 다시 넣으려면: docker compose down -v → docker compose up -d → python seed.py")
            return

        db.add_all([
            Income(amount=900_000, income_type="salary", income_date=date(2026, 11, 10),
                   memo="11월 아르바이트 급여"),
            FixedExpense(expense_name="통신비·교통비", amount=200_000, month=MONTH),
            MonthlySetting(month=MONTH, min_living=300_000),
        ])
        # 등록 순서 = 우선순위 순 (N04)
        db.add(Goal(goal_name="비상금", target_amount=1_200_000, current_amount=0,
                    target_month="2027-04", priority=1))
        db.flush()
        db.add(Goal(goal_name="여행", target_amount=900_000, current_amount=300_000,
                    target_month="2027-01", priority=2))
        db.commit()

    print(f"기준 예시 데이터를 넣었습니다 ({MONTH}).")
    print("  수입 900,000 / 고정 지출 200,000 / 최소 생활비 300,000")
    print("  목표: 비상금 1,200,000 (2027-04, 우선순위 1), 여행 900,000 중 300,000 확보 (2027-01, 우선순위 2)")
    print(f"다음 단계: POST /plans/{MONTH}/allocate 로 자동 배분을 실행하세요.")


if __name__ == "__main__":
    seed()
