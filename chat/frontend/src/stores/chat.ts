/**
 * Chat store — current conversation's messages and live stream state.
 *
 * Step 2: send() now drives an SSE stream and updates an in-flight
 * "streaming assistant" message in place. Past messages are immutable.
 */
import { reactive, computed } from 'vue'
import { ElMessage } from 'element-plus'
import {
  api,
  streamMessage,
  type Message,
  type StreamEvent,
} from '../api/client'
import type { GalleryImage } from '../components/ImageGallery.vue'
import { useQueueStore } from './queue'
import { useSessionStore } from './session'

/** Message rows may carry live gallery images (queue results, Step 4). */
export type ChatMessage = Message & { images?: GalleryImage[] }

function newIdSuffix(): string {
  return Math.random().toString(36).slice(2, 8)
}

export interface StreamingAssistant {
  id: string // reserved assistant id (from message.start)
  content: string
  reasoning: string
  toolCalls: Array<{ name: string; arguments: unknown }>
  /** Images returned by executed tools (tool.result events), shown live. */
  images: GalleryImage[]
  streaming: boolean
  error: string | null
}

interface ChatState {
  conversationId: string | null
  messages: Message[]
  /** When non-null, an assistant message is being streamed in. */
  streaming: StreamingAssistant | null
  /** True while we're persisting the user message and waiting for first byte. */
  loading: boolean
}

const state = reactive<ChatState>({
  conversationId: null,
  messages: [],
  streaming: null,
  loading: false,
})

export function useChatStore() {
  const sessionStore = useSessionStore()

  async function open(conversationId: string) {
    if (state.conversationId === conversationId) return
    state.conversationId = conversationId
    state.streaming = null
    state.loading = true
    try {
      const detail = await api.getConversation(conversationId)
      state.messages = detail.messages
      sessionStore.setActive(conversationId)
    } catch (e: any) {
      ElMessage.error(`加载会话失败：${e.message}`)
    } finally {
      state.loading = false
    }
  }

  function clear() {
    state.conversationId = null
    state.messages = []
    state.streaming = null
  }

  /**
   * Send a user message and stream the assistant response.
   *
   * Adds the user message to the local list immediately (optimistic),
   * then consumes the SSE stream and updates `state.streaming` chunk
   * by chunk. On message.end the stream is closed and the persisted
   * message replaces the streaming placeholder.
   */
  async function send(content: string, workflow_id?: string) {
    const cid = state.conversationId
    if (!cid) return
    if (!content.trim()) return
    if (state.streaming) {
      ElMessage.warning('上一条消息还在生成中，请稍候')
      return
    }

    state.loading = true
    // Optimistic user message; will be replaced when message.start arrives.
    const tempUserMsg: Message = {
      id: 'temp-user-' + Date.now(),
      role: 'user',
      content,
      reasoning: null,
      job_id: null,
      created_at: new Date().toISOString(),
    }
    state.messages = [...state.messages, tempUserMsg]
    state.streaming = {
      id: 'pending',
      content: '',
      reasoning: '',
      toolCalls: [],
      images: [],
      streaming: true,
      error: null,
    }

    try {
      let realUserMsg: Message | null = null
      for await (const evt of streamMessage(cid, content, workflow_id)) {
        handleEvent(evt, tempUserMsg, (m) => (realUserMsg = m))
      }

      // Reload the conversation to pick up the persisted assistant message
      // (the placeholder streaming row is removed; the real one comes from
      // the server).
      const detail = await api.getConversation(cid)
      state.messages = detail.messages
      state.streaming = null
      sessionStore.touch(cid)
      sessionStore.load()
    } catch (e: any) {
      const msg = e?.message || String(e)
      ElMessage.error(`对话失败：${msg}`)
      if (state.streaming) state.streaming.error = msg
      // Drop the optimistic user message to avoid showing a phantom.
      state.messages = state.messages.filter((m) => m.id !== tempUserMsg.id)
      state.streaming = null
    } finally {
      state.loading = false
    }
  }

  function handleEvent(
    evt: StreamEvent,
    tempUserMsg: Message,
    setRealUser: (m: Message) => void,
  ) {
    switch (evt.type) {
      case 'message.start': {
        // Replace optimistic user message with the real one.
        const realUser: Message = {
          ...tempUserMsg,
          id: evt.data.user_message_id,
        }
        setRealUser(realUser)
        state.messages = state.messages.map((m) => (m.id === tempUserMsg.id ? realUser : m))
        if (state.streaming) state.streaming.id = evt.data.assistant_message_id
        return
      }
      case 'reasoning.delta': {
        if (state.streaming) state.streaming.reasoning += evt.data.delta
        return
      }
      case 'content.delta': {
        if (state.streaming) state.streaming.content += evt.data.delta
        return
      }
      case 'tool.call': {
        if (!state.streaming) return
        const idx = evt.data.index
        while (state.streaming.toolCalls.length <= idx) {
          state.streaming.toolCalls.push({ name: '?', arguments: null })
        }
        state.streaming.toolCalls[idx] = {
          name: evt.data.name,
          arguments: evt.data.arguments,
        }
        return
      }
      case 'tool.result': {
        if (!state.streaming) return
        const result = (evt.data as any)?.result || {}
        if (result.ok && Array.isArray(result.images)) {
          for (const img of result.images) {
            state.streaming.images.push({
              id: img.id,
              url: img.url,
              width: img.width,
              height: img.height,
              seed: img.seed ?? null,
            })
          }
        }
        // A queue was just created — hand it to the queue store so the
        // JobQueuePanel subscribes to its live event stream.
        if (result.ok && result.queue_id) {
          void useQueueStore().track(result.queue_id as string)
        }
        return
      }
      case 'message.end':
      case 'error':
        // Both close the stream — message.end is the success path,
        // error ends it prematurely. Persistence / list reload happens
        // after the iterator returns (see send()).
        return
    }
  }

  /**
   * Append a queue-generated result as an assistant message (Step 4).
   *
   * Queue items finish asynchronously (outside the SSE chat stream); the
   * queue worker persists the text row server-side, and this call surfaces
   * it locally with live image thumbnails. The synthetic id matches no DB
   * row, so a conversation reload replaces it with the persisted version.
   */
  function appendQueueResultMessage(payload: {
    content: string
    images: Array<{ id: string; url: string; width: number; height: number; seed: number | null }>
    jobId?: string | null
  }) {
    const msg: ChatMessage = {
      id: 'queue-' + (payload.jobId ?? newIdSuffix()) + '-' + Date.now(),
      role: 'assistant',
      content: payload.content,
      reasoning: null,
      job_id: payload.jobId ?? null,
      created_at: new Date().toISOString(),
      images: payload.images.map((img) => ({ ...img })),
    }
    state.messages = [...state.messages, msg]
    if (state.conversationId) sessionStore.touch(state.conversationId)
  }

  return {
    state: {
      ...state,
      hasStreaming: computed(() => state.streaming !== null),
    },
    open,
    send,
    clear,
    appendQueueResultMessage,
  }
}