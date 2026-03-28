from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.notification import Notification

router = APIRouter(prefix="/api/notifications", tags=["notifications"], dependencies=[Depends(get_current_user)])


@router.get("/")
def list_notifications(
    unread_only: bool = False,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    query = db.query(Notification)
    if unread_only:
        query = query.filter(Notification.is_read == False)
    notifications = query.order_by(Notification.created_at.desc()).limit(limit).all()
    return [
        {
            "id": n.id,
            "title": n.title,
            "message": n.message,
            "type": n.notification_type,
            "is_read": n.is_read,
            "created_at": str(n.created_at),
        }
        for n in notifications
    ]


@router.get("/unread-count")
def unread_count(db: Session = Depends(get_db)):
    count = db.query(Notification).filter(Notification.is_read == False).count()
    return {"count": count}


@router.put("/{notification_id}/read")
def mark_as_read(notification_id: int, db: Session = Depends(get_db)):
    notification = db.query(Notification).filter(Notification.id == notification_id).first()
    if notification:
        notification.is_read = True
        db.commit()
    return {"ok": True}


@router.put("/read-all")
def mark_all_as_read(db: Session = Depends(get_db)):
    db.query(Notification).filter(Notification.is_read == False).update(
        {Notification.is_read: True}
    )
    db.commit()
    return {"ok": True}
