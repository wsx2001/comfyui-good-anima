# 技术规格文档（TECH）

> 作者视角：资深 Python 后端 / 数据工程架构师
> 版本：v1.1 · 修订
> 日期：2026-08-23
> 输入：[PROJECT.md](./PROJECT.md) · [PRD.md](./PRD.md)

---

## 1. 总体架构

### 1.1 一句话架构

**FastAPI 单体 + Vue3 SPA + ComfyUI 自定义节点 launcher**，通过 `comfyui-skill` CLI 和 `danbooru-tags` CLI 与 v2mini 链路解耦；**通过 `WorkflowInjector` 双模式适配 v2mini 与任意 ComfyUI workflow**；**通过 `JobQueue` 实现场景列表串行生图**。

### 1.2 分层视图

```
┌────────────────────────────────────────────────────────────────────────┐
│  Browser (Vue 3 SPA, Vite)                                            │
│  ┌──────────┬─────────────┬──────────────┬────────────┬─────────────┐  │
│  │ Sessions │ Chat Stream │ Image Gallery│ Job Queue  │ Workflows   │  │
│  └──────────┴─────────────┴──────────────┴────────────┴─────────────┘  │
└──────────────────────────┬─────────────────────────────────────────────┘
                           │ HTTP + SSE (127.0.0.1:8787)
┌──────────────────────────▼─────────────────────────────────────────────┐
│  FastAPI Backend (Python 3.11, asyncio)                                │
│  ┌──────────┬──────────────┬─────────────┬──────────────────────────┐  │
│  │ API 路由 │ LLM 适配层   │ Skill Bridge│ Storage (SQLite)         │  │
│  └──────────┴──────────────┴─────────────┴──────────────────────────┘  │
│           │              │             │             │                  │
│           ▼              ▼             ▼             ▼                  │
│  ┌────────────────┐ ┌───────────┐ ┌─────────────────┐ ┌──────────────┐  │
│  │ LLM Provider   │ │ Workflow  │ │ danbooru-tags   │ │ JobQueue     │  │
│  │ (OpenAI 兼容)  │ │ Injector  │ │ + comfyui-skill │ │ (串行调度)   │  │
│  │ + reasoning    │ │ (双模式)  │ │   CLI           │ │              │  │
│  └────────────────┘ └───────────┘ └─────────────────┘ └──────────────┘  │
│                          │             │                                │
└──────────────────────────┼─────────────┼────────────────────────────────┘
                           │             │
                           ▼             ▼
                  ┌──────────────────────────────┐
                  │ ComfyUI server (8188)        │
                  │  v2mini workflow | 自定义 wf │
                  └──────────────────────────────┘
```

### 1.3 关键设计原则

| 原则                         | 体现                                                                          |
| ---------------------------- | ----------------------------------------------------------------------------- |
| **不重新实现 v2mini 规则**   | 硬约束以 SKILL.md 文本注入 LLM；后端只做「参数二次校验」兜底                  |
| **进程解耦**                 | Chat 与 ComfyUI 互不依赖：ComfyUI 死了 Chat 还能改配置、看历史                |
| **同步/异步清晰**            | LLM 流式 = SSE；ComfyUI 异步 = 后台任务 + SSE 推送结果；**队列 = 单 worker 串行** |
| **单文件可移植**             | SQLite WAL；整个项目用 `git clone` 拿走就能跑                                  |
| **失败可恢复**               | 任务状态机化（pending/running/succeeded/failed/cancelled）；**队列持久化、Chat 重启可恢复** |
| **注入而非重写**             | 任意 workflow 仅修改内存中的 JSON，**不写回磁盘**                            |

---

## 2. 技术栈选型

| 层            | 选型                            | 理由                                                                   |
| ---------------- | ------------------------------- | ---------------------------------------------------------------------- |
| 后端语言      | Python 3.11+                    | 与 v2mini 生态（danbooru-tags Python 索引脚本、comfyui-skill）一致      |
| 后端框架      | FastAPI + Uvicorn               | 原生 SSE、原生 async、与 Pydantic 强类型结合                           |
| LLM 客户端    | `openai` SDK（兼容模式）        | DeepSeek / 通义 / Ollama / LM Studio 全部走 OpenAI 协议；reasoning_effort 为 OpenAI 扩展参数，多数 provider 已支持 |
| 异步任务      | `asyncio` + 后台 Task           | 单进程够用；队列 worker 与 LLM 流式各自一个 asyncio Task               |
| 数据访问      | SQLModel（基于 SQLAlchemy 2.x） | Pydantic + ORM 一体；类型友好                                          |
| 数据库        | SQLite + WAL                    | 单文件零部署；WAL 模式并发读不阻塞写                                   |
| 进程间调用    | `asyncio.create_subprocess_exec` | 调 danbooru-tags / comfyui-skill CLI，非阻塞                            |
| 前端框架      | Vue 3 + Vite + TypeScript       | 体积小、流式渲染简单、Pina 状态轻                                       |
| UI 组件       | Element Plus                    | 中文社区成熟；样式成本最低                                              |
| HTTP 客户端   | `fetch` + `EventSource`         | 标准 SSE；无额外依赖                                                    |
| 配置          | JSON + 环境变量                 | 与 v2mini config.json 一致；环境变量覆盖敏感字段                        |
| 日志          | `loguru`                        | 零配置彩色日志；按等级 + 模块拆分                                      |
| 测试          | `pytest` + `pytest-asyncio`     | 同步 + 异步测试统一                                                     |
| 打包          | `pyinstaller` / `pipx`          | 用户偏好；MVP 仅提供 `python -m backend.app` 启动                     |

> **未选** 的关键依赖：Celery（杀鸡用牛刀）、Docker（MVP 不引入编排）、LangChain（过度抽象）、Tortoise ORM（与 FastAPI + Pydantic 集成不如 SQLModel 顺）。

---

## 3. 目录结构

```
comfyui-good-anima-chat/
├── README.md
├── docs/
│   ├── PROJECT.md
│   ├── PRD.md
│   └── TECH.md
├── backend/
│   ├── pyproject.toml
│   ├── app.py                       # FastAPI entrypoint
│   ├── api/
│   │   ├── conversations.py
│   │   ├── messages.py              # POST + SSE
│   │   ├── jobs.py                  # 单 job CRUD + SSE events
│   │   ├── workflows.py             # 自定义 workflow CRUD + 节点映射
│   │   ├── queues.py                # 队列 CRUD + 暂停/恢复/取消/追加
│   │   ├── settings.py              # /api/settings（含 LLM 参数）
│   │   └── launcher.py              # /api/launcher/status
│   ├── services/
│   │   ├── chat_service.py
│   │   ├── job_service.py           # 单 job 状态机
│   │   ├── job_queue.py             # 队列 worker（串行调度）
│   │   ├── prompt_assembler.py
│   │   ├── image_watcher.py
│   │   └── workflow_service.py      # workflow CRUD + 节点解析
│   ├── skills/
│   │   ├── base.py
│   │   ├── danbooru.py
│   │   ├── comfyui.py               # comfyui-skill CLI 封装
│   │   ├── prompts.py               # args 兜底校验
│   │   ├── workflow_injector.py     # 注入器抽象 + 工厂
│   │   ├── v2mini_injector.py       # 模式 A：v2mini 默认 workflow
│   │   └── generic_injector.py      # 模式 B：任意 ComfyUI workflow（节点注入）
│   ├── llm/
│   │   ├── client.py                # OpenAI 兼容 + reasoning_effort
│   │   ├── prompt_builder.py        # system prompt + workflow 描述
│   │   ├── tool_definitions.py      # tool: submit_image_gen / enqueue_scene_list
│   │   └── response_parser.py
│   ├── storage/
│   │   ├── db.py
│   │   ├── models.py                # Conversation / Message / Job / Image
│   │   │                            # Workflow / PromptNodeMapping
│   │   │                            # JobQueue / JobQueueItem
│   │   │                            # Setting (含 context_window / reasoning_effort)
│   │   └── migrate.py
│   ├── config/
│   │   ├── loader.py
│   │   └── schema.py
│   ├── runtime/
│   │   ├── args/                    # 提交 ComfyUI 的 args.json（按 job_id 命名）
│   │   ├── outputs/
│   │   └── logs/
│   └── utils/
│       ├── id_gen.py
│       ├── ssrf_safe.py
│       └── workflow_nodes.py        # 解析 workflow JSON 找 CLIPTextEncode
├── frontend/
│   ├── package.json
│   ├── index.html
│   ├── vite.config.ts
│   ├── src/
│   │   ├── main.ts
│   │   ├── App.vue
│   │   ├── views/
│   │   │   ├── ChatView.vue
│   │   │   ├── SessionsView.vue
│   │   │   ├── SettingsView.vue
│   │   │   └── WorkflowsView.vue    # 自定义 workflow 管理
│   │   ├── components/
│   │   │   ├── MessageBubble.vue
│   │   │   ├── ImageGallery.vue
│   │   │   ├── ImageLightbox.vue
│   │   │   ├── ParamsPanel.vue
│   │   │   ├── WorkflowSelector.vue
│   │   │   ├── NodeMappingEditor.vue
│   │   │   └── JobQueuePanel.vue    # 队列状态面板
│   │   ├── stores/
│   │   │   ├── session.ts
│   │   │   ├── chat.ts
│   │   │   ├── settings.ts
│   │   │   └── queue.ts
│   │   └── api/
│   │       └── client.ts
│   └── tsconfig.json
├── launcher/
│   ├── __init__.py
│   ├── chat_launcher.py
│   └── web/launcher_button.js
└── tests/
    ├── backend/
    │   ├── test_workflow_injector.py
    │   ├── test_job_queue.py
    │   ├── test_chat_service.py
    │   └── test_api.py
    └── frontend/
        └── components.test.ts
```

---

## 4. 核心模块说明

### 4.1 `backend/skills/workflow_injector.py` — 双模式注入器

**职责**：根据 `workflow_id` 选择注入策略，把 prompt 写到正确位置再提交。

```python
# skills/workflow_injector.py
class WorkflowInjector(Protocol):
    workflow_id: str
    async def build_payload(self, args: dict) -> WorkflowPayload: ...  # 返回给 comfyui-skill
    async def validate_args(self, args: dict) -> ValidationResult: ...

# 工厂
def get_injector(workflow_id: str, ctx: InjectorContext) -> WorkflowInjector:
    if workflow_id.startswith("local/anima-") or workflow_id in V2MINI_WORKFLOWS:
        return V2MiniInjector(workflow_id, ctx)
    return GenericInjector(workflow_id, ctx)  # 查 DB 拿节点映射
```

#### 模式 A：`V2MiniInjector`（默认）

- 直接复用 v2mini `comfyui-manager` 链路：扁平 args → `node run_workflow_args.js submit`
- 节点注入由 v2mini 内部完成
- 必须经过 `prompts.py` 的 args 兜底校验
- 必须经过 `danbooru.py` 的 hard anchor 校验

#### 模式 B：`GenericInjector`（高级 / 任意 workflow）

- 从 DB 取该 workflow 的节点映射（`PromptNodeMapping`）
- 加载 workflow JSON（缓存到内存，按需从磁盘读）
- **深拷贝** workflow JSON（保护原文件）
- 修改 `positive_prompt_node_id` 的 `inputs.text` 为 `args["prompt_11"]`
- 修改 `negative_prompt_node_id` 的 `inputs.text` 为 `args["prompt_12"]`（若有）
- 其它 args 字段（width/height/steps/batch_size/seed）按 workflow 的约定节点路径注入；
  MVP 不做通用参数注入，仅 prompt 文本注入 + 让 ComfyUI 用 workflow 自带默认
- 调用 comfyui-skill 的 `--workflow-data` 直接提交修改后的 JSON

**关键代码骨架**：

```python
# skills/generic_injector.py
class GenericInjector:
    def __init__(self, workflow_id: str, ctx: InjectorContext):
        self.workflow_id = workflow_id
        self.mapping = ctx.db.get_prompt_mapping(workflow_id)
        self.original_json = ctx.workflow_loader.load(workflow_id)

    def build_payload(self, args: dict) -> WorkflowPayload:
        wf = copy.deepcopy(self.original_json)
        wf[self.mapping.positive_node_id]["inputs"]["text"] = args["prompt_11"]
        if self.mapping.negative_node_id:
            wf[self.mapping.negative_node_id]["inputs"]["text"] = args.get("prompt_12", "")
        return WorkflowPayload(workflow_json=wf, extra_args=args)
```

### 4.2 `backend/services/job_queue.py` — 队列调度

**职责**：串行执行 JobQueueItem，事件驱动（不轮询），持久化所有状态。

#### 数据流

```
LLM tool call: enqueue_scene_list
   ↓
JobQueueService.create(items)
   ↓
DB: 插入 JobQueue + N 个 JobQueueItem（state=pending）
   ↓
启动后台 worker（一个 asyncio Task）
   ↓
loop over items:
   ├─ 检查 queue.state（pause / cancel 信号）
   ├─ 取 next item（state=pending, by order）
   ├─ 提交 ComfyUI（走 WorkflowInjector）
   ├─ 创建 Job 记录（state=running）
   ├─ 等待 image_watcher 回调（asyncio.Event）
   ├─ 收到图片 → 更新 Job state=succeeded, item state=done
   ├─ 收到失败 → 更新 Job state=failed, item state=failed（继续下一个，不卡住）
   ├─ 推送 SSE: queue.item_done / queue.item_failed
   ↓
所有 item 完成 → queue.state=completed, SSE: queue.completed
```

#### 暂停 / 恢复 / 取消

| 操作      | 实现                                                                                  |
| --------- | ------------------------------------------------------------------------------------- |
| **暂停**  | `queue.state = paused`；worker 在 item 完成边界检查，发现 paused 就停止取新 item       |
| **恢复**  | `queue.state = running`；worker 下一轮循环检测到 running 继续                          |
| **取消**  | `queue.state = cancelled`；立即取消当前 job（调 comfyui cancel）+ 清空 pending items |
| **追加**  | INSERT new JobQueueItem(state=pending)；worker 自动 pick up                             |

#### 重启恢复

- 启动时扫描 `JobQueue WHERE state = 'running'`，对应 worker 已死
- 把 state 改回 `running`，对应 item 状态：
  - 如果 ComfyUI 历史中该 prompt_id 已完成 → 标 succeeded，关联图片
  - 如果还在 → 重启 worker 继续
  - 如果丢失 → 标 failed(reason=comfyui_lost)

### 4.3 `backend/llm/` — LLM 适配层

**职责**：与 LLM 通信、流式响应解析、把 v2mini SKILL.md 注入 system prompt，**让 LLM 知道双模式工作流与队列能力**。

**System Prompt 组装顺序**：

```
1. # Role
   你是 v2mini 生图助理，按以下规则工作。

2. # Hard Constraints（直接复制 v2mini SKILL.md 的硬约束段）
   ...

3. # Workflow Decision Tree
   （用户意图 → 决策路径）
   - 普通生图 → 选 workflow → 视觉简报 → tag 校验 → 三层 prompt → submit_image_gen
   - 「依次生成 N 个场景」→ 拆解为独立 prompt 列表 → enqueue_scene_list
   - 「切换 workflow」→ workflow_id 字段变化
   - 迭代 → 加载上一轮 prompt + 修改
   - 参数调整 → 直接修改 args 字段
   - ...

4. # Available Workflows
   - local/anima-txt2img-aesthetic-lora (默认，双 LoRA)
   - local/anima-txt2img-base (裸模型)
   - local/anima-txt2img-aesthetic-lora-artist-mixer (画师融合)
   - local/anima-txt2img-aesthetic-lora-enhancer (加速)
   - local/anima-txt2img-aesthetic-lora-fixed (固定参数)
   - [用户自定义 workflow 列表，动态注入]

5. # Tools
   - submit_image_gen(workflow_id, args)
       - args 必须包含 prompt_11 / prompt_12 / width / height / batch_size / steps / filename_prefix
       - workflow_id 必填（默认 local/anima-txt2img-aesthetic-lora）
   - enqueue_scene_list(workflow_id, items)
       - items: [{scene_label, prompt_11, prompt_12, args}, ...]
       - 每个 item 独立走「视觉简报 → tag 校验 → 三层 prompt」（v2mini 硬约束）
   - validate_tags(candidates)
   - list_workflows() → 返回可用 workflow + 用户自定义

6. # Output Format
   - 默认回复用 Markdown
   - 触发生图时调用 submit_image_gen tool
   - 触发队列时调用 enqueue_scene_list tool（**不是** batch_size）
   - tool args 必须包含完整 prompt_11 / prompt_12
```

**Reasoning 控制**：

```python
# llm/client.py
async def chat_stream(messages, *, reasoning_effort: str | None = None):
    params = {"model": ..., "messages": ..., "stream": True}
    if reasoning_effort and reasoning_effort != "off":
        params["reasoning_effort"] = reasoning_effort  # low/medium/high
    # 客户端不抛错，provider 忽略不支持的参数
```

### 4.4 `backend/services/job_service.py` — 单 job 状态机

```python
class JobState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

- 每个 job 有 `job_id`（ULID）和 `prompt_id`（ComfyUI 返回）
- 启动时扫描 `running` 状态的 job，向 ComfyUI 探活；已完成的更新为 `succeeded/failed`，丢失的标记 `failed(reason=comfyui_lost)`
- 通过 SSE 推送状态变更给前端
- **队列中的 job 与单图 job 共享同一 Job 表**，通过 `source` 字段区分（`source: "single" | "queue"`）

### 4.5 `backend/services/image_watcher.py` — 输出监听

- 用 `watchdog` 监听 ComfyUI `output_dir`（来自 config.json）
- 新增 `.png` / `.webp` 时，按 `filename_prefix` 匹配运行中 job
- 命中则：复制（软链）到 `runtime/outputs/`，更新 job state = SUCCEEDED，关联到 image 表
- 通过 `asyncio.Event` 通知 `job_queue` worker 该 job 已完成（事件驱动，无轮询）

### 4.6 `backend/storage/models.py` — 数据模型

```python
# === 会话与消息 ===
class Conversation(SQLModel, table=True):
    id: str = Field(primary_key=True)        # ULID
    title: str
    created_at: datetime
    updated_at: datetime
    default_workflow_id: str | None          # 该会话默认 workflow
    default_params: dict | None              # JSON: {"width": 1024, ...}

class Message(SQLModel, table=True):
    id: str = Field(primary_key=True)
    conversation_id: str = Field(foreign_key="conversation.id", index=True)
    role: str                                  # "user" | "assistant" | "system"
    content: str
    reasoning: str | None
    created_at: datetime

# === Job ===
class Job(SQLModel, table=True):
    id: str = Field(primary_key=True)
    conversation_id: str
    message_id: str | None
    queue_item_id: str | None                  # 若由队列产生，关联
    prompt_id: str | None
    workflow_id: str
    injector_mode: str                         # "v2mini" | "generic"
    args_snapshot: dict                        # 提交时的 args
    state: str
    error: str | None
    created_at: datetime
    finished_at: datetime | None
    source: str                                # "single" | "queue"

class Image(SQLModel, table=True):
    id: str = Field(primary_key=True)
    job_id: str = Field(foreign_key="job.id", index=True)
    file_path: str
    width: int
    height: int
    seed: int | None
    created_at: datetime

# === 自定义 Workflow（高级模式） ===
class Workflow(SQLModel, table=True):
    id: str = Field(primary_key=True)          # ULID
    name: str                                  # 用户起的名字
    source: str                                # "v2mini" | "custom"
    file_path: str | None                       # 自定义 workflow JSON 磁盘路径
    raw_json: dict | None                      # 缓存（小 workflow 内嵌）
    created_at: datetime

class PromptNodeMapping(SQLModel, table=True):
    id: str = Field(primary_key=True)
    workflow_id: str = Field(foreign_key="workflow.id", unique=True)
    positive_node_id: str                      # CLIPTextEncode node id
    positive_node_title: str | None
    negative_node_id: str | None
    negative_node_title: str | None

# === 队列 ===
class JobQueue(SQLModel, table=True):
    id: str = Field(primary_key=True)          # ULID
    conversation_id: str = Field(foreign_key="conversation.id", index=True)
    workflow_id: str
    state: str                                 # running / paused / completed / cancelled / failed
    title: str | None                          # "依次生成：..."
    created_at: datetime
    finished_at: datetime | None

class JobQueueItem(SQLModel, table=True):
    id: str = Field(primary_key=True)
    queue_id: str = Field(foreign_key="jobqueue.id", index=True)
    order_index: int                           # 0..N-1
    scene_label: str | None                   # "A 雨天天台"
    prompt_11: str
    prompt_12: str
    args: dict
    state: str                                 # pending / running / done / failed / skipped
    job_id: str | None                         # 关联到 Job
    error: str | None
    created_at: datetime
    finished_at: datetime | None

# === 设置（key-value JSON）===
class Setting(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str                                 # JSON-encoded
    updated_at: datetime

# 常用 key：
#   "llm.api_key", "llm.base_url", "llm.model",
#   "llm.max_tokens", "llm.temperature",
#   "llm.reasoning_effort" (off|low|medium|high),
#   "llm.context_window" (int, 0-50),
#   "comfyui.skills_root", "comfyui.workspace"
```

**索引**：`message(conversation_id, created_at)`、`job(conversation_id, created_at)`、`image(job_id)`、`jobqueueitem(queue_id, order_index)`。

---

## 5. API 设计

### 5.1 REST

| Method | Path                                              | 用途                                         |
| ------ | ------------------------------------------------- | -------------------------------------------- |
| GET    | `/api/health`                                     | 健康检查（供 launcher 探活）                |
| GET    | `/api/settings`                                   | 获取当前配置（含 LLM 参数）                 |
| PUT    | `/api/settings`                                   | 修改配置（实时生效）                         |
| GET    | `/api/conversations`                              | 会话列表                                     |
| POST   | `/api/conversations`                              | 新建会话                                     |
| GET    | `/api/conversations/{id}`                         | 会话详情                                     |
| PATCH  | `/api/conversations/{id}`                         | 重命名 / 改默认 workflow                    |
| DELETE | `/api/conversations/{id}`                         | 删除会话                                     |
| POST   | `/api/conversations/{id}/messages`                | **发送消息**（返回 SSE 流）                  |
| POST   | `/api/conversations/{id}/messages/{mid}/cancel`   | 取消该消息关联的运行中 job                  |
| GET    | `/api/jobs/{id}`                                  | 单个 job 状态                                |
| POST   | `/api/jobs/{id}/cancel`                           | 取消 job                                     |
| GET    | `/api/jobs/{id}/events`                           | SSE 流：job 状态 + 图片                     |
| GET    | `/api/workflows`                                  | 列出所有 workflow（v2mini + 自定义）        |
| POST   | `/api/workflows`                                  | 导入自定义 workflow（multipart .json）      |
| GET    | `/api/workflows/{id}/nodes`                       | 列出 CLIPTextEncode 节点供用户选             |
| PUT    | `/api/workflows/{id}/mapping`                     | 保存节点映射                                  |
| DELETE | `/api/workflows/{id}`                             | 删除自定义 workflow                          |
| POST   | `/api/queues`                                     | 创建队列（也由 LLM tool 触发）              |
| GET    | `/api/queues/{id}`                                | 队列详情（含 items）                          |
| POST   | `/api/queues/{id}/pause`                          | 暂停                                          |
| POST   | `/api/queues/{id}/resume`                         | 恢复                                          |
| POST   | `/api/queues/{id}/cancel`                         | 取消                                          |
| POST   | `/api/queues/{id}/items`                          | 追加 item                                     |
| GET    | `/api/queues/{id}/events`                         | SSE 流：item 进度                            |
| GET    | `/api/queues/{id}/export.zip`                     | 导出整队图片为 ZIP                            |
| GET    | `/api/images/{id}`                                | 单图详情 + 下载                              |

### 5.2 SSE 事件统一

**`POST /api/conversations/{id}/messages`** 与 **`GET /api/queues/{id}/events`** 共用以下事件类型：

| event 字段        | data 内容                                                  | 触发时机                          |
| ----------------- | ---------------------------------------------------------- | --------------------------------- |
| `message.start`   | `{message_id}`                                             | assistant 消息开始                |
| `reasoning.delta` | `{delta: "..."}`                                           | LLM 思维链片段                    |
| `content.delta`   | `{delta: "..."}`                                           | assistant 文本片段                |
| `tool.call`       | `{name, args}`                                             | LLM 决定调 tool                   |
| `queue.created`   | `{queue_id, item_count}`                                   | 创建队列                          |
| `queue.item_start`| `{queue_id, item_id, scene_label}`                         | 开始执行 item                     |
| `queue.item_done` | `{queue_id, item_id, image_id}`                            | item 成功                          |
| `queue.item_fail`| `{queue_id, item_id, error}`                                | item 失败                          |
| `queue.completed` | `{queue_id, total, succeeded, failed}`                     | 队列完成                            |
| `job.created`     | `{job_id, workflow_id, args_summary}`                      | 提交 ComfyUI 后                   |
| `job.state`       | `{job_id, state, error?}`                                  | job 状态变更                      |
| `image.added`     | `{image_id, url, width, height, seed}`                     | 图片落地                          |
| `message.end`     | `{message_id, finish_reason}`                              | 流结束                            |
| `error`           | `{code, message, recoverable}`                             | 异常                              |

### 5.3 数据契约示例

```jsonc
// POST /api/conversations/{id}/messages
{
  "content": "依次生成：1. 立华奏雨中天台 2. 雾雨魔理沙魔法森林 3. 八云紫夜晚书房",
  "workflow_id": "local/anima-txt2img-aesthetic-lora",
  "client_msg_id": "ulid-xxx"
}

// POST /api/queues（也由 LLM tool 触发）
{
  "conversation_id": "...",
  "workflow_id": "local/anima-txt2img-aesthetic-lora",
  "title": "依次生成三个场景",
  "items": [
    {
      "scene_label": "1 立华奏雨中天台",
      "prompt_11": "...",
      "prompt_12": "...",
      "args": {"width": 1024, "height": 1536, ...}
    },
    ...]
}

// PUT /api/workflows/{id}/mapping
{
  "positive_node_id": "12",
  "negative_node_id": "15"
}
```

---

## 6. 关键流程时序

### 6.1 用户消息 → 单图生图主流程

```
Browser             FastAPI           LLM          WorkflowInjector  ComfyUI
   │  POST message    │                │                │                │
   │─────────────────▶│                │                │                │
   │                  │ persist user   │                │                │
   │                  │ load ctx (N轮) │                │                │
   │                  │ build sysprmt  │                │                │
   │                  │  stream chat   │                │                │
   │                  │───────────────▶│                │                │
   │  SSE:reasoning   │◀───────────────│                │                │
   │  SSE:content     │◀───────────────│                │                │
   │  SSE:tool.call   │                │                │                │
   │                  │  tool: submit_image_gen          │                │
   │                  │  validate args ──▶               │                │
   │                  │  build payload ─────────────────▶│                │
   │                  │  v2mini: CLI submit              │                │
   │                  │  generic: 修改 JSON + submit     │                │
   │                  │                                  │   HTTP submit │
   │                  │                                  │──────────────▶│
   │                  │                                  │◀──────────────│
   │                  │  prompt_id                        │                │
   │  SSE:job.created │  persist job                      │                │
   │◀─────────────────│                                  │                │
   │                  │  background: image_watcher       │                │
   │                  │      │ (event-driven)             │                │
   │                  │      ▼                           │                │
   │  SSE:image.added │  persist image                   │                │
   │  SSE:job.state   │  job state = SUCCEEDED           │                │
   │◀─────────────────│                                  │                │
   │  SSE:message.end │                                  │                │
   │◀─────────────────│                                  │                │
```

### 6.2 队列流程：场景列表串行生图

```
Browser           FastAPI             LLM              JobQueue Worker    ComfyUI
   │ POST message    │                  │                    │                 │
   │────────────────▶│                  │                    │                 │
   │                 │ stream chat      │                    │                 │
   │                 │─────────────────▶│                    │                 │
   │                 │ tool: enqueue_scene_list              │                 │
   │                 │◀─────────────────│                    │                 │
   │                 │ create queue + items (DB)            │                 │
   │                 │ start worker ───────────────────────▶│                 │
   │ SSE:queue.      │                  │                    │                 │
   │   created       │                  │                    │                 │
   │◀────────────────│                  │                    │                 │
   │                 │                  │                    │ loop:           │
   │                 │                  │                    │   pick item[0] │
   │                 │                  │                    │   submit job   │────▶│
   │ SSE:queue.      │                  │                    │                 │
   │   item_start    │                  │                    │                 │
   │◀────────────────│                  │                    │                 │
   │                 │                  │  wait (asyncio.Event, no polling)    │
   │                 │                  │                    │                 │
   │                 │                  │   image detected ──┤                 │
   │                 │                  │                    │   persist job   │
   │ SSE:image.added │                  │                    │   item done     │
   │◀────────────────│                  │                    │                 │
   │                 │                  │                    │   pick item[1] │
   │                 │                  │                    │   ... (loop)    │
   │                 │                  │                    │                 │
   │ SSE:queue.      │                  │                    │ all done        │
   │   completed     │                  │                    │                 │
   │◀────────────────│                  │                    │                 │
```

### 6.3 取消流程

```
Browser             FastAPI           ComfyUI       ImageWatcher    JobQueue Worker
   │ POST cancel      │                  │               │                │
   │─────────────────▶│  prompt_id       │               │                │
   │                  │  call cancel ───▶│               │                │
   │                  │◀────── ok ───────│               │                │
   │                  │  job.state = CANCELLED                          │
   │  SSE:job.state   │  stop watching output            │                │
   │◀─────────────────│                                                  │
   │ POST cancel      │                                                  │
   │   queue          │                                                  │
   │─────────────────▶│  queue.state = cancelled                         │
   │                  │  cancel current job ─────────────▶               │
   │                  │  skip remaining items ────────────────────────▶│
   │  SSE:queue.      │                                                  │
   │   completed      │                                                  │
   │   (reason:       │                                                  │
   │    cancelled)    │                                                  │
   │◀─────────────────│                                                  │
```

### 6.4 通用 workflow 导入与使用流程

```
[设置页]
  │
  │ 1. 用户上传 .json
  ▼
[API: POST /api/workflows]
  │
  │ 2. WorkflowService.import()
  │    - 校验 JSON 结构（≤5MB）
  │    - 解析所有 CLIPTextEncode 节点
  │    - 写入 DB（Workflow + nodes 临时缓存）
  │
  │ 3. 返回 {workflow_id, nodes: [{node_id, title, class_type}]}
  │
  │ 4. UI 显示节点列表，用户选 positive / negative
  │
  │ 5. PUT /api/workflows/{id}/mapping
  │    - 持久化 PromptNodeMapping
  │
  ▼
[对话中使用]
  │
  │ 6. 用户说"用我的 custom workflow 出图"
  │ 7. LLM 选 workflow_id 为 custom 的 ULID
  │ 8. WorkflowInjector.get_injector() → GenericInjector
  │ 9. GenericInjector.build_payload():
  │    - deepcopy 原 JSON
  │    - 写 positive / negative text
  │ 10. 提交 ComfyUI
```

### 6.5 重启恢复

```
App start
   │
   ▼
Scan jobs WHERE state IN ('PENDING','RUNNING')
   │
   ├─ For each job:
   │    ├─ Query ComfyUI history(prompt_id)
   │    ├─ 若完成 → 更新 state，关联落地图片
   │    ├─ 若仍运行 → 保持 RUNNING，继续监听
   │    └─ 若丢失 → state=FAILED(reason=comfyui_lost)
   ▼
Scan JobQueue WHERE state = 'running'
   │
   ├─ 重新派入 background task
   ├─ 重新 pick up 未完成 items
   └─ 继续监听 / 提交
   ▼
继续接受新请求
```

---

## 7. 与 v2mini 的集成策略

| 集成点           | 方式                                              | 备注                                            |
| ---------------- | ------------------------------------------------- | ----------------------------------------------- |
| SKILL.md 内容    | 启动时从 `skills_root` 读取，注入 system prompt  | 文件路径由用户配置；变更后下次会话生效          |
| danbooru-tags    | `subprocess.run(['danbooru-tags.exe', ...])`      | **仅 v2mini 模式**需要；高级模式跳过（不强制 Anima 硬约束） |
| comfyui-skill    | `subprocess.run(['node', 'run_workflow_args.js'])`| v2mini 模式走 submit 模式；**Generic 模式走 raw workflow JSON 提交** |
| ComfyUI 配置     | 读取 `comfyui-manager/workspace/config.json`     | 复用 `servers[]` 配置；只读                     |
| 输出目录         | 监听 `output_dir`（来自 config）                 | watchdog；事件驱动                             |

**双模式执行对比**：

| 维度         | V2MiniInjector                          | GenericInjector                            |
| ------------ | --------------------------------------- | ------------------------------------------- |
| 工作流来源   | v2mini 5 个内置 workflow                 | 用户导入的任意 ComfyUI workflow JSON        |
| 参数注入     | 扁平 args.json（v2mini 内部映射节点）     | 直接修改 CLIPTextEncode 节点的 `inputs.text` |
| 硬约束校验   | 必须（v2mini 硬约束完整继承）            | 可选（默认不校验，用户可在 tool call 中声明 skip_constraints） |
| 提交方式     | `run_workflow_args.js submit`            | `comfyui-skill workflow submit --data <json>` |
| args 校验    | 后端 prompts.py 二次校验                 | 后端 minimal 校验（仅 prompt_11 / prompt_12 非空） |

**不直接做** 的事：
- ❌ 解析 / 修改 workflow 中非 CLIPTextEncode 节点
- ❌ 重写 comfyui-skill CLI
- ❌ 重写 danbooru-tags Rust CLI

---

## 8. 错误处理与降级

| 错误                          | 检测                            | 用户可见行为                                   | 后端行为                              |
| ----------------------------- | ------------------------------- | ---------------------------------------------- | ------------------------------------- |
| LLM API Key 无效              | HTTP 401                        | 设置页标红 + 跳引导                            | 停止当前 job，状态 FAILED              |
| LLM 限流                      | HTTP 429                        | 「LLM 限流，10s 后重试」                       | 指数退避，最多 3 次                   |
| reasoning_effort 不支持       | provider 忽略 / 4xx             | 无声忽略                                       | 不重试，记录 debug 日志               |
| danbooru 校验无结果           | CLI 返回空                      | 「标签 X 找不到候选，请换描述」                | 把失败 tag 反馈给 LLM 重试（≤2 次）   |
| 高级模式 workflow 导入失败    | JSON 解析 / 节点扫描            | 「导入失败：xxx」                              | 拒绝保存                              |
| 高级模式 workflow 无 CLIPTextEncode | 节点列表为空                  | 「该 workflow 未发现 prompt 节点，无法注入」   | 拒绝导入                              |
| ComfyUI 离线                  | subprocess 非零退出              | 「ComfyUI 未启动」                             | job FAILED                            |
| ComfyUI 任务失败              | watcher 收到 error 文件         | 「生成失败：xxx」                              | job FAILED；队列 item FAILED；**队列继续下一个** |
| 用户取消                      | POST cancel                     | 「已取消」                                     | job CANCELLED；queue CANCELLED        |
| args 缺失关键字段            | 后端 schema 校验                | 不显示给用户；反馈给 LLM 补全                  | 拒绝提交，重试 ≤2 次                  |
| 队列 worker 崩溃              | asyncio Task 异常               | 队列自动恢复（启动时扫描）                     | 异常落日志，状态保留                  |
| SQLite 写失败                 | engine 异常                      | 顶部条幅「数据库写入失败，请检查磁盘」         | 不丢内存中数据，提示用户备份          |

---

## 9. 配置管理

### 9.1 配置文件：`backend/config/config.json`

```jsonc
{
  "server": { "host": "127.0.0.1", "port": 8787 },
  "comfyui": {
    "skills_root": "C:/skills",
    "workspace": "C:/skills/comfyui-manager/workspace",
    "config_json": "C:/skills/comfyui-manager/workspace/config.json"
  },
  "llm": {
    "base_url": "https://api.deepseek.com/v1",
    "api_key": "",
    "model": "deepseek-chat",
    "temperature": 0.7,
    "max_tokens": 4096,
    "reasoning_effort": "off",        // off | low | medium | high
    "context_window": 5               // 保留最近 N 轮消息
  },
  "storage": {
    "db_path": "backend/runtime/chat.db",
    "outputs_dir": "backend/runtime/outputs"
  },
  "system_prompt": {
    "v2mini_animatool_path": "{skills_root}/comfyui-animatool/SKILL.md",
    "v2mini_danbooru_path": "{skills_root}/danbooru-tags/SKILL.md",
    "v2mini_manager_path": "{skills_root}/comfyui-manager/SKILL.md"
  }
}
```

### 9.2 环境变量覆盖

```
COMFYUI_CHAT_PORT=8787
COMFYUI_CHAT_LLM_API_KEY=sk-xxx
COMFYUI_CHAT_LLM_BASE_URL=https://api.deepseek.com/v1
COMFYUI_CHAT_LLM_REASONING_EFFORT=high
COMFYUI_CHAT_LLM_CONTEXT_WINDOW=10
COMFYUI_CHAT_SKILLS_ROOT=C:/skills
```

> 敏感字段（API Key）优先从 env 读；UI 设置项同步写回 JSON。

---

## 10. 部署与启动

### 10.1 首次启动

```bash
# 1. 克隆
git clone <repo>
cd comfyui-good-anima-chat

# 2. 后端依赖
cd backend
pip install -e .
python -m app         # 自动初始化 SQLite、生成默认 config.json

# 3. 前端开发
cd ../frontend
npm install
npm run dev           # 默认监听 5173，proxy /api 到 8787

# 4. 生产模式
npm run build
# 把 dist/ 放到 backend/app.py 启动时的 static 目录
```

### 10.2 启动校验清单

- [ ] `python -m app` 输出 `[OK] listening on http://127.0.0.1:8787`
- [ ] `GET /api/health` 返回 `{"status":"ok","comfyui_reachable":true}`
- [ ] 设置页填入 LLM API Key 后，测试调用通过
- [ ] 设置页导入自定义 workflow，能正确识别 CLIPTextEncode 节点
- [ ] 队列测试：发"依次生成 3 个简单场景"，能在对话流中逐张看到结果

---

## 11. 里程碑

| 里程碑       | 时间    | 范围                                                                                              | 验收                                                                                |
| ------------ | ------- | ------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| **M0 骨架**  | 1 周    | FastAPI 启动 + SQLite 建表 + 健康检查 + 配置加载 + Launcher 节点 + **Settings 页**（含 LLM 参数） | `python -m app` 启动，`/api/health` 200；ComfyUI 节点按钮可见；设置页能改并验证 LLM |
| **M1 MVP**   | 3-4 周  | US-1 / US-2 / US-3 / US-4 / US-5 / US-6 / US-7 / US-8 全打通 + **US-9 默认模式** + 队列基础 US-10 | 端到端走通「聊天 → 出图 → 续聊 → 队列串行 3 张」                                    |
| **M2 增强**  | 2 周    | **US-9 高级模式**（任意 workflow 导入 + 节点映射）+ 队列 ZIP 导出 + 重启恢复 + 图片 Lightbox + i18n 框架预留 | PRD §7 非功能指标达标                                                              |
| **M3 增值**  | TBD     | 画师融合 UX、图生图、并行队列                                                                      | PRD §3.2 移入 In-Scope 后单独排期                                                  |

---

## 12. 风险与缓解

| 风险                                       | 概率 | 影响 | 缓解                                                                |
| ------------------------------------------ | ---- | ---- | ------------------------------------------------------------------- |
| LLM 输出的 tool args 缺字段                | 中   | 高   | 后端 Pydantic 校验 + 反馈给 LLM 重试 ≤2 次                          |
| LLM 忽略硬约束，越权选画师                  | 中   | 中   | args 必须经「LLM 输出 → Python 校验 → comfyui-manager 执行」三道闸  |
| 多 LLM 协议差异                            | 低   | 中   | 用 OpenAI SDK 兼容模式；用户自配 base_url                            |
| 流式 SSE 被反代 / 浏览器缓冲                | 低   | 低   | 后端定期发心跳（`: heartbeat\n\n`），前端 30s 无新 chunk 即提示断线   |
| SQLite 单文件被锁                          | 低   | 中   | WAL 模式 + 启动时 `PRAGMA integrity_check`                          |
| ComfyUI 长时间任务导致 SSE 连接超时         | 中   | 低   | nginx/proxy 默认 60s；本地直连无问题；客户端自动重连                  |
| 用户错误关闭后未完成 job 的悬挂            | 中   | 低   | 启动恢复流程（§6.5）                                                |
| GenericInjector 修改 workflow 引入未知副作用 | 中   | 中   | **不写回磁盘**；深拷贝；提交时让 ComfyUI 仅作为新一次执行            |
| 用户上传恶意 workflow JSON                  | 低   | 中   | JSON 解析时拒绝带代码执行特征；大小限制 5MB；提交到 127.0.0.1 才执行  |
| 队列长时间运行（>1h）GPU 持续占用           | 中   | 中   | 队列面板展示预计剩余时间；用户可主动暂停                              |
| LLM 拆解场景列表时遗漏场景                 | 中   | 中   | 拆解结果在「队列预览」中可编辑，编辑后再创建队列                      |

---

## 13. 接口变更与版本管理

- API 路径稳定版本：`/api/v1/...` 暂不引入，PRD v1 内路径固定
- 若 SKILL.md 内容大改导致 system prompt 行为变化，引入 `system_prompt_version` 字段，DB 持久化供 A/B 对比
- 配置 schema 变更走 Pydantic 兼容 + 启动时迁移

---

## 14. 交付物清单（移交开发时附）

- 本 TECH（`docs/TECH.md`）
- PRD（`docs/PRD.md`）
- v2mini 三份 SKILL.md（作为 system prompt 内容源）
- `comfyui-manager/workspace/config.json` 样例
- 数据库 schema 文档（本文件 §4.6）
- API 契约（本文件 §5）
- 时序图（本文件 §6）

---

## 15. 待确认事项（移交开发前 PM / 架构师对齐）

| 事项                                | 默认假设                                          | 待 PM 确认                                  |
| ----------------------------------- | ------------------------------------------------- | ------------------------------------------- |
| LLM 默认推荐配置                    | DeepSeek-chat（中文友好 + 便宜 + 兼容 OpenAI）    | 是否要内置多 provider 预设？               |
| ComfyUI 状态检测失败时是否允许对话  | 允许（仅生图功能不可用）                          | 是否要硬阻断？                              |
| 单会话消息上限                      | 不限（按 SQLite 上限）                            | 是否要软上限 1000 条防止 DB 膨胀？          |
| 默认 workflow_id                    | `local/anima-txt2img-aesthetic-lora`（v2mini 默认） | 是否要在 UI 暴露所有 5 个 workflow 选择？  |
| 启动失败的日志位置                  | `backend/runtime/logs/app.log`                    | 是否要写到用户桌面？                        |
| 队列默认失败处理策略                | 失败继续下一个（不中断）                          | 是否要默认「任一失败则中断整队」选项？      |
| 队列中单个 job 失败是否重试          | 不自动重试；用户手动「重试该任务」按钮             | 是否需要自动重试 N 次？                     |
| reasoning_effort 高档位的成本        | 默认 high 档慎用，加提示「高档位 token 计费较高」 | 是否需要在前端显示档位成本提示？            |
| GenericInjector 是否支持参数注入     | 仅注入 prompt 文本；其它参数走 workflow 默认      | 是否要支持注入 width/height/steps 等？      |
| 队列中各 item 的 workflow 是否可不同 | 当前设计：同一队列固定一个 workflow                | 是否要支持每 item 不同 workflow？            |