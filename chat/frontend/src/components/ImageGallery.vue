<template>
  <div class="image-gallery">
    <div
      v-for="(img, i) in images"
      :key="img.id"
      class="thumb"
      :class="{ failed: img.failed }"
      :title="img.failed ? img.error : `点击查看大图`"
      @click="!img.failed && open(img)"
    >
      <img v-if="!img.failed" :src="img.url" loading="lazy" :alt="`生成图 ${i + 1}`" />
      <div v-else class="failed-box">
        <el-icon size="28"><WarningFilled /></el-icon>
        <span>{{ img.error || '生成失败' }}</span>
      </div>
    </div>

    <ImageLightbox :image="active" @close="close" />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { WarningFilled } from '@element-plus/icons-vue'
import ImageLightbox from './ImageLightbox.vue'

export interface GalleryImage {
  id: string
  url: string
  width: number
  height: number
  seed: number | null
  /** When set the tile renders as a failure placeholder instead of an image. */
  failed?: boolean
  error?: string
}

defineProps<{ images: GalleryImage[] }>()

const active = ref<GalleryImage | null>(null)

function open(img: GalleryImage) {
  active.value = img
}
function close() {
  active.value = null
}
</script>

<style scoped>
.image-gallery {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}
.thumb {
  width: 132px;
  height: 132px;
  border-radius: 6px;
  overflow: hidden;
  cursor: pointer;
  border: 1px solid #ebeef5;
  background: #fafafa;
  display: flex;
  align-items: center;
  justify-content: center;
}
.thumb:hover {
  border-color: #409eff;
}
.thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.thumb.failed {
  cursor: default;
  color: #f56c6c;
}
.failed-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  padding: 8px;
  text-align: center;
}
</style>