"""Image endpoints — serve generated images.

GET /api/images/{id} returns the image binary (PNG/WebP).
GET /api/images/{id}/info returns its metadata as JSON.

Image files live in ``backend/runtime/outputs/`` (gitignored).
The DB stores ``file_path`` as a path **relative to that directory** so
moving the runtime folder doesn't break references.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from backend.storage.db import get_session
from backend.storage.models import Image

router = APIRouter()


_OUTPUTS_DIR = Path(__file__).resolve().parent.parent / "runtime" / "outputs"


def _resolve(image: Image) -> Path:
    """Map a stored relative path to an absolute path, guarding against traversal."""
    # file_path is always relative to outputs dir.
    candidate = (_OUTPUTS_DIR / image.file_path).resolve()
    if not str(candidate).startswith(str(_OUTPUTS_DIR.resolve())):
        raise HTTPException(status_code=400, detail="Invalid image path")
    if not candidate.exists():
        raise HTTPException(status_code=404, detail="Image file missing on disk")
    return candidate


@router.get("/images/{image_id}")
def get_image(image_id: str, session: Session = Depends(get_session)):
    img = session.get(Image, image_id)
    if not img:
        raise HTTPException(status_code=404, detail="Image not found")
    path = _resolve(img)
    return FileResponse(path, media_type="image/png", filename=path.name)


@router.get("/images/{image_id}/info")
def get_image_info(image_id: str, session: Session = Depends(get_session)) -> dict:
    img = session.get(Image, image_id)
    if not img:
        raise HTTPException(status_code=404, detail="Image not found")
    return {
        "id": img.id,
        "job_id": img.job_id,
        "file_path": img.file_path,
        "width": img.width,
        "height": img.height,
        "seed": img.seed,
        "created_at": img.created_at.isoformat(),
        "url": f"/api/images/{img.id}",
    }