import sys
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database.base import Base
from app.models.result import Result


def test_database_can_create_table_insert_and_read_result(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'test.db'}"
    engine = create_engine(database_url)
    TestingSessionLocal = sessionmaker(bind=engine)

    Base.metadata.create_all(bind=engine, tables=[Result.__table__])

    with TestingSessionLocal() as session:
        result = Result(text="ASX headline", label="positive", score=0.95)
        session.add(result)
        session.commit()

    with TestingSessionLocal() as session:
        saved_result = session.execute(
            select(Result).where(Result.text == "ASX headline")
        ).scalar_one()

    assert saved_result.label == "positive"
    assert saved_result.score == 0.95
