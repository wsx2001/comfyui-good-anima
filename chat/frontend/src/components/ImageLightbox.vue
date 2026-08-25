<template>
  <teleport to="body">
    <div v-if="image" class="lightbox-mask" @click.self="$emit('close')">
      <div class="lightbox">
        <div class="toolbar">
          <span class="meta">
            {{ image.width }}×{{ image.height }}
            <template v-if="image.seed !== null"> · seed {{ image.seed }}</template>
          </span>
          <div class="actions">
            <el-button size="small" @click="download">下载</el-button>
            <el-button size="small" text @click="$emit('close')">关闭 ✕</el-button>
          </div>
        </div>
        <img :src="image.url" :alt="image.id" />
      </div>
    </div>
  </teleport>
</template>

<script setup lang="ts">
import type { GalleryImage } from './ImageGallery.vue'

const props = defineProps<{ image: GalleryImage | null }>()
defineEmits<{ (e: 'close'): void }>()

function download() {
  if (!props.image) return
  // Same-origin URL; trigger a browser download.
  const link = document.createElement('a')
  link.href = props.image.url
  link.download = `${props.image.id}.png`
  link.click()
}
</script>

<style scoped>
.lightbox-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.72);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
}
.lightbox {
  max-width: 92vw;
  max-height: 92vh;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: #e5eaf3;
}
.meta {
  font-size: 13px;
}
.lightbox img {
  max-width: 92vw;
  max-height: 84vh;
  object-fit: contain;
  border-radius: 6px;
}
</style>