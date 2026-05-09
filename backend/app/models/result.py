from sqlalchemy import Column, Float, Integer, String

from app.database.base import Base


class Result(Base):
    """Stored sentiment analysis result."""

    __tablename__ = "results"

    id = Column(Integer, primary_key=True)
    text = Column(String)
    label = Column(String)
    score = Column(Float)
