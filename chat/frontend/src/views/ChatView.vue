<template>
  <div class="chat-view">
    <div class="chat-header">
      <el-button :icon="ArrowLeft" link @click="onBack">返回会话列表</el-button>
      <h3 class="title">{{ title }}</h3>
      <span class="meta" v-if="state.conversationId">
        {{ state.messages.length }} 条消息
      </span>
    </div>

    <div class="messages" ref="messagesRef" v-if="state.conversationId">
      <div v-if="!state.messages.length && !state.streaming" class="empty-hint">
        还没有消息，发条消息开始聊天吧。
      </div>

      <!-- Persisted messages -->
      <MessageBubble v-for="m in state.messages" :key="m.id" :message="m" />

      <!-- Live serial-queue progress (Step 4) -->
      <JobQueuePanel v-if="queueStore.state.queue" />

      <!-- Live streaming assistant -->
      <div v-if="state.streaming" class="message message--assistant streaming">
        <div class="avatar">
          <el-avatar :size="32" style="background: #67c23a">AI</el-avatar>
        </div>
        <div class="bubble">
          <div class="meta">
            <span class="role">Good Anima</span>
            <span class="status">
              <span class="dot" v-if="state.streaming.streaming"></span>
              {{ state.streaming.streaming ? '生成中…' : '完成' }}
            </span>
          </div>

          <!-- Reasoning (Markdown) -->
          <ReasoningBlock
            v-if="state.streaming.reasoning"
            :text="state.streaming.reasoning"
            :streaming="state.streaming.streaming"
          />

          <!-- Content (Markdown) -->
          <div v-if="state.streaming.content" class="assistant-content" v-html="renderedContent"></div>

          <!-- Tool calls -->
          <div v-if="state.streaming.toolCalls.length" class="tool-calls">
            <el-alert
              v-for="(tc, i) in state.streaming.toolCalls"
              :key="i"
              :title="`已调用工具：${tc.name}`"
              type="info"
              show-icon
              :closable="false"
              class="tool-call-alert"
            >
              <pre class="tool-args">{{ formatJson(tc.arguments) }}</pre>
            </el-alert>
          </div>

          <!-- Live images from executed tools -->
          <ImageGallery
            v-if="state.streaming.images.length"
            :images="state.streaming.images"
          />

          <div v-if="state.streaming.error" class="error-text">
            <el-alert :title="state.streaming.error" type="error" :closable="false" show-icon />
          </div>
        </div>
      </div>
    </div>

    <div class="messages-placeholder" v-else>
      <el-empty description="还没选会话">
        <el-button type="primary" @click="onBack">去会话列表</el-button>
      </el-empty>
    </div>

    <div class="composer" v-if="state.conversationId">
      <el-input
        v-model="draft"
        type="textarea"
        :rows="3"
        :autosize="{ minRows: 2, maxRows: 6 }"
        placeholder="输入消息…"
        :disabled="state.streaming !== null"
        @keydown.enter.exact.prevent="onSend"
      />
      <div class="composer-actions">
        <WorkflowSelector v-model="selectedWorkflow" />
        <el-text size="small" type="info">
          {{ state.streaming ? '生成中，按下方按钮取消' : 'Enter 发送 · Shift+Enter 换行' }}
        </el-text>
        <el-button v-if="!state.streaming" type="primary" @click="onSend" :loading="state.loading">
          发送
        </el-button>
        <el-button v-else disabled>生成中…</el-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft } from '@element-plus/icons-vue'
import MessageBubble from '../components/MessageBubble.vue'
import ReasoningBlock from '../components/ReasoningBlock.vue'
import ImageGallery from '../components/ImageGallery.vue'
import WorkflowSelector from '../components/WorkflowSelector.vue'
import JobQueuePanel from '../components/JobQueuePanel.vue'
import { useChatStore } from '../stores/chat'
import { useSessionStore } from '../stores/session'
import { useQueueStore } from '../stores/queue'
import { getMarkdown } from '../api/client'

const route = useRoute()
const router = useRouter()
const chatStore = useChatStore()
const sessionStore = useSessionStore()
const queueStore = useQueueStore()

const draft = ref('')
const messagesRef = ref<HTMLElement | null>(null)
const selectedWorkflow = ref('local/anima-txt2img-aesthetic-lora')
const { state } = chatStore
const renderedContent = ref('')

const cid = computed(() => route.query.cid as string | undefined)
const title = computed(() => {
  const c = sessionStore.state.conversations.find((x) => x.id === cid.value)
  return c?.title || '对话'
})

async function openIfNeeded() {
  if (cid.value) {
    await chatStore.open(cid.value)
    // Restore the queue panel for this conversation (page reload case).
    await queueStore.restoreForConversation(cid.value)
  } else {
    chatStore.clear()
    queueStore.stop()
  }
}

onMounted(async () => {
  await sessionStore.load()
  await openIfNeeded()
})

onUnmounted(() => {
  // Drop the SSE subscription when leaving the conversation.
  queueStore.stop()
})

watch(cid, openIfNeeded)

watch(
  () => state.streaming?.content,
  async (c) => {
    if (c === undefined) {
      renderedContent.value = ''
      return
    }
    const md = await getMarkdown()
    renderedContent.value = md.render(c)
  },
  { immediate: true },
)

// Auto-scroll on new content (messages or stream chunks).
watch(
  () => [state.messages.length, state.streaming?.content.length ?? 0, state.streaming?.reasoning.length ?? 0],
  async () => {
    await nextTick()
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  },
)

async function onSend() {
  const text = draft.value.trim()
  if (!text) return
  if (queueStore.state.queue) {
    // Reset panel tracking so a new queue in this conversation takes over.
    queueStore.stop()
  }
  draft.value = ''
  await chatStore.send(text, selectedWorkflow.value || undefined)
}

function onBack() {
  router.push({ name: 'sessions' })
}

function formatJson(obj: unknown): string {
  try {
    return JSON.stringify(obj, null, 2)
  } catch {
    return String(obj)
  }
}
</script>

<style scoped>
.chat-view {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 48px);
  max-width: 900px;
  margin: 0 auto;
}
.chat-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid #ebeef5;
}
.title {
  margin: 0;
  flex: 1;
  font-weight: 600;
  font-size: 16px;
}
.meta {
  color: #909399;
  font-size: 12px;
}
.messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px 0;
}
.messages-placeholder {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}
.empty-hint {
  text-align: center;
  color: #909399;
  padding: 40px 0;
}
.composer {
  border-top: 1px solid #ebeef5;
  padding-top: 12px;
}
.composer-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 8px;
}

/* Streaming bubble (duplicates MessageBubble styles; scoped only here) */
.message {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}
.message--assistant .bubble {
  max-width: 80%;
  padding: 12px 16px;
  background: #f5f7fa;
  border: 1px solid #ebeef5;
  border-radius: 8px;
}
.message--assistant.streaming .bubble {
  border-color: #67c23a;
  background: #f0f9eb;
}
.bubble .meta {
  display: flex;
  gap: 8px;
  font-size: 12px;
  color: #909399;
  margin-bottom: 6px;
}
.bubble .meta .status {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.bubble .meta .dot {
  width: 6px;
  height: 6px;
  background: #67c23a;
  border-radius: 50%;
  animation: pulse 1s ease-in-out infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}
.assistant-content {
  white-space: normal;
  line-height: 1.6;
}
.assistant-content :deep(pre) {
  background: #f0f0f0;
  border-radius: 4px;
  padding: 8px;
  overflow-x: auto;
  font-size: 12px;
}
.assistant-content :deep(code) {
  background: #f0f0f0;
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 12px;
}
.tool-calls {
  margin-top: 8px;
}
.tool-call-alert {
  margin-top: 6px;
}
.tool-args {
  background: #fafafa;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 6px 8px;
  font-size: 11px;
  max-height: 120px;
  overflow: auto;
  margin: 4px 0 0;
  white-space: pre-wrap;
}
.error-text {
  margin-top: 8px;
}
</style>