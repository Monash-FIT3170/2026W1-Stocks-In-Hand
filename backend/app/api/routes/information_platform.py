from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from app.database.connection import get_db
from app.schemas.information_platform import InformationPlatformCreate, InformationPlatformResponse
from app.crud import information_platform as crud

router = APIRouter(prefix="/information-platforms", tags=["information-platforms"])

@router.post("/", response_model=InformationPlatformResponse)
def create_platform(platform: InformationPlatformCreate, db: Session = Depends(get_db)):
    existing = crud.get_platform_by_name(db, name=platform.name)
    if existing:
        raise HTTPException(status_code=400, detail="Platform already exists")
    return crud.create_platform(db=db, platform=platform)

@router.get("/", response_model=list[InformationPlatformResponse])
def get_platforms(db: Session = Depends(get_db)):
    return crud.get_platforms(db)

@router.get("/{platform_id}", response_model=InformationPlatformResponse)
def get_platform(platform_id: UUID, db: Session = Depends(get_db)):
    platform = crud.get_platform(db, platform_id=platform_id)
    if not platform:
        raise HTTPException(status_code=404, detail="Platform not found")
    return platform

@router.patch("/{platform_id}", response_model=InformationPlatformResponse)
def update_platform(platform_id: UUID, data: dict, db: Session = Depends(get_db)):
    platform = crud.get_platform(db, platform_id=platform_id)
    if not platform:
        raise HTTPException(status_code=404, detail="Platform not found")
    return crud.update_platform(db=db, platform_id=platform_id, data=data)