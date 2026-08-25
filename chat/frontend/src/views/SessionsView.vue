<template>
  <div class="sessions-view">
    <div class="page-header">
      <h2 class="page-title">会话</h2>
      <el-button type="primary" :icon="Plus" @click="onCreate" :loading="creating">
        新建会话
      </el-button>
    </div>

    <el-empty v-if="!state.conversations.length && !state.loading" description="还没有会话，点上方按钮新建一个吧" />

    <el-skeleton v-if="state.loading && !state.conversations.length" :rows="5" animated />

    <el-table
      v-else
      :data="state.conversations"
      stripe
      class="session-table"
      :default-sort="{ prop: 'updated_at', order: 'descending' }"
    >
      <el-table-column label="标题" min-width="240">
        <template #default="{ row }">
          <el-link type="primary" :underline="false" @click="onOpen(row.id)">
            {{ row.title || '(无标题)' }}
          </el-link>
        </template>
      </el-table-column>

      <el-table-column label="工作流" width="220">
        <template #default="{ row }">
          <el-tag size="small" type="info">{{ row.default_workflow_id }}</el-tag>
        </template>
      </el-table-column>

      <el-table-column label="创建时间" width="180" sortable prop="created_at">
        <template #default="{ row }">
          {{ formatTime(row.created_at) }}
        </template>
      </el-table-column>

      <el-table-column label="更新时间" width="180" sortable prop="updated_at">
        <template #default="{ row }">
          {{ formatTime(row.updated_at) }}
        </template>
      </el-table-column>

      <el-table-column label="操作" width="180" align="center">
        <template #default="{ row }">
          <el-button size="small" @click="onRename(row)" :icon="Edit">重命名</el-button>
          <el-button size="small" type="danger" @click="onDelete(row)" :icon="Delete" plain>删除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Edit, Delete } from '@element-plus/icons-vue'
import { useSessionStore } from '../stores/session'
import type { ConversationSummary } from '../api/client'

const router = useRouter()
const { state, load, create, rename, remove } = useSessionStore()
const creating = ref(false)

onMounted(load)

function formatTime(iso: string): string {
  const d = new Date(iso)
  const now = Date.now()
  const diff = now - d.getTime()
  if (diff < 60_000) return '刚刚'
  if (diff < 3600_000) return `${Math.floor(diff / 60_000)} 分钟前`
  if (diff < 86400_000) return `${Math.floor(diff / 3600_000)} 小时前`
  return d.toLocaleString('zh-CN', { hour12: false })
}

async function onCreate() {
  creating.value = true
  try {
    const c = await create()
    if (c) router.push({ name: 'chat', query: { cid: c.id } })
  } finally {
    creating.value = false
  }
}

async function onOpen(id: string) {
  router.push({ name: 'chat', query: { cid: id } })
}

async function onRename(row: ConversationSummary) {
  try {
    const { value } = await ElMessageBox.prompt('新的会话标题', '重命名', {
      inputValue: row.title,
      inputValidator: (v) => (v && v.trim() ? true : '标题不能为空'),
      confirmButtonText: '保存',
      cancelButtonText: '取消',
    })
    await rename(row.id, value.trim())
    ElMessage.success('已重命名')
  } catch {
    // user cancelled
  }
}

async function onDelete(row: ConversationSummary) {
  try {
    await ElMessageBox.confirm(
      `确定删除「${row.title || '(无标题)'}」？消息记录也会一并删除。`,
      '删除会话',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
    await remove(row.id)
    ElMessage.success('已删除')
  } catch {
    // user cancelled
  }
}
</script>

<style scoped>
.sessions-view {
  max-width: 1100px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.page-title {
  margin: 0;
  font-weight: 600;
}
.session-table {
  border-radius: 4px;
}
</style>