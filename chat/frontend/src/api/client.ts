/**
 * Tiny fetch wrapper. All API calls return parsed JSON or throw.
 * 4xx / 5xx responses throw an Error with the body message.
 */

import type MarkdownIt from 'markdown-it'

const BASE = '' // Same-origin (Vite proxy in dev, FastAPI in prod)

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(BASE + path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init.headers || {}),
    },
  })
  if (!res.ok) {
    let msg = `HTTP ${res.status}`
    try {
      const body = await res.json()
      msg = body.detail || body.message || msg
    } catch {
      // body wasn't JSON; ignore
    }
    throw new ApiError(res.status, msg)
  }
  return res.json() as Promise<T>
}

export interface ServerSettings {
  host: string
  port: number
}

export interface ComfyUISettings {
  skills_root: string
  workspace: string
  config_json: string
}

export type ReasoningEffort = 'off' | 'low' | 'medium' | 'high'

export interface LLMSettings {
  base_url: string
  api_key: string
  model: string
  temperature: number
  max_tokens: number
  reasoning_effort: ReasoningEffort
  context_window: number
}

export interface StorageSettings {
  db_path: string
  outputs_dir: string
}

export interface SystemPromptSettings {
  v2mini_animatool_path: string
  v2mini_danbooru_path: string
  v2mini_manager_path: string
}

export interface Settings {
  server: ServerSettings
  comfyui: ComfyUISettings
  llm: LLMSettings
  storage: StorageSettings
  system_prompt: SystemPromptSettings
}

export interface HealthInfo {
  status: string
  db_ok: boolean
  comfyui_reachable: boolean
  llm_configured: boolean
  version: string
}

export interface TestLLMResult {
  ok: boolean
  model?: string
  latency_ms?: number
  error_code?: string
  error_message?: string
}

// ---------------------------------------------------------------------------
// M1 — Chat types
// ---------------------------------------------------------------------------

export interface ConversationSummary {
  id: string
  title: string
  default_workflow_id: string
  created_at: string
  updated_at: string
}

export interface ConversationDetail extends ConversationSummary {
  messages: Message[]
}

export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  reasoning: string | null
  job_id: string | null
  created_at: string
}

export interface MessagePair {
  user: Message
  assistant: Message
}

export interface JobImage {
  id: string
  file_path: string
  width: number
  height: number
  seed: number | null
}

export interface Job {
  id: string
  conversation_id: string
  message_id: string | null
  queue_item_id: string | null
  prompt_id: string | null
  workflow_id: string
  injector_mode: string
  args_snapshot: string
  state: string
  error: string | null
  source: string
  created_at: string
  finished_at: string | null
  images: JobImage[]
}

export interface ImageInfo {
  id: string
  job_id: string
  file_path: string
  width: number
  height: number
  seed: number | null
  created_at: string
  url: string
}

// ---------------------------------------------------------------------------
// M1 Step 4 — Queues
// ---------------------------------------------------------------------------

export type QueueState = 'pending' | 'running' | 'paused' | 'completed' | 'cancelled' | 'failed'
export type QueueItemState = 'pending' | 'running' | 'done' | 'failed' | 'skipped'

export interface QueueItem {
  id: string
  order_index: number
  scene_label: string | null
  prompt_11: string
  prompt_12: string
  args: string
  state: QueueItemState
  job_id: string | null
  error: string | null
}

export interface Queue {
  id: string
  conversation_id: string
  workflow_id: string
  state: QueueState
  title: string | null
  created_at: string
  finished_at: string | null
  items: QueueItem[]
}

export interface QueueCreated {
  id: string
  state: string
  item_count: number
}

export type QueueEventName =
  | 'queue.snapshot'
  | 'queue.state'
  | 'item.start'
  | 'item.done'
  | 'queue.end'
  | 'queue.updated'

export interface QueueStreamEvent {
  event: QueueEventName
  data: any
}

// ---------------------------------------------------------------------------
// M1 Step 2 — SSE event types
// ---------------------------------------------------------------------------

export interface SSEMessageStart {
  user_message_id: string
  assistant_message_id: string
}
export interface SSEReasoningDelta {
  delta: string
}
export interface SSEContentDelta {
  delta: string
}
export interface SSEToolCall {
  index: number
  id: string
  name: string
  arguments: unknown
}
export interface SSEToolResult {
  index: number
  name: string
  result: {
    ok: boolean
    error?: string
    job_id?: string
    final_state?: string
    images?: Array<{ id: string; url: string; width: number; height: number; seed: number | null }>
    [key: string]: unknown
  }
}
export interface SSEMessageEnd {
  finish_reason: string | null
  tool_calls_count?: number
}
export interface SSEError {
  message: string
  code: string
}

export type StreamEvent =
  | { type: 'message.start'; data: SSEMessageStart }
  | { type: 'reasoning.delta'; data: SSEReasoningDelta }
  | { type: 'content.delta'; data: SSEContentDelta }
  | { type: 'tool.call'; data: SSEToolCall }
  | { type: 'tool.result'; data: SSEToolResult }
  | { type: 'message.end'; data: SSEMessageEnd }
  | { type: 'error'; data: SSEError }

/** Parse one SSE message block. Returns event + data, or null for heartbeats. */
export function parseSSEBlock(block: string): { event: string; data: any } | null {
  let event = 'message'
  const dataLines: string[] = []
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) {
      event = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trim())
    }
    // empty line / comments ignored
  }
  if (!dataLines.length) return null
  const dataStr = dataLines.join('\n')
  try {
    return { event, data: JSON.parse(dataStr) }
  } catch {
    return { event, data: dataStr }
  }
}

// ---------------------------------------------------------------------------
// API methods
// ---------------------------------------------------------------------------

export const api = {
  getHealth: () => request<HealthInfo>('/api/health'),

  getSettings: () => request<Settings>('/api/settings'),
  putSettings: (s: Settings) =>
    request<{ ok: boolean }>('/api/settings', {
      method: 'PUT',
      body: JSON.stringify(s),
    }),
  reloadSettings: () =>
    request<{ ok: boolean }>('/api/settings/reload', { method: 'POST' }),

  testLLM: (override?: { base_url?: string; api_key?: string; model?: string; timeout?: number }) =>
    request<TestLLMResult>('/api/settings/test_llm', {
      method: 'POST',
      body: JSON.stringify(override ?? {}),
    }),

  // Conversations
  listConversations: () => request<ConversationSummary[]>('/api/conversations'),
  createConversation: (body: { title?: string; default_workflow_id?: string } = {}) =>
    request<ConversationSummary>('/api/conversations', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  getConversation: (id: string) => request<ConversationDetail>(`/api/conversations/${id}`),
  patchConversation: (id: string, body: { title?: string; default_workflow_id?: string }) =>
    request<{ ok: boolean; conversation: ConversationSummary }>(`/api/conversations/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  deleteConversation: (id: string) =>
    request<{ ok: boolean }>(`/api/conversations/${id}`, { method: 'DELETE' }),

  // Messages (Step 1 list-only; Step 2 streaming send below)
  listMessages: (conversationId: string) =>
    request<Message[]>(`/api/conversations/${conversationId}/messages`),

  // Jobs
  getJob: (id: string) => request<Job>(`/api/jobs/${id}`),
  cancelJob: (id: string) =>
    request<{ ok: boolean }>(`/api/jobs/${id}/cancel`, { method: 'POST' }),

  // Queues (Step 4)
  createQueue: (body: {
    conversation_id: string
    workflow_id?: string
    title?: string
    items: Array<{ scene_label?: string; prompt_11: string; prompt_12: string; args?: Record<string, unknown> }>
  }) =>
    request<QueueCreated>('/api/queues', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  getQueue: (id: string) => request<Queue>(`/api/queues/${id}`),
  getConversationQueue: (convId: string) =>
    request<{ queue: Queue | null }>(`/api/conversations/${convId}/queue`),
  pauseQueue: (id: string) =>
    request<{ ok: boolean }>(`/api/queues/${id}/pause`, { method: 'POST' }),
  resumeQueue: (id: string) =>
    request<{ ok: boolean }>(`/api/queues/${id}/resume`, { method: 'POST' }),
  cancelQueue: (id: string) =>
    request<{ ok: boolean }>(`/api/queues/${id}/cancel`, { method: 'POST' }),
  appendQueueItem: (
    id: string,
    body: { scene_label?: string; prompt_11: string; prompt_12: string; args?: Record<string, unknown> },
  ) =>
    request<{ ok: boolean; item: { id: string; order_index: number } }>(`/api/queues/${id}/items`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  // Images
  getImageInfo: (id: string) => request<ImageInfo>(`/api/images/${id}/info`),
}

// ---------------------------------------------------------------------------
// Streaming send (Step 2)
//
// The body must be POSTed and we want a ReadableStream of SSE events.
// EventSource doesn't support POST, so we use fetch + ReadableStream.
// ---------------------------------------------------------------------------

export async function* streamMessage(
  conversationId: string,
  content: string,
  workflow_id?: string,
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const res = await fetch(`${BASE}/api/conversations/${conversationId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ content, workflow_id }),
    signal,
  })

  if (!res.ok) {
    let msg = `HTTP ${res.status}`
    try {
      const body = await res.json()
      msg = body.detail || body.message || msg
    } catch {
      // ignore
    }
    throw new ApiError(res.status, msg)
  }
  if (!res.body) {
    throw new ApiError(500, 'No response body')
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      // SSE messages are separated by a blank line. Split off complete blocks.
      let idx: number
      // eslint-disable-next-line no-cond-assign
      while ((idx = buffer.indexOf('\n\n')) !== -1) {
        const block = buffer.slice(0, idx)
        buffer = buffer.slice(idx + 2)
        const parsed = parseSSEBlock(block)
        if (!parsed) continue
        yield { type: parsed.event as StreamEvent['type'], data: parsed.data } as StreamEvent
      }
    }
    // Flush trailing block without the trailing blank line.
    if (buffer.trim()) {
      const parsed = parseSSEBlock(buffer)
      if (parsed) {
        yield { type: parsed.event as StreamEvent['type'], data: parsed.data } as StreamEvent
      }
    }
  } finally {
    try {
      reader.releaseLock()
    } catch {
      // ignore
    }
  }
}

// ---------------------------------------------------------------------------
// Queue event stream (Step 4)
//
// GET-based SSE — EventSource works here, but we reuse fetch/ReadableStream
// for consistent parsing and easy cleanup.
// ---------------------------------------------------------------------------

export async function* streamQueueEvents(
  queueId: string,
  signal?: AbortSignal,
): AsyncGenerator<QueueStreamEvent> {
  const res = await fetch(`${BASE}/api/queues/${queueId}/events`, {
    headers: { Accept: 'text/event-stream' },
    signal,
  })
  if (!res.ok) {
    let msg = `HTTP ${res.status}`
    try {
      const body = await res.json()
      msg = body.detail || msg
    } catch {
      // ignore
    }
    throw new ApiError(res.status, msg)
  }
  if (!res.body) throw new ApiError(500, 'No response body')

  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let idx: number
      // eslint-disable-next-line no-cond-assign
      while ((idx = buffer.indexOf('\n\n')) !== -1) {
        const block = buffer.slice(0, idx)
        buffer = buffer.slice(idx + 2)
        if (!block.trim() || block.startsWith(':')) continue // heartbeat
        const parsed = parseSSEBlock(block)
        if (!parsed) continue
        yield { event: parsed.event as QueueEventName, data: parsed.data }
      }
    }
  } finally {
    try {
      reader.releaseLock()
    } catch {
      // ignore
    }
  }
}

// ---------------------------------------------------------------------------
// Markdown renderer (lazy singleton)
// ---------------------------------------------------------------------------

let _md: MarkdownIt | null = null
export async function getMarkdown(): Promise<MarkdownIt> {
  if (_md) return _md
  const MarkdownItModule = await import('markdown-it')
  const MarkdownIt = MarkdownItModule.default
  _md = new MarkdownIt({
    html: false,
    linkify: true,
    breaks: true,
    typographer: false,
  })
  return _md
}