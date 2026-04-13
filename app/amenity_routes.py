from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from .database import get_db
from .models import Amenity
from pydantic import BaseModel
from typing import List, Optional
import json

router = APIRouter(prefix="/api/amenities", tags=["amenities"])

class AmenitySchema(BaseModel):
    id: Optional[int] = None
    name: str
    icon: str
    image_url: str
    description: str
    features: str  # store as JSON string in DB

    class Config:
        orm_mode = True

@router.get("/", response_model=List[AmenitySchema])
def get_all(db: Session = Depends(get_db)):
    return db.query(Amenity).all()

@router.get("/{id}", response_model=AmenitySchema)
def get_one(id: int, db: Session = Depends(get_db)):
    item = db.query(Amenity).filter(Amenity.id == id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Not found")
    return item

@router.post("/")
def create(data: AmenitySchema, db: Session = Depends(get_db)):
    amenity = Amenity(**data.dict(exclude={"id"}))
    db.add(amenity)
    db.commit()
    db.refresh(amenity)
    return amenity

@router.put("/{id}")
def update(id: int, data: AmenitySchema, db: Session = Depends(get_db)):
    item = db.query(Amenity).filter(Amenity.id == id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Not found")
    for key, val in data.dict(exclude={"id"}).items():
        setattr(item, key, val)
    db.commit()
    return item

@router.delete("/{id}")
def delete(id: int, db: Session = Depends(get_db)):
    item = db.query(Amenity).filter(Amenity.id == id).first()
    db.delete(item)
    db.commit()
    return {"status": "deleted"}