<template>
  <div class="placeholder">
    <el-empty :description="description">
      <template #image>
        <el-icon size="64" color="#909399"><Clock /></el-icon>
      </template>
    </el-empty>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  title: string
  milestone: string
}>()

const description = computed(
  () => `${props.title}功能将在 ${props.milestone} 阶段上线，敬请期待。`
)
</script>

<style scoped>
.placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 60vh;
}
</style>
