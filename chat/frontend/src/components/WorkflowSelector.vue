<template>
  <el-select
    :model-value="modelValue"
    placeholder="工作流"
    size="small"
    style="width: 260px"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <el-option-group label="v2mini 内置">
      <el-option
        v-for="wf in V2MINI_OPTIONS"
        :key="wf.value"
        :value="wf.value"
        :label="wf.label"
      />
    </el-option-group>
  </el-select>
</template>

<script setup lang="ts">
/**
 * Workflow selector — M1 exposes the five built-in v2mini workflows only.
 * Custom imported ones arrive in M2 (WorkflowsView).
 */
defineProps<{ modelValue: string }>()
defineEmits<{ (e: 'update:modelValue', v: string): void }>()

const V2MINI_OPTIONS = [
  {
    value: 'local/anima-txt2img-aesthetic-lora',
    label: '默认 · 双 LoRA 美学增强',
  },
  {
    value: 'local/anima-txt2img-base',
    label: '裸模型（对比测试）',
  },
  {
    value: 'local/anima-txt2img-aesthetic-lora-artist-mixer',
    label: '画师融合 Artist Mixer',
  },
  {
    value: 'local/anima-txt2img-aesthetic-lora-enhancer',
    label: '加速版 Enhancer（约30%提速）',
  },
  {
    value: 'local/anima-txt2img-aesthetic-lora-fixed',
    label: '固定参数版',
  },
]
</script>