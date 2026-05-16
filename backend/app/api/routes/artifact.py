from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from app.database.connection import get_db
from app.schemas.artifact import ArtifactCreate, ArtifactResponse
from app.crud import artifact as crud

router = APIRouter(prefix="/artifacts", tags=["artifacts"])

@router.get("/", response_model=list[ArtifactResponse])
def list_artifacts(limit: int = 200, offset: int = 0, db: Session = Depends(get_db)):
    return crud.get_all_artifacts(db, limit=limit, offset=offset)

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

@router.get("/compiled/recent", response_model=list[ArtifactResponse])
def get_recent_compiled_artifacts(
    days: int = 30,
    limit: int = 200,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    return crud.get_recent_compiled_artifacts(
        db=db,
        days=days,
        limit=limit,
        offset=offset,
    )

@router.get("/{artifact_id}", response_model=ArtifactResponse)
def get_artifact(artifact_id: UUID, db: Session = Depends(get_db)):
    artifact = crud.get_artifact(db, artifact_id=artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return artifact
