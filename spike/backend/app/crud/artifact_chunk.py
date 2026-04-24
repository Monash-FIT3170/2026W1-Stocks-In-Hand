from sqlalchemy.orm import Session
from uuid import UUID
from app.models.artifact_chunk import ArtifactChunk
from app.schemas.artifact_chunk import ArtifactChunkCreate

def get_artifact_chunk(db: Session, chunk_id: UUID):
    return db.query(ArtifactChunk).filter(ArtifactChunk.id == chunk_id).first()

def get_chunks_by_artifact(db: Session, artifact_id: UUID):
    return (
        db.query(ArtifactChunk)
        .filter(ArtifactChunk.artifact_id == artifact_id)
        .order_by(ArtifactChunk.chunk_index)
        .all()
    )

def create_artifact_chunk(db: Session, chunk: ArtifactChunkCreate):
    db_chunk = ArtifactChunk(**chunk.model_dump())
    db.add(db_chunk)
    db.commit()
    db.refresh(db_chunk)
    return db_chunk