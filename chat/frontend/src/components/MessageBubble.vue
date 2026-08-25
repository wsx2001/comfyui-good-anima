<template>
  <div :class="['message', `message--${message.role}`]">
    <div class="avatar">
      <el-avatar :size="32" :style="{ background: avatarBg }">
        {{ avatarText }}
      </el-avatar>
    </div>
    <div class="bubble">
      <div class="meta">
        <span class="role">{{ roleLabel }}</span>
        <span class="time">{{ relativeTime }}</span>
      </div>

      <ReasoningBlock v-if="message.reasoning" :text="message.reasoning" />

      <!-- Render assistant content as Markdown; user content as plain text. -->
      <div v-if="isAssistant" class="content md" v-html="rendered"></div>
      <div v-else class="content">{{ message.content }}</div>

      <!-- Queue-generated images (Step 4: live queue result messages). -->
      <ImageGallery v-if="galleryImages.length" :images="galleryImages" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { getMarkdown } from '../api/client'
import type { ChatMessage } from '../stores/chat'
import ReasoningBlock from './ReasoningBlock.vue'
import ImageGallery from './ImageGallery.vue'

const props = defineProps<{
  message: ChatMessage
}>()

const galleryImages = computed(() => props.message.images ?? [])

const isUser = computed(() => props.message.role === 'user')
const isAssistant = computed(() => props.message.role === 'assistant')

const avatarText = computed(() => {
  if (isUser.value) return '我'
  if (isAssistant.value) return 'AI'
  return '⚙'
})

const avatarBg = computed(() => {
  if (isUser.value) return '#409eff'
  if (isAssistant.value) return '#67c23a'
  return '#909399'
})

const roleLabel = computed(() => {
  if (isUser.value) return '我'
  if (isAssistant.value) return 'Good Anima'
  return props.message.role
})

const relativeTime = computed(() => {
  const t = new Date(props.message.created_at).getTime()
  const diff = Date.now() - t
  if (diff < 60_000) return '刚刚'
  if (diff < 3600_000) return `${Math.floor(diff / 60_000)} 分钟前`
  if (diff < 86400_000) return `${Math.floor(diff / 3600_000)} 小时前`
  return new Date(props.message.created_at).toLocaleString('zh-CN')
})

const rendered = ref('')
watch(
  () => props.message.content,
  async (c) => {
    const md = await getMarkdown()
    rendered.value = md.render(c || '')
  },
  { immediate: true },
)
</script>

<style scoped>
.message {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}
.message--user {
  flex-direction: row-reverse;
}
.message--user .bubble {
  background: #ecf5ff;
  border-color: #d9ecff;
}
.message--user .meta {
  justify-content: flex-end;
}
.bubble {
  max-width: 70%;
  padding: 12px 16px;
  background: #f5f7fa;
  border: 1px solid #ebeef5;
  border-radius: 8px;
}
.meta {
  display: flex;
  gap: 8px;
  font-size: 12px;
  color: #909399;
  margin-bottom: 6px;
}
.content {
  white-space: pre-wrap;
  word-wrap: break-word;
  line-height: 1.6;
}
.content.md {
  white-space: normal;
}
.content.md :deep(pre) {
  background: #f0f0f0;
  border-radius: 4px;
  padding: 8px;
  overflow-x: auto;
  font-size: 12px;
}
.content.md :deep(code) {
  background: #f0f0f0;
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 12px;
}
.avatar {
  flex-shrink: 0;
}
</style>