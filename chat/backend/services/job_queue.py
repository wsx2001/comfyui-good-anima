"""Serial queue worker — runs JobQueues one item at a time.

Design (TECH §5.5, revised for M1):

  * One asyncio.Task per active queue (``_workers[queue_id]``).
  * The worker re-reads queue/item state from SQLite between items, so
    pause/resume/cancel issued by HTTP endpoints take effect without any
    in-memory signalling. Pause lands between items; the in-flight job
    always runs to completion.
  * Each item becomes a Job via ``job_service.create_and_submit``; the
    worker blocks on ``wait_for_job`` then snapshots the final state.
  * Failure policy: mark the item failed and continue with the next one
    (AC-10.x "默认失败继续下一个"). Queue-level abort happens only on
    explicit cancel.
  * Every finished item appends a Message row to the conversation, so the
    generated image lands in the chat flow and survives page reloads.
  * SSE subscribers (JobQueuePanel) receive live events through in-process
    asyncio queues; a full snapshot is sent on subscribe so late joiners
    catch up.

Restart policy (M1): workers do NOT auto-resume after a process restart.
``app.lifespan`` calls :func:`recover_stale_queues` which marks orphaned
active queues as failed and their pending items as skipped.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from backend.services import job_service
from backend.skills.workflow_injector import get_injector
from backend.storage.db import get_engine
from backend.storage.models import Conversation, JobQueue, JobQueueItem, Message
from backend.utils.id_gen import new_id
from backend.utils.log import get_logger

logger = get_logger()

MAX_ITEMS = 50
PAUSE_POLL_INTERVAL = 0.5  # seconds between state checks while paused

# Sane defaults when an item omits sizing args (Anima portrait standard).
DEFAULT_ITEM_ARGS: dict[str, Any] = {"width": 832, "height": 1216, "steps": 28}

QUEUE_ACTIVE_STATES = ("pending", "running", "paused")
QUEUE_TERMINAL_STATES = ("completed", "cancelled", "failed")

# ---------------------------------------------------------------------------
# Event bus (SSE fan-out)
# ---------------------------------------------------------------------------

_subscribers: dict[str, set[asyncio.Queue]] = {}
_workers: dict[str, asyncio.Task] = {}


def subscribe(queue_id: str) -> asyncio.Queue:
    """Register an SSE subscriber for a queue's live events."""
    sub: asyncio.Queue = asyncio.Queue(maxsize=256)
    _subscribers.setdefault(queue_id, set()).add(sub)
    return sub


def unsubscribe(queue_id: str, sub: asyncio.Queue) -> None:
    _subscribers.get(queue_id, set()).discard(sub)


def _publish(queue_id: str, event: str, data: dict) -> None:
    for sub in _subscribers.get(queue_id, set()):
        try:
            sub.put_nowait({"event": event, "data": data})
        except asyncio.QueueFull:  # pragma: no cover — slow client
            pass


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _get_queue_row(queue_id: str) -> Optional[JobQueue]:
    with Session(get_engine()) as session:
        return session.get(JobQueue, queue_id)


def _set_queue_state(queue_id: str, state: str) -> None:
    with Session(get_engine()) as session:
        q = session.get(JobQueue, queue_id)
        if not q:
            return
        q.state = state
        if state in QUEUE_TERMINAL_STATES and not q.finished_at:
            q.finished_at = datetime.utcnow()
        session.add(q)
        session.commit()


def _finalize_queue(queue_id: str, state: str) -> None:
    _set_queue_state(queue_id, state)


def _next_pending_item(queue_id: str) -> Optional[JobQueueItem]:
    with Session(get_engine()) as session:
        return session.exec(
            select(JobQueueItem)
            .where(JobQueueItem.queue_id == queue_id)
            .where(JobQueueItem.state == "pending")
            .order_by(JobQueueItem.order_index.asc())
        ).first()


def _mark_item(
    item_id: str,
    state: Optional[str] = None,
    job_id: Optional[str] = None,
    error: Optional[str] = None,
    finished: bool = False,
) -> None:
    with Session(get_engine()) as session:
        it = session.get(JobQueueItem, item_id)
        if not it:
            return
        if state:
            it.state = state
        if job_id:
            it.job_id = job_id
        if error is not None:
            it.error = error[:300]
        if finished:
            it.finished_at = datetime.utcnow()
        session.add(it)
        session.commit()


def _skip_remaining(queue_id: str, reason: str) -> None:
    with Session(get_engine()) as session:
        rows = session.exec(
            select(JobQueueItem)
            .where(JobQueueItem.queue_id == queue_id)
            .where(JobQueueItem.state == "pending")
        ).all()
        for it in rows:
            it.state = "skipped"
            it.error = reason[:300]
            it.finished_at = datetime.utcnow()
            session.add(it)
        session.commit()


def _get_job_error(job_id: str) -> Optional[str]:
    from backend.storage.models import Job

    with Session(get_engine()) as session:
        job = session.get(Job, job_id)
        return job.error if job else None


# ---------------------------------------------------------------------------
# Args assembly
# ---------------------------------------------------------------------------


def _sanitize_prefix(s: str) -> str:
    cleaned = "".join(ch for ch in s if ch.isalnum() or ch in "_-")
    return cleaned[:48] or "qimg"


def _build_item_args(queue_id: str, item: JobQueueItem) -> dict:
    """Merge item.args JSON over defaults and inject the prompts."""
    try:
        raw = json.loads(item.args) if item.args else {}
    except Exception:
        raw = {}
    args = dict(DEFAULT_ITEM_ARGS)
    args.update({k: v for k, v in (raw or {}).items() if v is not None})
    args["prompt_11"] = item.prompt_11
    args["prompt_12"] = item.prompt_12
    if not args.get("filename_prefix"):
        args["filename_prefix"] = _sanitize_prefix(
            f"q{queue_id[-6:]}_{item.order_index}_{item.id[-4:]}"
        )
    return args


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------


async def create_queue(
    conversation_id: str,
    workflow_id: str,
    title: str,
    items: list[dict],
) -> tuple[Optional[str], Optional[str]]:
    """Create a JobQueue + items and start its worker.

    Returns ``(queue_id, None)`` or ``(None, error_message)``. All items are
    pre-validated (injector gate) before anything hits the DB so the LLM
    gets one precise error instead of a partially-started queue.
    """
    with Session(get_engine()) as session:
        if not session.get(Conversation, conversation_id):
            return None, "会话不存在"
    if not items:
        return None, "items 为空"
    if len(items) > MAX_ITEMS:
        return None, f"items 最多 {MAX_ITEMS} 项"

    injector = get_injector(workflow_id)
    now = datetime.utcnow()
    queue_id = new_id()

    prepared: list[tuple[JobQueueItem, dict]] = []
    for idx, it in enumerate(items):
        if not isinstance(it, dict):
            return None, f"items[{idx}] 必须是对象"
        p11 = str(it.get("prompt_11") or "").strip()
        p12 = str(it.get("prompt_12") or "").strip()
        if not p11 or not p12:
            return None, f"items[{idx}] 缺少 prompt_11/prompt_12"
        scene_label = it.get("scene_label")
        item = JobQueueItem(
            id=new_id(),
            queue_id=queue_id,
            order_index=idx,
            scene_label=str(scene_label)[:64] if scene_label else None,
            prompt_11=p11[:4000],
            prompt_12=p12[:2000],
            args=json.dumps(it.get("args") or {}, ensure_ascii=False),
            state="pending",
            job_id=None,
            error=None,
            created_at=now,
            finished_at=None,
        )
        merged = _build_item_args(queue_id, item)
        normalized, err = await injector.validate(merged)
        if err or normalized is None:
            return None, f"items[{idx}] 参数校验失败：{err}"
        prepared.append((item, merged))

    with Session(get_engine()) as session:
        session.add(
            JobQueue(
                id=queue_id,
                conversation_id=conversation_id,
                workflow_id=injector.workflow_id,
                state="pending",
                title=title,
                created_at=now,
                finished_at=None,
            )
        )
        for item, _ in prepared:
            session.add(item)
        conv = session.get(Conversation, conversation_id)
        if conv:
            conv.updated_at = now
            session.add(conv)
        session.commit()

    start_worker(queue_id)
    logger.info("queue {} created ({} items, workflow={})", queue_id, len(prepared), injector.workflow_id)
    return queue_id, None


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


def start_worker(queue_id: str) -> bool:
    """Start the worker task for a queue (idempotent)."""
    task = _workers.get(queue_id)
    if task and not task.done():
        return False
    _workers[queue_id] = asyncio.create_task(_run_queue(queue_id))
    return True


async def _run_queue(queue_id: str) -> None:
    try:
        await _queue_loop(queue_id)
    except Exception:
        logger.exception("queue {} worker crashed", queue_id)
        _fail_queue(queue_id, "队列内部错误")
    finally:
        _workers.pop(queue_id, None)


async def _queue_loop(queue_id: str) -> None:
    # Only flip pending -> running; a pause that landed between create_queue
    # and this first tick must survive.
    current = _get_queue_row(queue_id)
    if current and current.state == "pending":
        _set_queue_state(queue_id, "running")
        _publish(queue_id, "queue.state", {"state": "running"})

    while True:
        q = _get_queue_row(queue_id)
        if q is None:
            return
        if q.state == "cancelled":
            _skip_remaining(queue_id, "队列已取消")
            _finalize_queue(queue_id, "cancelled")
            _publish(queue_id, "queue.end", {"state": "cancelled"})
            return
        if q.state in ("completed", "failed"):
            return
        if q.state == "paused":
            await asyncio.sleep(PAUSE_POLL_INTERVAL)
            continue

        item = _next_pending_item(queue_id)
        if item is None:
            # Re-check before finalising: a pause that landed while the last
            # item was running must win over 'completed', otherwise resume
            # would find a finished queue. Keep looping until resumed.
            q = _get_queue_row(queue_id)
            if q and q.state == "paused":
                await asyncio.sleep(PAUSE_POLL_INTERVAL)
                continue
            _finalize_queue(queue_id, "completed")
            _publish(queue_id, "queue.end", {"state": "completed"})
            return

        await _run_item(q, item)


async def _run_item(q: JobQueue, item: JobQueueItem) -> None:
    """Execute one queue item end-to-end."""
    _mark_item(item.id, state="running")
    _publish(
        q.id,
        "item.start",
        {"item_id": item.id, "order_index": item.order_index, "scene_label": item.scene_label},
    )

    args = _build_item_args(q.id, item)
    job, err = await job_service.create_and_submit(
        conversation_id=q.conversation_id,
        message_id=None,
        workflow_id=q.workflow_id,
        args=args,
        queue_item_id=item.id,
        source="queue",
    )
    # The queue may have been cancelled while we were submitting.
    q_now = _get_queue_row(q.id)
    if q_now and q_now.state == "cancelled":
        if job is not None:
            await job_service.cancel_job(job.id)  # also interrupts ComfyUI
        return  # cancel_queue's cleanup owns the item rows from here

    if err or job is None:
        _mark_item(item.id, state="failed", error=err or "提交失败", finished=True)
        _publish(
            q.id,
            "item.done",
            {
                "item_id": item.id,
                "order_index": item.order_index,
                "scene_label": item.scene_label,
                "state": "failed",
                "job_id": None,
                "message_id": None,
                "images": [],
                "error": err or "提交失败",
            },
        )
        return

    _mark_item(item.id, job_id=job.id)
    await job_service.wait_for_job(job.id)
    final_state, images = job_service.job_snapshot(job.id)

    # A cancel that landed mid-job already owns this item's terminal state;
    # don't resurrect it with a post-cancel write.
    q_now = _get_queue_row(q.id)
    if q_now and q_now.state == "cancelled":
        return

    label = f"「{item.scene_label}」" if item.scene_label else ""
    if final_state == "succeeded":
        _mark_item(item.id, state="done", finished=True)
        message_id = _persist_item_message(
            conversation_id=q.conversation_id,
            job_id=job.id,
            content=f"🎬 场景{label}完成，共 {len(images)} 张图。",
        )
        _publish(
            q.id,
            "item.done",
            {
                "item_id": item.id,
                "order_index": item.order_index,
                "scene_label": item.scene_label,
                "state": "done",
                "job_id": job.id,
                "message_id": message_id,
                "images": images,
                "error": None,
            },
        )
    elif final_state == "cancelled":
        _mark_item(item.id, state="skipped", error="已取消", finished=True)
        _publish(
            q.id,
            "item.done",
            {
                "item_id": item.id,
                "order_index": item.order_index,
                "scene_label": item.scene_label,
                "state": "skipped",
                "job_id": job.id,
                "message_id": None,
                "images": [],
                "error": "已取消",
            },
        )
    else:
        errmsg = _get_job_error(job.id) or f"生图失败（{final_state}）"
        _mark_item(item.id, state="failed", error=errmsg, finished=True)
        message_id = _persist_item_message(
            conversation_id=q.conversation_id,
            job_id=job.id,
            content=f"⚠️ 场景{label}失败：{errmsg}",
        )
        _publish(
            q.id,
            "item.done",
            {
                "item_id": item.id,
                "order_index": item.order_index,
                "scene_label": item.scene_label,
                "state": "failed",
                "job_id": job.id,
                "message_id": message_id,
                "images": [],
                "error": errmsg,
            },
        )


def _persist_item_message(conversation_id: str, job_id: str, content: str) -> str:
    """Append an assistant message summarising a finished item."""
    now = datetime.utcnow()
    with Session(get_engine()) as session:
        msg = Message(
            id=new_id(),
            conversation_id=conversation_id,
            role="assistant",
            content=content,
            reasoning=None,
            job_id=job_id,
            created_at=now,
        )
        session.add(msg)
        conv = session.get(Conversation, conversation_id)
        if conv:
            conv.updated_at = now
            session.add(conv)
        session.commit()
        return msg.id


def _fail_queue(queue_id: str, reason: str) -> None:
    """Mark a crashed queue failed and skip whatever is left."""
    with Session(get_engine()) as session:
        q = session.get(JobQueue, queue_id)
        if q and q.state not in QUEUE_TERMINAL_STATES:
            q.state = "failed"
            q.finished_at = datetime.utcnow()
            session.add(q)
        rows = session.exec(
            select(JobQueueItem)
            .where(JobQueueItem.queue_id == queue_id)
            .where(JobQueueItem.state.in_(["pending", "running"]))
        ).all()
        for it in rows:
            it.state = "skipped" if it.state == "pending" else "failed"
            it.error = reason[:300]
            it.finished_at = datetime.utcnow()
            session.add(it)
        session.commit()
    _publish(queue_id, "queue.end", {"state": "failed"})


# ---------------------------------------------------------------------------
# Control operations (called by API endpoints)
# ---------------------------------------------------------------------------


def pause_queue(queue_id: str) -> tuple[bool, Optional[str]]:
    q = _get_queue_row(queue_id)
    if not q:
        return False, "队列不存在"
    if q.state not in ("pending", "running"):
        return False, f"队列状态为 {q.state}，无法暂停"
    _set_queue_state(queue_id, "paused")
    _publish(queue_id, "queue.state", {"state": "paused"})
    return True, None


def resume_queue(queue_id: str) -> tuple[bool, Optional[str]]:
    q = _get_queue_row(queue_id)
    if not q:
        return False, "队列不存在"
    if q.state != "paused":
        return False, f"队列状态为 {q.state}，无法恢复"
    _set_queue_state(queue_id, "running")
    _publish(queue_id, "queue.state", {"state": "running"})
    start_worker(queue_id)  # in case the task died while paused
    return True, None


async def cancel_queue(queue_id: str) -> tuple[bool, Optional[str]]:
    q = _get_queue_row(queue_id)
    if not q:
        return False, "队列不存在"
    if q.state in QUEUE_TERMINAL_STATES:
        return False, f"队列已结束（{q.state}），无法取消"

    # Collect jobs to interrupt BEFORE flipping state, then flip. The
    # worker's post-await cancelled-state checks keep it from overwriting
    # anything after this point.
    with Session(get_engine()) as session:
        running = session.exec(
            select(JobQueueItem)
            .where(JobQueueItem.queue_id == queue_id)
            .where(JobQueueItem.state == "running")
        ).all()
        job_ids = [it.job_id for it in running if it.job_id]

    _set_queue_state(queue_id, "cancelled")
    _publish(queue_id, "queue.state", {"state": "cancelled"})

    # Interrupt in-flight ComfyUI prompts (best-effort).
    for job_id in job_ids:
        await job_service.cancel_job(job_id)

    # Items whose job was never attached (submit still in flight) and all
    # pending items become skipped; running items WITH a job are finalised
    # by their worker via the cancelled-state check.
    with Session(get_engine()) as session:
        rows = session.exec(
            select(JobQueueItem).where(JobQueueItem.queue_id == queue_id)
        ).all()
        for it in rows:
            if it.state == "pending" or (it.state == "running" and not it.job_id):
                it.state = "skipped"
                it.error = "队列已取消"
                it.finished_at = datetime.utcnow()
                session.add(it)
            elif it.state == "running":
                it.state = "skipped"
                it.error = "已取消"
                it.finished_at = datetime.utcnow()
                session.add(it)
        session.commit()
    return True, None


async def append_item(
    queue_id: str,
    scene_label: Optional[str],
    prompt_11: str,
    prompt_12: str,
    extra_args: dict,
) -> tuple[Optional[dict], Optional[str]]:
    """Append one pending item to an active queue."""
    q = _get_queue_row(queue_id)
    if not q:
        return None, "队列不存在"
    if q.state not in QUEUE_ACTIVE_STATES:
        return None, f"队列已结束（{q.state}），不能追加；请新建队列"

    p11 = (prompt_11 or "").strip()
    p12 = (prompt_12 or "").strip()
    if not p11 or not p12:
        return None, "缺少 prompt_11/prompt_12"

    injector = get_injector(q.workflow_id)
    now = datetime.utcnow()
    item = JobQueueItem(
        id=new_id(),
        queue_id=queue_id,
        order_index=0,  # fixed below
        scene_label=str(scene_label)[:64] if scene_label else None,
        prompt_11=p11[:4000],
        prompt_12=p12[:2000],
        args=json.dumps(extra_args or {}, ensure_ascii=False),
        state="pending",
        job_id=None,
        error=None,
        created_at=now,
        finished_at=None,
    )

    with Session(get_engine()) as session:
        count = len(
            session.exec(
                select(JobQueueItem).where(JobQueueItem.queue_id == queue_id)
            ).all()
        )
        if count >= MAX_ITEMS:
            return None, f"队列最多 {MAX_ITEMS} 项"
        last = session.exec(
            select(JobQueueItem)
            .where(JobQueueItem.queue_id == queue_id)
            .order_by(JobQueueItem.order_index.desc())
        ).first()
        item.order_index = (last.order_index + 1) if last else 0

        merged = _build_item_args(queue_id, item)
        normalized, err = await injector.validate(merged)
        if err or normalized is None:
            return None, f"参数校验失败：{err}"

        session.add(item)
        session.commit()
        session.refresh(item)

    _publish(queue_id, "queue.updated", {"reason": "item_appended", "item_id": item.id})
    logger.info("item {} appended to queue {}", item.id, queue_id)
    return {
        "id": item.id,
        "order_index": item.order_index,
        "scene_label": item.scene_label,
        "state": item.state,
    }, None


# ---------------------------------------------------------------------------
# Restart recovery
# ---------------------------------------------------------------------------


def recover_stale_queues() -> int:
    """On startup, fail queues left active by a previous process.

    M1 does not auto-resume queues (TECH §5.7): workers are in-process
    tasks, so anything still 'running' belongs to a dead process.
    """
    with Session(get_engine()) as session:
        rows = session.exec(
            select(JobQueue).where(JobQueue.state.in_(QUEUE_ACTIVE_STATES))
        ).all()
        ids = [q.id for q in rows]

    for queue_id in ids:
        _skip_remaining(queue_id, "服务重启，队列未续跑")
        with Session(get_engine()) as session:
            q = session.get(JobQueue, queue_id)
            if q:
                q.state = "failed"
                q.finished_at = datetime.utcnow()
                session.add(q)
                session.commit()
    if ids:
        logger.warning("marked {} stale queue(s) as failed after restart", len(ids))
    return len(ids)
