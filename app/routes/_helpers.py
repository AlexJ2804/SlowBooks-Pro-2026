from typing import Type, TypeVar

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.database import Base

T = TypeVar("T", bound=Base)


def get_or_404(db: Session, model: Type[T], obj_id: int, name: str = None) -> T:
    obj = db.query(model).filter(model.id == obj_id).first()
    if not obj:
        label = name or model.__name__
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return obj


def require_class_id(db: Session, class_id) -> int:
    """Validate that a transaction request supplied a real class.

    Returns the class_id if valid. Raises HTTPException(400) with the spec
    message if missing, and HTTPException(400) with a different message if
    the id doesn't resolve to an existing class. Used by every user-driven
    transaction-creating route.
    """
    from app.models.classes import Class
    if class_id is None:
        raise HTTPException(
            status_code=400,
            detail="Class is required. Pick a class before saving.",
        )
    cls = db.query(Class).filter(Class.id == class_id).first()
    if cls is None:
        raise HTTPException(status_code=400, detail=f"Class {class_id} does not exist")
    return cls.id
