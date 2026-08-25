# ComfyUI Good Anima Chat · 项目主文档

> 配套 [comfyui-good-anima](../README.md) v2mini 的本地 AI 对话生图工具。
>
> 本文档是该新工具的"项目主文档"，用于在团队内部 / 后续开发者之间对齐**定位、边界、模块关系**。产品需求细节见 [PRD.md](./PRD.md)，技术细节见 [TECH.md](./TECH.md)。

---

## 1. 一句话定位

让用户像聊天一样使用 v2mini 生图技能：
**自然语言输入 → 工具调用 v2mini 链路（情境因果 → 三层 prompt → 标签校验 → ComfyUI 执行） → 实时回显生图结果。**

---

## 2. 与 v2mini 的关系

v2mini 是面向 AI 编程助手（Snow / Codex / Claude Code）的 Skills 包，**由 AI 在对话中触发**。本工具是 v2mini 的 **直接用户层**，绕开 AI 编程助手，自己作为 LLM-驱动的前端直接消费 v2mini 链路。

| 维度       | v2mini                                         | 本工具（Chat）                                       |
| ---------- | ---------------------------------------------- | ---------------------------------------------------- |
| 服务对象   | AI 编程助手（agent）                           | 人类创作者（通过浏览器）                             |
| 触发方式   | Agent 读 SKILL.md 自行推理                     | 用户在聊天框说话                                     |
| LLM 提供方 | 由 Agent 隐式提供                              | 用户自配 OpenAI 兼容 API（OpenAI / DeepSeek / 通义等） |
| 工作流执行 | `comfyui-manager`                              | 同上，**复用**                                       |
| 标签校验   | `danbooru-tags`                                | 同上，**复用**                                       |
| 视觉简报 / 三层 prompt | `comfyui-animatool`                  | 同上，**复用**                                       |

**核心原则**：本工具**不重新实现** v2mini 的任何硬约束规则，只把它们以可调用的形式暴露给 LLM，并替用户完成 Agent 原本的工作。

---

## 3. 核心特性（v1 MVP）

1. **对话式生图** — 自然语言描述需求，工具自动生成 prompt 并提交 ComfyUI。
2. **流式响应** — LLM 思考过程以打字效果展示，让用户看到"它在想什么"。
3. **结果画廊** — 生成的图片以缩略图网格呈现，可点开查看大图、原始 prompt、参数字段。
4. **会话历史** — 所有对话持久化在本地 SQLite，可回看、续聊、重生成。
5. **双模式工作流调度** — 默认走 v2mini 5 个 workflow（保持 Anima 硬约束）；高级模式支持导入任意 ComfyUI workflow JSON 并指定 prompt 注入节点。
6. **场景列表串行生图** — 用户在对话中说"依次生成 N 个场景"，工具自动拆解为任务队列、串行逐张生成；每张完成后自动注入下一个 prompt 并继续。
7. **LLM 参数可调** — 上下文保留轮数、max_tokens、temperature、思维深度档位均可调，实时生效。

---

## 4. 非目标（v1 不做）

明确划清边界，避免过度设计：

- ❌ 多用户 / 登录鉴权（**单用户本地**）
- ❌ 远程访问（仅 `localhost`）
- ❌ 画师融合、随机抽卡、图生图（图生图是 M2+）
- ❌ 多 LLM 路由 / 智能切换
- ❌ 工作流画布编辑器（节点拖拽式）
- ❌ 模型 / LoRA 下载管理
- ❌ ComfyUI 队列调度优化（直接复用 comfyui-manager 的提交行为）
- ❌ 自定义节点画布（ComfyUI 那边已经够了）

---

## 5. 目录结构

```
comfyui-good-anima-chat/                  ← 本工具的根目录
├── README.md                             ← 安装与启动
├── docs/
│   ├── PROJECT.md                        ← 本文件
│   ├── PRD.md                            ← 产品需求
│   └── TECH.md                           ← 技术规格
├── backend/
│   ├── pyproject.toml                    ← Python 项目配置
│   ├── app.py                            ← FastAPI 入口
│   ├── api/                              ← REST + SSE 路由
│   ├── services/                         ← 业务逻辑
│   ├── skills/                           ← v2mini skill 调用封装
│   ├── llm/                              ← LLM 适配层
│   ├── storage/                          ← SQLite 数据访问
│   ├── config/                           ← 配置加载
│   └── runtime/                          ← 运行期产物（args、缓存）
├── frontend/
│   ├── package.json
│   ├── src/
│   │   ├── views/                        ← 会话列表 / 对话页
│   │   ├── components/                   ← 消息气泡 / 图片卡片 / 参数面板
│   │   └── store/                        ← Pinia / Zustand 状态
│   └── vite.config.ts
├── launcher/                             ← ComfyUI 自定义节点
│   ├── __init__.py
│   └── chat_launcher.py
└── tests/
    ├── backend/
    └── frontend/
```

> 安装到本地后，整体目录与 `comfyui-good-anima/` **平级**（不在其内部）。它们通过 `COMFYUI_GOOD_ANIMA_SKILLS_DIR` 环境变量解耦。

---

## 6. 关键决策（与背景对照）

| 决策点         | 选择                                  | 理由                                                            |
| -------------- | ------------------------------------- | --------------------------------------------------------------- |
| 部署形态       | 独立 Web 服务                         | 聊天 UX 与节点画布语义不符；进程解耦利于流式响应与未来扩展      |
| 端口           | `127.0.0.1:8787`                      | 避开 ComfyUI 默认 8188 与常见冲突端口                           |
| 用户体系       | 单用户，无登录                        | v1 只服务单机创作者；鉴权会拖慢 MVP                             |
| 持久化         | SQLite（WAL 模式）                    | 单文件，零部署，备份就是复制                                    |
| LLM 接入       | OpenAI 兼容协议                       | 用户可换 DeepSeek / 通义 / Ollama / LM Studio，零迁移成本        |
| ComfyUI 通信   | 沿用 `comfyui-skill` CLI              | 复用 v2mini 已验证的执行链路，不重新实现 worker 协议             |
| 标签校验       | 沿用 `danbooru-tags` Rust CLI          | 复用 v2mini 已验证的锚点校验，不重新实现                         |
| 任务执行模式   | 异步 + 流式（SSE）                    | LLM 流式思考 + ComfyUI 异步执行都不阻塞 UI                      |
| Launcher       | ComfyUI 自定义节点，单按钮跳浏览器    | 给 ComfyUI 用户一个发现入口，不强迫启动顺序                     |
| 工作流执行     | 双模式：v2mini 默认 / 任意 workflow 节点注入 | 兼顾硬约束一致性与灵活性（高级用户）                            |
| 串行生图       | 任务队列 + 自动续行                  | 用户无需手动管理多 prompt 序列                                  |
| Prompt 节点定位 | v2mini 模式自动；自定义模式 UI 选    | 通用 workflow 注入的关键能力                                    |

---

## 7. 文档导航

- 📘 [PRD.md](./PRD.md) — **做什么 / 不做什么 / 验收标准**
- 📐 [TECH.md](./TECH.md) — **怎么做 / 模块 / 接口 / 数据模型 / 里程碑**
- 📖 [v2mini README](../README.md) — 底层技能的完整说明（情境因果、三层 prompt、Danbooru 校验）

---

## 8. 状态

| 项目        | 状态          |
| ----------- | ------------- |
| 项目主文档  | ✅ v1（本文件）|
| PRD         | ✅ v1          |
| TECH        | ✅ v1          |
| 代码骨架    | ⏳ 待 M0      |
| MVP         | ⏳ 待 M1      |

> 状态由里程碑推进更新，详见 [TECH.md §11](./TECH.md)。