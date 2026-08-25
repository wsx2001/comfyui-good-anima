# ComfyUI Good Anima Chat — Launcher

A small ComfyUI custom node that adds a **「🎨 Good Anima Chat」** button
to ComfyUI's menu bar. Clicking it opens the chat backend in a new tab,
after probing that the backend is actually running.

This directory contains **no workflow nodes** — it's a pure UI launcher.

---

## Supported ComfyUI versions

Tested with **ComfyUI 0.3.x** (uses `server.PromptServer.instance`).

If you have an older ComfyUI (< 0.3), the `from server import PromptServer`
import in `chat_launcher.py` will fail. Update ComfyUI or patch the
launcher accordingly.

---

## Installation

Pick **one** of the two methods below.

### Option A — Symlink (recommended for development)

Edit `CHAT_PATH` below to the absolute path of your `comfyui-good-anima/chat/launcher`
directory.

#### Linux / macOS

```bash
cd /path/to/ComfyUI/custom_nodes
ln -s /abs/path/to/comfyui-good-anima/chat/launcher good_anima_chat
```

#### Windows (PowerShell, admin)

```powershell
cd C:\path\to\ComfyUI\custom_nodes
New-Item -ItemType Junction -Path .\good_anima_chat -Target D:\Code\person_project\comfyui-good-anima\chat\launcher
```

(Junctions are directory symlinks; they don't require admin if both
volumes are local.)

### Option B — Copy (for deployment)

Just copy the `launcher/` directory into `ComfyUI/custom_nodes/good_anima_chat/`.
You'll need to manually re-copy after each update.

---

## Verifying

1. **Start the chat backend** (in a separate terminal):

   ```bash
   cd comfyui-good-anima/chat
   python -m backend
   # Expected: [OK] listening on http://127.0.0.1:8787
   ```

2. **Restart ComfyUI**.

3. Look in ComfyUI's menu bar for **「🎨 Good Anima Chat」**.

4. Click it. A new browser tab opens at <http://127.0.0.1:8787/>.

5. If the backend isn't running, the button shows an alert with the
   start command instead.

---

## Configuration

The chat URL is hard-coded to `http://127.0.0.1:8787/` by default.
To override, set the `GOOD_ANIMA_CHAT_URL` environment variable before
launching ComfyUI:

```bash
GOOD_ANIMA_CHAT_URL=http://192.168.1.10:8787/ python main.py
```

---

## Files

```
launcher/
├── __init__.py        # ComfyUI entry point
├── chat_launcher.py   # Backend: registers /good_anima_chat/* routes
├── web/
│   └── launcher.js    # Frontend: registers the menu-bar button
└── README.md          # This file
```