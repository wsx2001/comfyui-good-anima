<template>
  <el-container class="layout">
    <el-aside width="220px" class="sidebar">
      <div class="logo">🎨 Good Anima</div>
      <el-menu
        :default-active="activeRoute"
        router
        class="nav-menu"
      >
        <el-menu-item index="/sessions">
          <el-icon><Document /></el-icon>
          <span>会话</span>
        </el-menu-item>
        <el-menu-item index="/chat" disabled>
          <el-icon><ChatDotRound /></el-icon>
          <span>对话</span>
          <el-tag size="small" type="info" class="ml-1">M1</el-tag>
        </el-menu-item>
        <el-menu-item index="/workflows" disabled>
          <el-icon><Connection /></el-icon>
          <span>工作流</span>
          <el-tag size="small" type="info" class="ml-1">M2</el-tag>
        </el-menu-item>
        <el-menu-item index="/settings">
          <el-icon><Setting /></el-icon>
          <span>设置</span>
        </el-menu-item>
      </el-menu>

      <div class="sidebar-footer">
        <el-text size="small" type="info">v{{ version }}</el-text>
      </div>
    </el-aside>

    <el-main class="main">
      <router-view />
    </el-main>
  </el-container>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const activeRoute = computed(() => route.path)
const version = '0.1.0'
</script>

<style scoped>
.layout {
  height: 100vh;
}
.sidebar {
  background: #fafafa;
  border-right: 1px solid #ebeef5;
  display: flex;
  flex-direction: column;
}
.logo {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  font-weight: 600;
  color: #303133;
  border-bottom: 1px solid #ebeef5;
}
.nav-menu {
  flex: 1;
  border-right: none;
}
.ml-1 {
  margin-left: auto;
}
.sidebar-footer {
  padding: 12px;
  text-align: center;
  border-top: 1px solid #ebeef5;
}
.main {
  padding: 24px;
  background: #fff;
  overflow-y: auto;
}
</style>
