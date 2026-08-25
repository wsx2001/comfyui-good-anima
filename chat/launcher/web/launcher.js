/**
 * Good Anima Chat launcher — front-end extension for ComfyUI.
 *
 * Registers a button in ComfyUI's menu bar. Click it:
 *   1. POSTs /good_anima_chat/launch to probe the chat backend.
 *   2. If reachable, opens /good_anima_chat/url in a new tab.
 *   3. Otherwise, alerts the user with the run command.
 */

import { app } from "../../scripts/app.js"

const APP_NAME = "ComfyUI.GoodAnimaChatLauncher"

app.registerExtension({
  name: APP_NAME,

  async setup() {
    // The menu bar's container; resilient to ComfyUI version changes.
    const menuSelectors = [
      ".comfy-menu",
      "#comfy-main-menu",
      ".comfyui-menu",
    ]
    let menu = null
    for (const sel of menuSelectors) {
      menu = document.querySelector(sel)
      if (menu) break
    }
    if (!menu) {
      console.warn(`[${APP_NAME}] No ComfyUI menu container found`)
      return
    }

    const btn = document.createElement("button")
    btn.textContent = "🎨 Good Anima Chat"
    btn.className = "good-anima-chat-btn comfy-btn"
    btn.title = "打开本地 AI 对话生图工具"
    btn.style.cssText = [
      "margin: 4px 8px",
      "padding: 6px 12px",
      "cursor: pointer",
      "border: 1px solid #dcdfe6",
      "border-radius: 4px",
      "background: linear-gradient(180deg, #fff, #f5f7fa)",
      "font-size: 13px",
    ].join("; ")

    let busy = false
    btn.onclick = async () => {
      if (busy) return
      busy = true
      btn.disabled = true
      const original = btn.textContent
      btn.textContent = "🎨 检测中…"
      try {
        const r = await fetch("/good_anima_chat/launch", { method: "POST" })
        const data = await r.json()
        if (data.ok) {
          window.open(data.url, "_blank", "noopener")
        } else {
          alert(
            "Good Anima Chat 服务未启动。\n\n" +
              "请在终端运行：\n" +
              "  cd chat\n" +
              "  python -m backend\n\n" +
              "默认地址：" + (data.url || "http://127.0.0.1:8787/"),
          )
        }
      } catch (e) {
        alert("启动检测失败：" + (e?.message || e))
      } finally {
        busy = false
        btn.disabled = false
        btn.textContent = original
      }
    }

    menu.appendChild(btn)
    console.log(`[${APP_NAME}] Button injected`)
  },
})