from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from app.database.connection import get_db
from app.schemas.artifact_chunk import ArtifactChunkCreate, ArtifactChunkResponse
from app.crud import artifact_chunk as crud

router = APIRouter(prefix="/artifact-chunks", tags=["artifact-chunks"])

@router.post("/", response_model=ArtifactChunkResponse)
def create_artifact_chunk(chunk: ArtifactChunkCreate, db: Session = Depends(get_db)):
    return crud.create_artifact_chunk(db=db, chunk=chunk)

@router.get("/artifact/{artifact_id}", response_model=list[ArtifactChunkResponse])
def get_chunks_by_artifact(artifact_id: UUID, db: Session = Depends(get_db)):
    chunks = crud.get_chunks_by_artifact(db, artifact_id=artifact_id)
    if not chunks:
        raise HTTPException(status_code=404, detail="No chunks found for this artifact")
    return chunks

@router.get("/{chunk_id}", response_model=ArtifactChunkResponse)
def get_artifact_chunk(chunk_id: UUID, db: Session = Depends(get_db)):
    chunk = crud.get_artifact_chunk(db, chunk_id=chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail="Chunk not found")
    return chunk