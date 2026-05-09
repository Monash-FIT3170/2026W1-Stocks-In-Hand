from sqlalchemy.orm import Session
from uuid import UUID
from app.models.alert import Alert
from app.schemas.alert import AlertCreate

def get_alert(db: Session, alert_id: UUID):
    return db.query(Alert).filter(Alert.id == alert_id).first()

def get_alerts_by_investor(db: Session, investor_id: UUID):
    return db.query(Alert).filter(Alert.investor_id == investor_id).all()

def create_alert(db: Session, alert: AlertCreate):
    db_alert = Alert(**alert.model_dump())
    db.add(db_alert)
    db.commit()
    db.refresh(db_alert)
    return db_alert

def update_alert(db: Session, alert_id: UUID, data: dict):
    db_alert = get_alert(db, alert_id)
    for key, value in data.items():
        setattr(db_alert, key, value)
    db.commit()
    db.refresh(db_alert)
    return db_alert

def delete_alert(db: Session, alert_id: UUID):
    db_alert = get_alert(db, alert_id)
    db.delete(db_alert)
    db.commit()