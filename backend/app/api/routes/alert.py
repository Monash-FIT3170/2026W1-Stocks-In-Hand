from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from app.database.connection import get_db
from app.schemas.alert import AlertCreate, AlertResponse
from app.crud import alert as crud

router = APIRouter(prefix="/alerts", tags=["alerts"])

@router.post("/", response_model=AlertResponse)
def create_alert(alert: AlertCreate, db: Session = Depends(get_db)):
    return crud.create_alert(db=db, alert=alert)

@router.get("/investor/{investor_id}", response_model=list[AlertResponse])
def get_alerts_by_investor(investor_id: UUID, db: Session = Depends(get_db)):
    alerts = crud.get_alerts_by_investor(db, investor_id=investor_id)
    if not alerts:
        raise HTTPException(status_code=404, detail="No alerts found for this investor")
    return alerts

@router.get("/{alert_id}", response_model=AlertResponse)
def get_alert(alert_id: UUID, db: Session = Depends(get_db)):
    alert = crud.get_alert(db, alert_id=alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert

@router.patch("/{alert_id}", response_model=AlertResponse)
def update_alert(alert_id: UUID, data: dict, db: Session = Depends(get_db)):
    alert = crud.get_alert(db, alert_id=alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return crud.update_alert(db=db, alert_id=alert_id, data=data)

@router.delete("/{alert_id}")
def delete_alert(alert_id: UUID, db: Session = Depends(get_db)):
    alert = crud.get_alert(db, alert_id=alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    crud.delete_alert(db=db, alert_id=alert_id)
    return {"message": "Alert deleted successfully"}