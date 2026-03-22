import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Float
from sqlalchemy.orm import declarative_base, sessionmaker
from transformers import pipeline

# --- DB ---
engine = create_engine(os.environ["DATABASE_URL"])
Session = sessionmaker(bind=engine)
Base = declarative_base()

class Result(Base):
    __tablename__ = "results"
    id    = Column(Integer, primary_key=True)
    text  = Column(String)
    label = Column(String)
    score = Column(Float)

Base.metadata.create_all(engine)

# --- HuggingFace: FinBERT (financial sentiment) ---
sentiment = pipeline("text-classification", model="ProsusAI/finbert")

# --- API ---
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class AnalyseRequest(BaseModel):
    text: str

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/analyse")
def analyse(body: AnalyseRequest):
    out = sentiment(body.text[:512])[0]
    with Session() as db:
        row = Result(text=body.text, label=out["label"].lower(), score=round(out["score"], 4))
        db.add(row)
        db.commit()
        db.refresh(row)
    return {"id": row.id, "label": row.label, "score": row.score}

@app.get("/results")
def results():
    with Session() as db:
        rows = db.query(Result).order_by(Result.id.desc()).limit(10).all()
    return [{"id": r.id, "text": r.text[:80], "label": r.label, "score": r.score} for r in rows]
