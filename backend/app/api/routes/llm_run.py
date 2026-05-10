from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from app.database.connection import get_db
from app.schemas.llm_run import LLMRunCreate, LLMRunResponse
from app.crud import llm_run as crud

router = APIRouter(prefix="/llm-runs", tags=["llm-runs"])

@router.post("/", response_model=LLMRunResponse)
def create_llm_run(llm_run: LLMRunCreate, db: Session = Depends(get_db)):
    return crud.create_llm_run(db=db, llm_run=llm_run)

@router.get("/task/{task_type}", response_model=list[LLMRunResponse])
def get_llm_runs_by_task_type(task_type: str, db: Session = Depends(get_db)):
    runs = crud.get_llm_runs_by_task_type(db, task_type=task_type)
    if not runs:
        raise HTTPException(status_code=404, detail="No LLM runs found for this task type")
    return runs

@router.get("/{llm_run_id}", response_model=LLMRunResponse)
def get_llm_run(llm_run_id: UUID, db: Session = Depends(get_db)):
    run = crud.get_llm_run(db, llm_run_id=llm_run_id)
    if not run:
        raise HTTPException(status_code=404, detail="LLM run not found")
    return run
