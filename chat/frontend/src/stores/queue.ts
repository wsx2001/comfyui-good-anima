/**
 * Queue store — live state of the conversation's active serial queue.
 *
 * One active queue panel at a time (the most recent queue in the current
 * conversation). Subscribes to /api/queues/{id}/events on open() and keeps
 * local state in sync via snapshot + delta events. item.done also appends
 * a synthetic assistant message to the chat store so generated images land
 * in the conversation flow.
 */
import { reactive } from 'vue'
import { ElMessage } from 'element-plus'
import {
  api,
  streamQueueEvents,
  type Queue,
  type QueueItem,
} from '../api/client'
import { useChatStore } from './chat'

interface QueueState_ {
  /** Queue currently shown in the panel (null = no active queue). */
  queue: Queue | null
  connected: boolean
  error: string | null
}

const state = reactive<QueueState_>({
  queue: null,
  connected: false,
  error: null,
})

let controller: AbortController | null = null

export function useQueueStore() {
  const chatStore = useChatStore()

  /**
   * Track a queue (after creation or reload). Replaces any previous
   * subscription. Loads a full snapshot over REST first, then opens SSE.
   */
  async function track(queueId: string) {
    stop()
    try {
      state.queue = await api.getQueue(queueId)
    } catch (e: any) {
      state.error = e.message
      ElMessage.error(`加载队列失败：${e.message}`)
      return
    }
    listen(queueId)
  }

  /**
   * Restore the most recent queue of the conversation (page reload).
   * Terminal queues show statically; active ones re-subscribe to SSE.
   */
  async function restoreForConversation(conversationId: string) {
    stop()
    let q: Queue | null = null
    try {
      q = (await api.getConversationQueue(conversationId)).queue
    } catch {
      return // conversation may not have any queue; panel stays hidden
    }
    if (!q) return
    state.queue = q
    const terminal = !['pending', 'running', 'paused'].includes(q.state)
    if (!terminal) listen(q.id)
  }

  function listen(queueId: string) {
    controller = new AbortController()
    const signal = controller.signal
    ;(async () => {
      try {
        for await (const evt of streamQueueEvents(queueId, signal)) {
          handleEvent(evt.event, evt.data)
        }
        // Server closed (terminal event) — refresh once over REST.
        state.connected = false
        await refresh(queueId)
      } catch (e: any) {
        if (signal.aborted) return
        state.connected = false
        state.error = e?.message || String(e)
      }
    })()
  }

  function stop() {
    if (controller) {
      controller.abort()
      controller = null
    }
    state.queue = null
    state.connected = false
    state.error = null
  }

  async function refresh(queueId: string) {
    try {
      const q = await api.getQueue(queueId)
      if (state.queue?.id === queueId) state.queue = q
    } catch {
      // queue may have been deleted; leave state as-is
    }
  }

  function applyItemUpdate(itemUpdate: Partial<QueueItem> & { item_id?: string; order_index?: number }) {
    const q = state.queue
    if (!q || !itemUpdate.item_id) return
    const idx = q.items.findIndex((it) => it.id === itemUpdate.item_id)
    if (idx === -1) return
    q.items[idx] = {
      ...q.items[idx],
      ...('state' in itemUpdate ? { state: itemUpdate.state as QueueItem['state'] } : {}),
      ...('job_id' in itemUpdate ? { job_id: itemUpdate.job_id ?? null } : {}),
      ...('error' in itemUpdate ? { error: itemUpdate.error ?? null } : {}),
    }
  }

  function handleEvent(event: string, data: any) {
    switch (event) {
      case 'queue.snapshot':
        if (data?.id === state.queue?.id) state.queue = data
        state.connected = true
        return
      case 'queue.state': {
        if (state.queue && data?.state) state.queue.state = data.state
        return
      }
      case 'item.start': {
        if (!state.queue) return
        applyItemUpdate({ item_id: data.item_id, state: 'running' })
        return
      }
      case 'item.done': {
        if (!state.queue) return
        applyItemUpdate({
          item_id: data.item_id,
          state: data.state,
          error: data.error ?? null,
          job_id: data.job_id ?? null,
        })
        // Surface the result in the conversation flow.
        if (Array.isArray(data.images) && data.images.length) {
          chatStore.appendQueueResultMessage({
            content: `🎬 场景${data.scene_label ? `「${data.scene_label}」` : ''}完成，共 ${data.images.length} 张图。`,
            images: data.images,
            jobId: data.job_id,
          })
        } else if (data.state === 'failed') {
          chatStore.appendQueueResultMessage({
            content: `⚠️ 场景${data.scene_label ? `「${data.scene_label}」` : ''}失败：${data.error || '未知错误'}`,
            images: [],
            jobId: data.job_id,
          })
        }
        return
      }
      case 'queue.end': {
        if (state.queue && data?.state) state.queue.state = data.state
        state.connected = false
        return
      }
      case 'queue.updated':
        // A new pending item was appended — refetch for accurate ordering.
        if (state.queue) void refresh(state.queue.id)
        return
    }
  }

  async function pause() {
    if (!state.queue) return
    try {
      await api.pauseQueue(state.queue.id)
    } catch (e: any) {
      ElMessage.error(e.message)
    }
  }

  async function resume() {
    if (!state.queue) return
    try {
      await api.resumeQueue(state.queue.id)
    } catch (e: any) {
      ElMessage.error(e.message)
    }
  }

  async function cancel() {
    if (!state.queue) return
    try {
      await api.cancelQueue(state.queue.id)
    } catch (e: any) {
      ElMessage.error(e.message)
    }
  }

  return { state, track, restoreForConversation, stop, pause, resume, cancel, refresh }
}
