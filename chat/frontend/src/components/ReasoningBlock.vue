<template>
  <div class="reasoning-block">
    <div class="header" @click="expanded = !expanded">
      <el-icon class="icon" :class="{ expanded }"><ArrowDown v-if="expanded" /><ArrowRight v-else /></el-icon>
      <span class="label">思维链</span>
      <span class="hint">{{ hint }}</span>
      <span v-if="streaming" class="streaming-indicator">
        <span class="dot"></span> 推流中
      </span>
    </div>
    <div v-show="expanded" class="content" v-html="rendered"></div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowDown, ArrowRight } from '@element-plus/icons-vue'
import { getMarkdown } from '../api/client'

const props = defineProps<{
  text: string
  streaming?: boolean
}>()

const expanded = ref(true)
const rendered = ref('')

const hint = computed(() => {
  const len = props.text.length
  if (!len) return '(空)'
  return `${len} 字`
})

watch(
  () => props.text,
  async (t) => {
    const md = await getMarkdown()
    rendered.value = md.render(t || '*（暂无思维链）*')
  },
  { immediate: true },
)
</script>

<style scoped>
.reasoning-block {
  border: 1px solid #e6a23c;
  background: #fdf6ec;
  border-radius: 6px;
  margin: 8px 0;
  font-size: 13px;
}
.header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  cursor: pointer;
  user-select: none;
  color: #b88230;
}
.header:hover {
  background: #fbecd5;
}
.icon {
  font-size: 12px;
  transition: transform 0.15s ease;
}
.icon.expanded {
  transform: rotate(0deg);
}
.label {
  font-weight: 600;
}
.hint {
  color: #909399;
  font-size: 12px;
}
.streaming-indicator {
  margin-left: auto;
  color: #67c23a;
  font-size: 12px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.dot {
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
.content {
  padding: 8px 12px 12px;
  border-top: 1px solid #faecd0;
  color: #5d4a2c;
  max-height: 320px;
  overflow-y: auto;
  line-height: 1.6;
}
.content :deep(pre) {
  background: #f5f0e6;
  border-radius: 4px;
  padding: 8px;
  overflow-x: auto;
  font-size: 12px;
}
.content :deep(code) {
  background: #f5f0e6;
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 12px;
}
</style>