from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from app.database.connection import get_db
from app.schemas.artifact_summary import ArtifactSummaryCreate, ArtifactSummaryResponse
from app.crud import artifact_summary as crud

router = APIRouter(prefix="/artifact-summaries", tags=["artifact-summaries"])

@router.post("/", response_model=ArtifactSummaryResponse)
def create_artifact_summary(summary: ArtifactSummaryCreate, db: Session = Depends(get_db)):
    return crud.create_artifact_summary(db=db, summary=summary)

@router.get("/artifact/{artifact_id}", response_model=list[ArtifactSummaryResponse])
def get_summaries_by_artifact(artifact_id: UUID, db: Session = Depends(get_db)):
    summaries = crud.get_summaries_by_artifact(db, artifact_id=artifact_id)
    if not summaries:
        raise HTTPException(status_code=404, detail="No summaries found for this artifact")
    return summaries

@router.get("/{summary_id}", response_model=ArtifactSummaryResponse)
def get_artifact_summary(summary_id: UUID, db: Session = Depends(get_db)):
    summary = crud.get_artifact_summary(db, summary_id=summary_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Summary not found")
    return summary