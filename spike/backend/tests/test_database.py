import sys
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database.base import Base
from app.models.user import User


def test_database_can_create_table_insert_and_read_user(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'test.db'}"
    engine = create_engine(database_url)
    TestingSessionLocal = sessionmaker(bind=engine)

    Base.metadata.create_all(bind=engine, tables=[User.__table__])

    with TestingSessionLocal() as session:
        user = User(name="Test User", email="test@example.com")
        session.add(user)
        session.commit()

    with TestingSessionLocal() as session:
        saved_user = session.execute(
            select(User).where(User.email == "test@example.com")
        ).scalar_one()

    assert saved_user.name == "Test User"
    assert saved_user.email == "test@example.com"
