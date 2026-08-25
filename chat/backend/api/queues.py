"""Queue endpoints — Step 4 full implementation.

  - POST /api/queues                  — create + start a serial queue
  - GET  /api/queues/{id}             — queue detail (items included)
  - GET  /api/queues/{id}/events      — SSE live events
  - POST /api/queues/{id}/pause       — pause between items
  - POST /api/queues/{id}/resume      — resume a paused queue
  - POST /api/queues/{id}/cancel      — cancel queue + in-flight job
  - POST /api/queues/{id}/items       — append one item to an active queue

SSE events:
  event: queue.state   data: {"state": "running|paused|cancelled"}
  event: item.start    data: {"item_id", "order_index", "scene_label"}
  event: item.done     data: {"item_id", "order_index", "scene_label",
                              "state", "job_id", "message_id", "images", "error"}
  event: queue.end     data: {"state": "completed|failed"}
  event: queue.updated data: {"reason": "item_appended", "item_id"}

On subscribe the client first receives one ``queue.snapshot`` with the
full current state, then live deltas. Heartbeat comments keep proxies
from buffering.
"""
from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from backend.storage.db import get_engine, get_session
from backend.storage.models import Conversation, JobQueue, JobQueueItem
from backend.utils.id_gen import new_id

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class QueueItemIn(BaseModel):
    scene_label: Optional[str] = None
    prompt_11: str
    prompt_12: str
    args: dict = Field(default_factory=dict)


class QueueCreate(BaseModel):
    conversation_id: str
    workflow_id: str = "local/anima-txt2img-aesthetic-lora"
    title: Optional[str] = None
    items: list[QueueItemIn]


class QueueItemAppend(BaseModel):
    scene_label: Optional[str] = None
    prompt_11: str
    prompt_12: str
    args: dict = Field(default_factory=dict)


class QueueItemOut(BaseModel):
    id: str
    order_index: int
    scene_label: Optional[str] = None
    prompt_11: str
    prompt_12: str
    args: str
    state: str
    job_id: Optional[str] = None
    error: Optional[str] = None


class QueueOut(BaseModel):
    id: str
    conversation_id: str
    workflow_id: str
    state: str
    title: Optional[str] = None
    created_at: str
    finished_at: Optional[str] = None
    items: list[QueueItemOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Serialisation helper
# ---------------------------------------------------------------------------


def _serialize(queue: JobQueue, items: list[JobQueueItem]) -> dict:
    return QueueOut(
        id=queue.id,
        conversation_id=queue.conversation_id,
        workflow_id=queue.workflow_id,
        state=queue.state,
        title=queue.title,
        created_at=queue.created_at.isoformat(),
        finished_at=queue.finished_at.isoformat() if queue.finished_at else None,
        items=[
            QueueItemOut(
                id=it.id,
                order_index=it.order_index,
                scene_label=it.scene_label,
                prompt_11=it.prompt_11,
                prompt_12=it.prompt_12,
                args=it.args,
                state=it.state,
                job_id=it.job_id,
                error=it.error,
            )
            for it in sorted(items, key=lambda x: x.order_index)
        ],
    ).model_dump()


def _load_queue(session: Session, queue_id: str) -> tuple[JobQueue, list[JobQueueItem]]:
    queue = session.get(JobQueue, queue_id)
    if not queue:
        raise HTTPException(status_code=404, detail="Queue not found")
    items = session.exec(
        select(JobQueueItem)
        .where(JobQueueItem.queue_id == queue_id)
        .order_by(JobQueueItem.order_index.asc())
    ).all()
    return queue, items


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/queues", status_code=201)
async def create_queue(body: QueueCreate) -> dict:
    """Create a queue and immediately start its worker (US-10)."""
    from backend.services import job_queue as qsvc

    conv_exists = False
    with Session(get_engine()) as session:
        conv_exists = session.get(Conversation, body.conversation_id) is not None
    if not conv_exists:
        raise HTTPException(status_code=404, detail="Conversation not found")

    queue_id, err = await qsvc.create_queue(
        conversation_id=body.conversation_id,
        workflow_id=body.workflow_id,
        title=(body.title or "场景队列")[:64],
        items=[it.model_dump() for it in body.items],
    )
    if err or queue_id is None:
        raise HTTPException(status_code=400, detail=err or "创建失败")
    return {"id": queue_id, "state": "running", "item_count": len(body.items)}


@router.get("/queues/{queue_id}")
def get_queue(
    queue_id: str,
    session: Session = Depends(get_session),
) -> dict:
    queue, items = _load_queue(session, queue_id)
    return _serialize(queue, items)


@router.get("/conversations/{conv_id}/queue")
def get_latest_queue_for_conversation(
    conv_id: str,
    session: Session = Depends(get_session),
) -> dict:
    """Most recent queue in a conversation (panel restore after reload).

    Returns 204-style ``{"queue": null}`` when the conversation has none.
    """
    conv = session.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    latest = session.exec(
        select(JobQueue)
        .where(JobQueue.conversation_id == conv_id)
        .order_by(JobQueue.created_at.desc())
    ).first()
    if not latest:
        return {"queue": None}
    items = session.exec(
        select(JobQueueItem)
        .where(JobQueueItem.queue_id == latest.id)
        .order_by(JobQueueItem.order_index.asc())
    ).all()
    return {"queue": _serialize(latest, items)}


@router.get("/queues/{queue_id}/events")
async def queue_events(queue_id: str) -> StreamingResponse:
    """SSE stream of live queue events (JobQueuePanel)."""
    from backend.services import job_queue as qsvc

    # Validate existence before opening the stream.
    q = qsvc._get_queue_row(queue_id)
    if q is None:
        raise HTTPException(status_code=404, detail="Queue not found")

    async def event_generator() -> AsyncIterator[bytes]:
        sub = qsvc.subscribe(queue_id)

        def sse(event: str, data: dict) -> bytes:
            from backend.llm.response_parser import sse_format

            return sse_format(event, data).encode("utf-8")

        try:
            # Snapshot first so late joiners render the full board.
            with Session(get_engine()) as session:
                queue, items = _load_queue(session, queue_id)
            yield sse("queue.snapshot", _serialize(queue, items))

            # Terminal queue: nothing more will ever arrive — send one
            # heartbeat so clients settle, then close immediately.
            if queue.state in ("completed", "cancelled", "failed"):
                yield b": queue already finished\n\n"
                return

            while True:
                try:
                    msg = await asyncio.wait_for(sub.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield b": heartbeat\n\n"  # keep intermediaries from closing
                    continue
                yield sse(msg["event"], msg["data"])

                # After a terminal event, flush any trailing messages briefly
                # and close so the client stops holding the connection.
                if msg["event"] == "queue.end":
                    drain_deadline = asyncio.get_event_loop().time() + 1.0
                    while asyncio.get_event_loop().time() < drain_deadline:
                        try:
                            msg2 = await asyncio.wait_for(sub.get(), timeout=0.2)
                            yield sse(msg2["event"], msg2["data"])
                        except asyncio.TimeoutError:
                            break
                    break
        finally:
            qsvc.unsubscribe(queue_id, sub)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/queues/{queue_id}/pause")
def pause_queue_endpoint(queue_id: str) -> dict:
    from backend.services import job_queue as qsvc

    ok, err = qsvc.pause_queue(queue_id)
    if not ok:
        raise HTTPException(status_code=400, detail=err or "无法暂停")
    return {"ok": True, "state": "paused"}


@router.post("/queues/{queue_id}/resume")
def resume_queue_endpoint(queue_id: str) -> dict:
    from backend.services import job_queue as qsvc

    ok, err = qsvc.resume_queue(queue_id)
    if not ok:
        raise HTTPException(status_code=400, detail=err or "无法恢复")
    return {"ok": True, "state": "running"}


@router.post("/queues/{queue_id}/cancel")
async def cancel_queue_endpoint(queue_id: str) -> dict:
    from backend.services import job_queue as qsvc

    ok, err = await qsvc.cancel_queue(queue_id)
    if not ok:
        raise HTTPException(status_code=400, detail=err or "无法取消")
    return {"ok": True, "state": "cancelled"}


@router.post("/queues/{queue_id}/items", status_code=201)
async def append_item_endpoint(queue_id: str, body: QueueItemAppend) -> dict:
    from backend.services import job_queue as qsvc

    item, err = await qsvc.append_item(
        queue_id=queue_id,
        scene_label=body.scene_label,
        prompt_11=body.prompt_11,
        prompt_12=body.prompt_12,
        extra_args=body.args,
    )
    if err or item is None:
        raise HTTPException(status_code=400, detail=err or "追加失败")
    return {"ok": True, "item": item}
