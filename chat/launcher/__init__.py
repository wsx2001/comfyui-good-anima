"""ComfyUI custom node: Good Anima Chat launcher.

This module is loaded by ComfyUI when ``ComfyUI/custom_nodes/good_anima_chat``
exists. We don't expose any workflow nodes — only an HTTP route that
probes the chat backend and a web-side button that opens it.

Install: symlink this directory into ComfyUI's custom_nodes/ folder.
See ``launcher/README.md`` for platform-specific instructions.
"""

from .chat_launcher import NODE_CLASS_MAPPINGS, WEB_DIRECTORY

__all__ = ["NODE_CLASS_MAPPINGS", "WEB_DIRECTORY"]