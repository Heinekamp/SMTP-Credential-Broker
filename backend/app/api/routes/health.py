from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db

router = APIRouter()


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    """A real capability check, not just process liveness (architecture.md
    §7) — this stage only has a database to check; Postfix/config-generation
    checks are added when those subsystems exist (Stage 4/6)."""
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}
