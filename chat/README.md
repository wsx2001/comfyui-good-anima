# ComfyUI Good Anima Chat 🎨

> 本地 AI 对话生图工具，配套 [comfyui-good-anima v2mini](../README.md) 使用。
> 通过浏览器直接和 LLM 聊出图，自动调度 ComfyUI 执行——不再依赖 AI 编程助手。

**当前状态：M0 骨架**（后端 + 前端 + ComfyUI Launcher 可跑通，无生图能力）
- 后端：FastAPI + SQLite + 配置持久化
- 前端：Vue 3 + Vite + Element Plus 设置页
- Launcher：ComfyUI 自定义节点侧栏按钮

---

## 架构一览

```
┌─────────────────────────────────────────────────────────┐
│  浏览器  (127.0.0.1:5173, Vue 3 SPA)                    │
│  └─ Settings 页面：改 LLM / ComfyUI 配置 + 测试调用    │
└──────────────────────────┬──────────────────────────────┘
                           │ /api/* (Vite proxy → 8787)
┌──────────────────────────▼──────────────────────────────┐
│  FastAPI 后端  (127.0.0.1:8787)                         │
│  ├─ GET  /api/health                                    │
│  ├─ GET  /api/settings                                  │
│  ├─ PUT  /api/settings                                  │
│  ├─ POST /api/settings/test_llm                         │
│  └─ POST /api/settings/reload                           │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
                  ┌──────────────────┐
                  │ ComfyUI (8187/8188) │
                  │ + v2mini skills     │
                  └──────────────────┘
```

完整设计与后续规划见：
- 📘 [docs/PROJECT.md](../docs/PROJECT.md) — 项目定位与边界
- 📋 [docs/PRD.md](../docs/PRD.md) — 产品需求与验收标准
- 📐 [docs/TECH.md](../docs/TECH.md) — 技术规格与里程碑

---

## 5 分钟跑起来

### 前置依赖

| 工具    | 版本          | 检查命令              |
| ------- | ------------- | --------------------- |
| Python  | 3.11+         | `python --version`    |
| Node.js | 18+           | `node --version`      |
| npm     | 9+            | `npm --version`       |
| Git     | 任意          | `git --version`       |

### 1. 后端（FastAPI）

```bash
cd comfyui-good-anima/chat
python -m pip install -r requirements.txt
python -m backend
```

期望输出（部分）：

```
14:23:01  | INFO | backend.app:create_app - Database initialised at chat/backend/runtime/chat.db
INFO:     Uvicorn running on http://127.0.0.1:8787
```

打开另一个终端验证：

```bash
curl http://127.0.0.1:8787/api/health
# {"status":"ok","db_ok":true,"comfyui_reachable":false,"llm_configured":false,"version":"0.1.0"}
```

### 2. 前端（Vue 3）

```bash
cd comfyui-good-anima/chat/frontend
npm install
npm run dev
```

期望：

```
  VITE v5.x  ready in xxx ms
  ➜  Local:   http://127.0.0.1:5173/
```

浏览器打开 <http://127.0.0.1:5173/>，会自动跳到 `/settings`。

**功能**：
- 「LLM 配置」卡：选 provider（DeepSeek / OpenAI / 通义 / Ollama / LM Studio），填 API key，点「测试调用」看到延迟或失败原因
- 「ComfyUI 配置」卡：填技能根目录、workspace、config.json 路径
- 修改后点「保存」，会实时持久化到 `backend/runtime/config.json`

### 3. ComfyUI Launcher（可选）

按 [launcher/README.md](./launcher/README.md) 把 launcher 软链到 ComfyUI 自定义节点目录，重启 ComfyUI 后侧栏会出现 **「🎨 Good Anima Chat」** 按钮。点击会：
- 先 POST `/good_anima_chat/launch` 探测后端
- 若可达 → 弹新标签页打开 <http://127.0.0.1:8787/>
- 若不可达 → alert 提示启动命令

---

## 验证清单（M0 验收）

- [ ] 后端 `python -m backend` 启动，输出 `Uvicorn running on http://127.0.0.1:8787`
- [ ] `GET /api/health` 返回 `{"status":"ok",...}`
- [ ] `backend/runtime/chat.db` 文件被创建
- [ ] 前端 `npm run dev` 启动，浏览器访问 <http://127.0.0.1:5173/> 自动跳到设置页
- [ ] Vite proxy 生效：浏览器开发者工具 Network 看到 `/api/health` 状态 200
- [ ] 设置页能改 LLM API Key 并点「保存」
- [ ] 设置页「测试调用」按钮能调用真实 LLM（成功显示延迟，失败显示 error_code）
- [ ] ComfyUI 重启后侧栏出现 Good Anima Chat 按钮
- [ ] 点击按钮在 chat 后端运行时能弹浏览器

---

## 项目结构

```
chat/
├── README.md                  ← 本文件
├── .gitignore                 ← runtime/ 等已 gitignore
├── requirements.txt           ← Python 依赖
├── pyproject.toml             ← Python 项目元数据
├── backend/                   ← FastAPI 后端
│   ├── __main__.py            ← python -m backend 入口
│   ├── app.py                 ← FastAPI app factory
│   ├── api/                   ← /api/* 路由
│   ├── config/                ← 配置 schema + 加载
│   ├── storage/               ← SQLModel + Setting 表
│   ├── llm/                   ← OpenAI 兼容客户端 + ComfyUI 探活
│   ├── utils/                 ← loguru 等
│   └── runtime/               ← 运行时产物（gitignored）
├── frontend/                  ← Vue 3 前端
│   ├── package.json
│   ├── vite.config.ts         ← /api proxy 到 8787
│   ├── tsconfig.json
│   ├── index.html
│   └── src/
│       ├── main.ts            ← Vue 挂载
│       ├── App.vue            ← 侧栏 + 路由出口
│       ├── router.ts
│       ├── views/
│       │   ├── SettingsView.vue     ← 完整实现
│       │   └── PlaceholderView.vue  ← 其他路由占位
│       ├── api/client.ts      ← fetch 封装 + 类型
│       └── style.css
└── launcher/                  ← ComfyUI 自定义节点
    ├── __init__.py
    ├── chat_launcher.py       ← PromptServer 路由
    ├── web/launcher.js        ← 侧栏按钮
    └── README.md              ← 安装说明
```

---

## 配置路径

| 路径                                              | 内容                       |
| ------------------------------------------------- | -------------------------- |
| `backend/runtime/chat.db`                        | SQLite 主数据库            |
| `backend/runtime/chat.db-wal`                    | SQLite WAL 文件             |
| `backend/runtime/config.json`                    | 主配置（API Key 已遮码）    |
| `backend/runtime/.secrets.json`                  | 真实 API Key（独立小文件） |

---

## 已知限制（M0 范围）

按设计，M0 **只搭骨架，不做生图**：

- ❌ 任何对话流（chat 接口）
- ❌ 任何生图能力（没接 ComfyUI，没接 LLM 对话）
- ❌ 工作流导入 / 节点映射
- ❌ 队列
- ❌ 会话历史

完整规划见 [TECH §11](../docs/TECH.md)。M1 开始接入对话与生图。

---

## 常见问题

### 后端启动报错：`Address already in use`

8787 端口被占。改环境变量：

```bash
COMFYUI_CHAT_PORT=8888 python -m backend
```

### 设置页保存后不生效

强制 reload：

```bash
curl -X POST http://127.0.0.1:8787/api/settings/reload
```

或在设置页重新加载浏览器（前端 store 不缓存）。

### 看不到 Vite proxy

确认 Vite 启动时没有报错。检查 `frontend/vite.config.ts` 的 `server.proxy` 配置。

### Windows 软链失败

参考 [launcher/README.md](./launcher/README.md#installation) 的 PowerShell `New-Item -ItemType Junction` 命令。

---

## 下一步开发

按 [TECH §11](../docs/TECH.md) 计划：

- **M1（3-4 周）**：US-1～US-10 全部打通——聊天 → 出图 → 续聊 → 队列串行 → 双模式 workflow
- **M2（2 周）**：任意 workflow 导入 + ZIP 导出 + 重启恢复 + Lightbox
- **M3**：画师融合 UX、图生图、并行队列

---

## 许可

GPLv3，与 v2mini 主项目保持一致。