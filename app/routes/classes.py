# ============================================================================
# Classes — CRUD for the user-defined transaction-tagging buckets.
# Archive only (no DELETE) so historical transaction links never dangle.
# The system Uncategorized class is protected: rename and archive return 403.
# ============================================================================

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.classes import Class
from app.schemas.classes import ClassCreate, ClassUpdate, ClassResponse


router = APIRouter(prefix="/api/classes", tags=["classes"])


@router.get("", response_model=list[ClassResponse])
def list_classes(include_archived: bool = False, db: Session = Depends(get_db)):
    q = db.query(Class)
    if not include_archived:
        q = q.filter(Class.is_archived == False)  # noqa: E712
    return q.order_by(Class.is_system_default.desc(), Class.name).all()


@router.post("", response_model=ClassResponse, status_code=201)
def create_class(data: ClassCreate, db: Session = Depends(get_db)):
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Class name is required")
    existing = db.query(Class).filter(Class.name == name).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Class '{name}' already exists")
    cls = Class(name=name, is_archived=False, is_system_default=False)
    db.add(cls)
    db.commit()
    db.refresh(cls)
    return cls


@router.patch("/{class_id}", response_model=ClassResponse)
def update_class(class_id: int, data: ClassUpdate, db: Session = Depends(get_db)):
    cls = db.query(Class).filter(Class.id == class_id).first()
    if not cls:
        raise HTTPException(status_code=404, detail="Class not found")
    if cls.is_system_default:
        # System default ("Uncategorized") cannot be renamed or archived,
        # otherwise auto-generated transactions would have no fallback.
        raise HTTPException(
            status_code=403,
            detail="The system Uncategorized class cannot be renamed or archived.",
        )
    if data.name is not None:
        new_name = data.name.strip()
        if not new_name:
            raise HTTPException(status_code=400, detail="Class name is required")
        if new_name != cls.name:
            clash = db.query(Class).filter(Class.name == new_name, Class.id != class_id).first()
            if clash:
                raise HTTPException(status_code=400, detail=f"Class '{new_name}' already exists")
            cls.name = new_name
    if data.is_archived is not None:
        cls.is_archived = data.is_archived
    db.commit()
    db.refresh(cls)
    return cls
