"""Job service — create, submit, poll, cancel ComfyUI jobs.

Polling design (revised from the original watchdog plan):

  We know the ``prompt_id`` at submit time, so instead of watching the
  output directory for files we poll ``GET /history/{prompt_id}`` every
  ~2s per running job. This is exact (no filename matching races), needs
  no extra dependency, and images download straight from ``/view``.

Each RUNNING job gets one asyncio task that:
  polls → on completion: downloads outputs, inserts Image rows, marks
  SUCCEEDED/FAILED, and fires any waiters registered via ``wait_for_job``.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlmodel import Session, select

from backend.config.loader import get_config
from backend.skills.base import JobState
from backend.skills.comfyui import (
    ComfySkillError,
    cancel_prompt,
    download_image,
    poll_history,
)
from backend.skills.workflow_injector import get_injector
from backend.storage.db import get_engine
from backend.storage.models import Image, Job
from backend.utils.id_gen import new_id
from backend.utils.log import get_logger

logger = get_logger()

POLL_INTERVAL = 2.0
MAX_POLLS = 600  # 20 minutes hard cap

_args_dir_cache: Optional[Path] = None


def _outputs_dir() -> Path:
    root = Path(__file__).resolve().parent.parent / "runtime" / "outputs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _args_dir() -> Path:
    """Lazily create + return the args staging directory.

    NOTE: the cache variable must NOT share its name with this function —
    a same-named global would be rebound by ``def`` before the sentinel
    check ever runs, making the function return itself.
    """
    global _args_dir_cache
    if _args_dir_cache is None:
        _args_dir_cache = Path(__file__).resolve().parent.parent / "runtime" / "args"
        _args_dir_cache.mkdir(parents=True, exist_ok=True)
    return _args_dir_cache


# ---------------------------------------------------------------------------
# Creation + submission
# ---------------------------------------------------------------------------


async def create_and_submit(
    conversation_id: str,
    message_id: str | None,
    workflow_id: str,
    args: dict,
    queue_item_id: str | None = None,
    source: str = "single",
) -> tuple[Optional[Job], Optional[str]]:
    """Validate args, insert a Job row, and submit to ComfyUI.

    Returns ``(job, None)`` on success or ``(None, error_message)`` when
    validation or submission fails (error_message is LLM-readable Chinese).
    """
    injector = get_injector(workflow_id)
    normalized, err = await injector.validate(args)
    if err or normalized is None:
        return None, err

    job = Job(
        id=new_id(),
        conversation_id=conversation_id,
        message_id=message_id,
        queue_item_id=queue_item_id,
        prompt_id=None,
        workflow_id=injector.workflow_id,
        injector_mode=injector.mode,
        args_snapshot=json.dumps(normalized, ensure_ascii=False),
        state=JobState.PENDING.value,
        error=None,
        source=source,
        created_at=datetime.utcnow(),
        finished_at=None,
    )
    with Session(get_engine()) as session:
        session.add(job)
        session.commit()
        session.refresh(job)

    try:
        prompt_id, args_file = await injector.submit(normalized, _args_dir())
    except ComfySkillError as exc:
        _mark(job.id, JobState.FAILED, f"{exc.code}: {exc.message}")
        return None, f"提交失败：{exc.message}"

    _mark(job.id, JobState.RUNNING, None, prompt_id=prompt_id)

    # Fire-and-forget poller; it owns this job until a terminal state.
    asyncio.create_task(_poll_loop(job.id, prompt_id))
    logger.info("job {} submitted (prompt_id={})", job.id, prompt_id)

    with Session(get_engine()) as session:
        refreshed = session.get(Job, job.id)
        return refreshed, None


def _mark(
    job_id: str,
    state: JobState,
    error: str | None,
    prompt_id: str | None = None,
) -> None:
    with Session(get_engine()) as session:
        job = session.get(Job, job_id)
        if not job:
            return
        job.state = state.value
        if error is not None:
            job.error = error[:500]
        elif state == JobState.SUCCEEDED:
            job.error = None
        if prompt_id:
            job.prompt_id = prompt_id
        if state in (JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED):
            job.finished_at = datetime.utcnow()
        session.add(job)
        session.commit()
    # Any terminal state releases waiters (chat_service blocks on this).
    if state in (JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED):
        _notify_waiters(job_id)


# ---------------------------------------------------------------------------
# Poll loop
# ---------------------------------------------------------------------------


async def _poll_loop(job_id: str, prompt_id: str) -> None:
    """Poll ComfyUI history until terminal state or cap."""
    for i in range(MAX_POLLS):
        # A cancel may have flipped the DB state while we slept.
        current = _get_state(job_id)
        if current in (JobState.CANCELLED.value, JobState.FAILED.value):
            return

        entry = await poll_history(prompt_id)
        if entry is not None:
            try:
                await _finalize_from_history(job_id, entry)
            except Exception:
                logger.exception("finalize failed for job {}", job_id)
                _mark(job_id, JobState.FAILED, "输出处理失败")
            return
        await asyncio.sleep(POLL_INTERVAL)

    _mark(job_id, JobState.FAILED, "轮询超时（20 分钟无结果）")


def _get_state(job_id: str) -> str | None:
    with Session(get_engine()) as session:
        job = session.get(Job, job_id)
        return job.state if job else None


async def _finalize_from_history(job_id: str, entry: dict) -> None:
    """Extract outputs from a /history entry, download them, mark the job."""
    status = entry.get("status") or {}
    completed = bool(status.get("status_str") == "success")

    outputs = entry.get("outputs") or {}
    saved_files: list[tuple[str, str]] = []  # (filename, subfolder)
    for _node_id, node_out in outputs.items():
        for img in node_out.get("images", []):
            saved_files.append((img.get("filename", ""), img.get("subfolder", "")))

    seed: int | None = None
    try:
        prompt_payload = (entry.get("prompt") or [None, None])[1] or {}
        for node_input in prompt_payload.values():
            if isinstance(node_input, dict) and isinstance(node_input.get("seed"), int):
                seed = node_input["seed"]
                break
    except Exception:
        pass

    width = height = 0
    args_snapshot: dict = {}
    with Session(get_engine()) as session:
        job = session.get(Job, job_id)
        if job:
            try:
                args_snapshot = json.loads(job.args_snapshot)
            except Exception:
                pass
            width = int(args_snapshot.get("width") or 0)
            height = int(args_snapshot.get("height") or 0)

    if completed and saved_files:
        prefix = args_snapshot.get("filename_prefix", "")
        for filename, subfolder in saved_files:
            if prefix and not Path(filename).stem.startswith(prefix):
                continue  # not ours — another job wrote into this batch window
            dest = _outputs_dir() / f"{job_id}_{filename}"
            try:
                await download_image(filename, subfolder, dest)
            except Exception as exc:
                logger.warning("download failed for {}: {}", filename, exc)
                continue
            rel = str(dest.relative_to(_outputs_dir()))
            with Session(get_engine()) as session:
                session.add(
                    Image(
                        id=new_id(),
                        job_id=job_id,
                        file_path=rel,
                        width=width,
                        height=height,
                        seed=seed,
                    )
                )
                session.commit()
        _mark(job_id, JobState.SUCCEEDED, None)
        logger.info("job {} succeeded with {} image(s)", job_id, len(saved_files))
    else:
        reason = "ComfyUI 执行失败" if not completed else "未找到输出文件"
        _mark(job_id, JobState.FAILED, reason)


# ---------------------------------------------------------------------------
# Waiting + cancellation + recovery
# ---------------------------------------------------------------------------

_waiters: dict[str, set[asyncio.Future]] = {}


async def wait_for_job(job_id: str, timeout: float = 1300) -> bool:
    """Await job completion. Returns True if reached SUCCEEDED."""
    fut: asyncio.Future = asyncio.get_event_loop().create_future()
    _waiters.setdefault(job_id, set()).add(fut)
    try:
        return await asyncio.wait_for(fut, timeout)
    except asyncio.TimeoutError:
        return False
    finally:
        _waiters.get(job_id, set()).discard(fut)


def _notify_waiters(job_id: str) -> None:
    for fut in _waiters.pop(job_id, set()):
        if not fut.done():
            fut.set_result(True)


def job_snapshot(job_id: str) -> tuple[str, list[dict]]:
    """Read final state + image rows for a finished job.

    Returns ``(state, images)`` where images carry API-ready URLs.
    Used by chat_service (single submits) and job_queue (queue items).
    """
    with Session(get_engine()) as session:
        job = session.get(Job, job_id)
        if not job:
            return "missing", []
        images = session.exec(select(Image).where(Image.job_id == job_id)).all()
        return job.state, [
            {
                "id": img.id,
                "url": f"/api/images/{img.id}",
                "width": img.width,
                "height": img.height,
                "seed": img.seed,
            }
            for img in images
        ]


def cancel_job(job_id: str) -> tuple[bool, str | None]:
    """Cancel a pending/running job. Returns (ok, error).

    Sync function — safe to call from threadpool endpoints and async code
    alike (the remote cancel is scheduled on the running loop when one
    exists, else fire-and-forget via a fresh task in a background thread
    is skipped; ComfyUI keeps processing but we mark CANCELLED locally).
    """
    with Session(get_engine()) as session:
        job = session.get(Job, job_id)
        if not job:
            return False, "Job 不存在"
        if job.state not in (JobState.PENDING.value, JobState.RUNNING.value):
            return False, f"Job 已处于终态 {job.state}，无法取消"
        prompt_id = job.prompt_id

    # Best-effort remote cancel (only when called from the event loop's
    # thread; from worker threads there is no loop to schedule on).
    if prompt_id:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            loop.create_task(cancel_prompt(prompt_id))
        else:
            logger.warning("cancel_job {} called off-loop; remote interrupt skipped", job_id)

    _mark(job_id, JobState.CANCELLED, None)
    _notify_waiters(job_id)
    return True, None


def recover_running_jobs() -> int:
    """On startup, resolve jobs stuck in PENDING/RUNNING from a prior run.

    Returns count recovered. Jobs whose prompt_id still exists in ComfyUI
    history are re-polled; others are marked failed.
    """
    with Session(get_engine()) as session:
        rows = session.exec(
            select(Job).where(Job.state.in_([JobState.PENDING.value, JobState.RUNNING.value]))
        ).all()

    revived = 0
    for job in rows:
        if job.prompt_id:
            asyncio.create_task(_poll_loop(job.id, job.prompt_id))
            revived += 1
        else:
            _mark(job.id, JobState.FAILED, "服务重启，任务从未提交成功")
    if revived:
        logger.info("recovered {} running job(s)", revived)
    return revived