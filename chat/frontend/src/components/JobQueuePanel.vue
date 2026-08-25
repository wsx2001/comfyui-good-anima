<template>
  <div v-if="state.queue" class="queue-panel">
    <div class="panel-header">
      <div class="header-left">
        <el-icon :size="16"><VideoPlay /></el-icon>
        <span class="title">{{ state.queue.title || '场景队列' }}</span>
        <el-tag :type="stateTagType" size="small">{{ stateLabel }}</el-tag>
      </div>
      <div class="header-actions">
        <el-button
          v-if="isActive"
          size="small"
          :icon="state.queue.state === 'paused' ? VideoPlay : VideoPause"
          @click="state.queue.state === 'paused' ? store.resume() : store.pause()"
        >
          {{ state.queue.state === 'paused' ? '恢复' : '暂停' }}
        </el-button>
        <el-button v-if="isActive" size="small" type="danger" plain @click="onCancel">
          取消队列
        </el-button>
        <el-button size="small" link @click="collapsed = !collapsed">
          {{ collapsed ? '展开' : '收起' }}
        </el-button>
      </div>
    </div>

    <div v-show="!collapsed" class="progress-row">
      <el-progress
        :percentage="progressPct"
        :status="progressStatus"
        :stroke-width="6"
      />
      <span class="progress-text">{{ doneCount }}/{{ state.queue.items.length }}</span>
    </div>

    <div v-show="!collapsed" class="item-list">
      <div
        v-for="it in state.queue.items"
        :key="it.id"
        class="queue-item"
        :class="'item--' + it.state"
      >
        <span class="order">#{{ it.order_index + 1 }}</span>
        <span class="label" :title="it.scene_label || it.prompt_11">
          {{ it.scene_label || truncate(it.prompt_11, 40) }}
        </span>
        <el-icon v-if="it.state === 'running'" class="spin"><Loading /></el-icon>
        <el-tag v-else :type="itemTagType(it.state)" size="small" effect="plain">
          {{ itemLabel(it.state) }}
        </el-tag>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import { Loading, VideoPause, VideoPlay } from '@element-plus/icons-vue'
import type { QueueItemState } from '../api/client'
import { useQueueStore } from '../stores/queue'

const store = useQueueStore()
const { state } = store

const collapsed = ref(false)

const isActive = computed(
  () =>
    !!state.queue &&
    ['pending', 'running', 'paused'].includes(state.queue.state),
)

const doneCount = computed(
  () => state.queue?.items.filter((it) => it.state !== 'pending' && it.state !== 'running').length ?? 0,
)
const progressPct = computed(() => {
  const total = state.queue?.items.length ?? 0
  return total ? Math.round((doneCount.value / total) * 100) : 0
})
const progressStatus = computed(() => {
  const s = state.queue?.state
  if (s === 'failed') return 'exception'
  if (s === 'completed') return 'success'
  if (doneCount.value === (state.queue?.items.length ?? 0)) return 'success' as const
  return undefined
})

const stateTagType = computed(() => {
  switch (state.queue?.state) {
    case 'running':
    case 'pending':
      return 'primary'
    case 'paused':
      return 'warning'
    case 'completed':
      return 'success'
    case 'failed':
    case 'cancelled':
      return 'danger'
    default:
      return 'info'
  }
})

const stateLabel = computed(() => {
  const map: Record<string, string> = {
    pending: '等待中',
    running: '执行中',
    paused: '已暂停',
    completed: '已完成',
    cancelled: '已取消',
    failed: '已失败',
  }
  return map[state.queue?.state ?? ''] ?? state.queue?.state
})

function itemTagType(s: QueueItemState) {
  switch (s) {
    case 'running':
      return 'primary'
    case 'done':
      return 'success'
    case 'failed':
      return 'danger'
    case 'skipped':
      return 'info'
    default:
      return 'info'
  }
}

function itemLabel(s: QueueItemState): string {
  const map: Record<QueueItemState, string> = {
    pending: '排队',
    running: '生成中',
    done: '完成',
    failed: '失败',
    skipped: '跳过',
  }
  return map[s]
}

function truncate(text: string, n: number): string {
  return text.length > n ? text.slice(0, n) + '…' : text
}

async function onCancel() {
  try {
    await ElMessageBox.confirm('取消后剩余场景将跳过，正在生成的图会中断。确定？', '取消队列', {
      confirmButtonText: '确定取消',
      cancelButtonText: '继续生成',
      type: 'warning',
    })
  } catch {
    return
  }
  await store.cancel()
}
</script>

<style scoped>
.queue-panel {
  border: 1px solid #d9ecff;
  background: #f4f9ff;
  border-radius: 8px;
  padding: 10px 12px;
  margin-top: 8px;
}
.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.header-actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}
.progress-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 8px;
}
.progress-row .el-progress {
  flex: 1;
}
.progress-text {
  font-size: 12px;
  color: #909399;
  white-space: nowrap;
}
.item-list {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 220px;
  overflow-y: auto;
}
.queue-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  padding: 3px 6px;
  border-radius: 4px;
  background: #fff;
  border: 1px solid #ebeef5;
}
.queue-item .order {
  color: #909399;
  width: 26px;
  flex-shrink: 0;
}
.queue-item .label {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: #606266;
}
.queue-item.item--running {
  border-color: #409eff;
  background: #f0f7ff;
}
.queue-item.item--done .label {
  color: #67c23a;
}
.queue-item.item--failed .label,
.queue-item.item--skipped .label {
  color: #c0c4cc;
  text-decoration: line-through;
}
.spin {
  animation: rotate 1s linear infinite;
  color: #409eff;
}
@keyframes rotate {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
