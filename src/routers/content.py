from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import Session
from db import get_db
from models.content import Content
from schemas.content import ContentSchema

router = APIRouter(prefix="/content", tags=["Content"])

@router.get("/{key}")
def get_content(key: str, db: Session = get_db()):
    item = db.query(Content).filter(Content.key == key).first()
    if not item:
        raise HTTPException(404, "Not found")
    return item.value

@router.post("/")
def update_content(data: ContentSchema, db: Session = get_db()):
    item = db.query(Content).filter(Content.key == data.key).first()
    if not item:
        item = Content(key=data.key, value=data.value)
        db.add(item)
    else:
        item.value = data.value
    db.commit()
    return {"status": "ok"}
