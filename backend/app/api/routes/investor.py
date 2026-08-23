from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from app.api.deps import require_admin_investor
from app.database.connection import get_db
from app.models.investor import Investor
from app.schemas.investor import InvestorCreate, InvestorResponse, InvestorUpdate
from app.crud import investor as crud

router = APIRouter(prefix="/investors", tags=["investors"])

@router.post("/", response_model=InvestorResponse)
def create_investor(
    investor: InvestorCreate,
    db: Session = Depends(get_db),
    _admin: Investor = Depends(require_admin_investor),
):
    existing = crud.get_investor_by_email(db, email=investor.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    return crud.create_investor(db=db, investor=investor)

@router.get("/", response_model=list[InvestorResponse])
def get_investors(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    _admin: Investor = Depends(require_admin_investor),
):
    return crud.get_investors(db, skip=skip, limit=limit)

@router.get("/{investor_id}", response_model=InvestorResponse)
def get_investor(
    investor_id: UUID,
    db: Session = Depends(get_db),
    _admin: Investor = Depends(require_admin_investor),
):
    investor = crud.get_investor(db, investor_id=investor_id)
    if not investor:
        raise HTTPException(status_code=404, detail="Investor not found")
    return investor

@router.patch("/{investor_id}", response_model=InvestorResponse)
def update_investor(
    investor_id: UUID,
    data: InvestorUpdate,
    db: Session = Depends(get_db),
    _admin: Investor = Depends(require_admin_investor),
):
    investor = crud.get_investor(db, investor_id=investor_id)
    if not investor:
        raise HTTPException(status_code=404, detail="Investor not found")
    return crud.update_investor(
        db=db,
        investor_id=investor_id,
        data=data.model_dump(exclude_unset=True),
    )

@router.delete("/{investor_id}")
def delete_investor(
    investor_id: UUID,
    db: Session = Depends(get_db),
    _admin: Investor = Depends(require_admin_investor),
):
    investor = crud.get_investor(db, investor_id=investor_id)
    if not investor:
        raise HTTPException(status_code=404, detail="Investor not found")
    crud.delete_investor(db=db, investor_id=investor_id)
    return {"message": "Investor deleted successfully"}
