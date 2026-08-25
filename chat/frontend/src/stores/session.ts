/**
 * Session store — list of conversations + active selection.
 *
 * Reactive module-level singleton (no Pinia). Components import
 * `useSessionStore()` and destructure; mutations trigger re-renders
 * everywhere because it's a single shared `reactive()`.
 */
import { reactive } from 'vue'
import { ElMessage } from 'element-plus'
import { api, type ConversationSummary } from '../api/client'

interface SessionState {
  conversations: ConversationSummary[]
  activeId: string | null
  loading: boolean
}

const state = reactive<SessionState>({
  conversations: [],
  activeId: null,
  loading: false,
})

export function useSessionStore() {
  async function load() {
    state.loading = true
    try {
      state.conversations = await api.listConversations()
    } catch (e: any) {
      ElMessage.error(`加载会话列表失败：${e.message}`)
    } finally {
      state.loading = false
    }
  }

  async function create(title?: string): Promise<ConversationSummary | null> {
    try {
      const c = await api.createConversation({ title })
      state.conversations.unshift(c)
      state.activeId = c.id
      return c
    } catch (e: any) {
      ElMessage.error(`创建会话失败：${e.message}`)
      return null
    }
  }

  async function rename(id: string, title: string) {
    try {
      await api.patchConversation(id, { title })
      const idx = state.conversations.findIndex((c) => c.id === id)
      if (idx >= 0) {
        state.conversations[idx] = { ...state.conversations[idx], title }
      }
    } catch (e: any) {
      ElMessage.error(`重命名失败：${e.message}`)
    }
  }

  async function remove(id: string) {
    try {
      await api.deleteConversation(id)
      state.conversations = state.conversations.filter((c) => c.id !== id)
      if (state.activeId === id) state.activeId = null
    } catch (e: any) {
      ElMessage.error(`删除失败：${e.message}`)
    }
  }

  function setActive(id: string | null) {
    state.activeId = id
  }

  function touch(id: string) {
    // Bump a conversation to the top of the list after a new message.
    const idx = state.conversations.findIndex((c) => c.id === id)
    if (idx > 0) {
      const item = state.conversations.splice(idx, 1)[0]
      state.conversations.unshift(item)
    }
  }

  return { state, load, create, rename, remove, setActive, touch }
}