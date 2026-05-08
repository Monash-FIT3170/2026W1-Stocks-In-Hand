from sqlalchemy.orm import Session
from uuid import UUID
from app.models.information_platform import InformationPlatform
from app.schemas.information_platform import InformationPlatformCreate

def get_platform(db: Session, platform_id: UUID):
    return db.query(InformationPlatform).filter(InformationPlatform.id == platform_id).first()

def get_platform_by_name(db: Session, name: str):
    return db.query(InformationPlatform).filter(InformationPlatform.name == name).first()

def get_platforms(db: Session):
    return db.query(InformationPlatform).all()

def create_platform(db: Session, platform: InformationPlatformCreate):
    db_platform = InformationPlatform(**platform.model_dump())
    db.add(db_platform)
    db.commit()
    db.refresh(db_platform)
    return db_platform

def update_platform(db: Session, platform_id: UUID, data: dict):
    db_platform = get_platform(db, platform_id)
    for key, value in data.items():
        setattr(db_platform, key, value)
    db.commit()
    db.refresh(db_platform)
    return db_platform