from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from app.database.connection import get_db
from app.schemas.artifact import ArtifactCreate, ArtifactResponse
from app.crud import artifact as crud

router = APIRouter(prefix="/artifacts", tags=["artifacts"])

@router.post("/", response_model=ArtifactResponse)
def create_artifact(artifact: ArtifactCreate, db: Session = Depends(get_db)):
    return crud.create_artifact(db=db, artifact=artifact)

@router.get("/ticker/{ticker_id}", response_model=list[ArtifactResponse])
def get_artifacts_by_ticker(ticker_id: UUID, db: Session = Depends(get_db)):
    artifacts = crud.get_artifacts_by_ticker(db, ticker_id=ticker_id)
    if not artifacts:
        raise HTTPException(status_code=404, detail="No artifacts found for this ticker")
    return artifacts

@router.get("/platform/{platform_id}", response_model=list[ArtifactResponse])
def get_artifacts_by_platform(platform_id: UUID, db: Session = Depends(get_db)):
    artifacts = crud.get_artifacts_by_platform(db, platform_id=platform_id)
    if not artifacts:
        raise HTTPException(status_code=404, detail="No artifacts found for this platform")
    return artifacts

@router.get("/{artifact_id}", response_model=ArtifactResponse)
def get_artifact(artifact_id: UUID, db: Session = Depends(get_db)):
    artifact = crud.get_artifact(db, artifact_id=artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return artifact