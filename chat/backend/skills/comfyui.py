"""comfyui-skill CLI wrapper.

All ComfyUI interaction goes through the ``comfyui-skill`` command (via
``run_workflow_args.js`` for workflow execution), never direct HTTP. This
keeps us decoupled from ComfyUI's internal API surface.

Commands used in M1 Step 3:
  - submit:   node run_workflow_args.js submit <workflow_id> <args.json>
  - status:   comfyui-skill queue status --json        (poll prompt_id state)
  - fetch:    comfyui-skill image view <filename>       (download output)
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

from backend.config.loader import get_config
from backend.utils.log import get_logger

logger = get_logger()


class ComfySkillError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _workspace() -> Path:
    ws = get_config().comfyui.workspace
    if not ws:
        raise ComfySkillError("no_workspace", "comfyui.workspace 未配置，请在设置页填写")
    p = Path(ws)
    if not p.exists():
        raise ComfySkillError(
            "workspace_missing", f"workspace 目录不存在：{p}"
        )
    return p


async def _run_node(args_file: Path, mode: str, workflow_id: str) -> dict:
    """Run ``node run_workflow_args.js <mode> <workflow_id> <args.json>``.

    Returns parsed JSON stdout. Raises ComfySkillError on failure.
    """
    ws = _workspace()
    script = ws / "run_workflow_args.js"
    if not script.exists():
        raise ComfySkillError(
            "script_missing", f"找不到 {script}——请确认 v2mini 已安装"
        )

    proc = await asyncio.create_subprocess_exec(
        "node",
        str(script),
        mode,
        workflow_id,
        str(args_file),
        cwd=str(ws),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    except asyncio.TimeoutError:
        proc.kill()
        raise ComfySkillError("timeout", "comfyui-skill 执行超时（120s）")

    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace")[:300]
        raise ComfySkillError("cli_error", f"run_workflow_args.js 失败：{err}")

    try:
        return json.loads(stdout.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raw = stdout.decode("utf-8", errors="replace")[:200]
        raise ComfySkillError("bad_json", f"CLI 输出非 JSON：{raw}")


async def submit_workflow(workflow_id: str, args: dict, args_dir: Path) -> tuple[str, Path]:
    """Write args to a temp file and submit to ComfyUI.

    Returns ``(prompt_id, args_file)``. The caller keeps args_file around
    until job completion (useful for debugging / re-submission).
    """
    args_dir.mkdir(parents=True, exist_ok=True)
    args_file = args_dir / f"args_{args.get('filename_prefix', 'job')}_{int(asyncio.get_event_loop().time() * 1000)}.json"

    # run_workflow_args.js expects a bare args object (no wrapper).
    args_file.write_text(json.dumps(args, ensure_ascii=False, indent=2), encoding="utf-8")

    result = await _run_node(args_file, "submit", workflow_id)
    prompt_id = result.get("prompt_id")
    if not prompt_id:
        raise ComfySkillError(
            "no_prompt_id", f"submit 未返回 prompt_id：{json.dumps(result)[:200]}"
        )
    logger.info("submitted {} → prompt_id={}", workflow_id, prompt_id)
    return prompt_id, args_file


# ---------------------------------------------------------------------------
# Status polling + output download (direct HTTP to ComfyUI — read-only)
#
# We use HTTP here (not CLI) because polling every ~2s via subprocess would
# be wasteful, and these are stable public endpoints (/history, /view).
# ---------------------------------------------------------------------------


def _server_url() -> str:
    cfg_path = get_config().comfyui.config_json
    if not cfg_path or not Path(cfg_path).exists():
        raise ComfySkillError("no_config", "comfyui.config_json 未配置或不存在")
    data = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
    servers = data.get("servers") or []
    if not servers:
        raise ComfySkillError("no_servers", "config.json 中无 servers 配置")
    url = (servers[0].get("url") or "").rstrip("/")
    if not url:
        raise ComfySkillError("no_url", "servers[0].url 为空")
    return url


async def poll_history(prompt_id: str) -> Optional[dict]:
    """GET /history/{prompt_id}. Returns the history entry or None.

    None means: not finished yet (still queued/running), OR prompt lost
    (e.g. after ComfyUI restart). Callers distinguish by counting polls.
    """
    import httpx

    try:
        url = f"{_server_url()}/history/{prompt_id}"
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url)
            if r.status_code != 200:
                return None
            data = r.json()
            return data.get(prompt_id)  # None while pending/running
    except Exception:
        return None


async def cancel_prompt(prompt_id: str) -> bool:
    """Best-effort cancellation: POST /interrupt then delete from queue.

    ComfyUI has two mechanisms:
      - POST /interrupt          interrupts the *currently running* prompt
      - POST /queue   {"delete": [prompt_id]}   removes queued items

    We do both; success is best-effort (True if either returned 2xx).
    """
    import httpx

    ok = False
    try:
        base = _server_url()
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                r1 = await client.post(f"{base}/queue", json={"delete": [prompt_id]})
                ok = ok or r1.status_code in (200, 204)
            except Exception:
                pass
            try:
                r2 = await client.post(f"{base}/interrupt")
                ok = ok or r2.status_code in (200, 204)
            except Exception:
                pass
    except Exception as exc:
        logger.warning("cancel_prompt failed: {}", exc)
    return ok


async def download_image(filename: str, subfolder: str, dest: Path) -> Path:
    """Download one output file via GET /view and save to dest."""
    import httpx

    url = f"{_server_url()}/view"
    params = {"filename": filename, "subfolder": subfolder, "type": "output"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return dest