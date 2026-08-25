"""Job endpoints — Step 1 minimal (GET only).

Step 3 adds POST /api/jobs/{id}/cancel and GET /api/jobs/{id}/events (SSE).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from backend.storage.db import get_session
from backend.storage.models import Image, Job

router = APIRouter()


def _serialize(job: Job, images: list[Image]) -> dict:
    return {
        "id": job.id,
        "conversation_id": job.conversation_id,
        "message_id": job.message_id,
        "queue_item_id": job.queue_item_id,
        "prompt_id": job.prompt_id,
        "workflow_id": job.workflow_id,
        "injector_mode": job.injector_mode,
        "args_snapshot": job.args_snapshot,
        "state": job.state,
        "error": job.error,
        "source": job.source,
        "created_at": job.created_at.isoformat(),
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "images": [
            {
                "id": img.id,
                "file_path": img.file_path,
                "width": img.width,
                "height": img.height,
                "seed": img.seed,
            }
            for img in images
        ],
    }


@router.get("/jobs/{job_id}")
def get_job(job_id: str, session: Session = Depends(get_session)) -> dict:
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    images = session.exec(select(Image).where(Image.job_id == job_id)).all()
    return _serialize(job, images)


@router.post("/jobs/{job_id}/cancel")
async def cancel_job_endpoint(job_id: str) -> dict:
    """Cancel a pending/running job (PRD US-5).

    async so cancel_job runs on the event loop and can schedule the
    remote ComfyUI interrupt (a sync endpoint would run in a worker
    thread with no loop).
    """
    from backend.services.job_service import cancel_job

    ok, error = cancel_job(job_id)
    if not ok:
        raise HTTPException(status_code=400, detail=error or "无法取消")
    return {"ok": True, "state": "cancelled"}