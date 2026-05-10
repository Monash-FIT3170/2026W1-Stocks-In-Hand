from sqlalchemy.orm import Session
from uuid import UUID
from app.models.llm_run import LLMRun
from app.schemas.llm_run import LLMRunCreate

def get_llm_run(db: Session, llm_run_id: UUID):
    return db.query(LLMRun).filter(LLMRun.id == llm_run_id).first()

def get_llm_runs_by_task_type(db: Session, task_type: str):
    return db.query(LLMRun).filter(LLMRun.task_type == task_type).all()

def create_llm_run(db: Session, llm_run: LLMRunCreate):
    db_run = LLMRun(**llm_run.model_dump())
    db.add(db_run)
    db.commit()
    db.refresh(db_run)
    return db_run
