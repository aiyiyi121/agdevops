<template>
  <div class="app-layout">
    <!-- 侧边栏 -->
    <aside class="sidebar" :class="{ collapsed: appStore.sidebarCollapsed }">
      <div class="sidebar-logo">
        <div class="logo-icon">
          <el-icon><Cpu /></el-icon>
        </div>
        <span class="logo-text">AgDevOps</span>
      </div>
      <nav class="sidebar-nav">
        <router-link
          v-for="item in menuItems"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          :class="{ active: currentRoute === item.name }"
        >
          <el-icon class="nav-icon"><component :is="item.icon" /></el-icon>
          <span class="nav-label">{{ item.title }}</span>
        </router-link>
      </nav>
    </aside>

    <!-- 主内容区 -->
    <div class="main-area">
      <!-- 顶栏 -->
      <header class="header">
        <div class="header-left">
          <button class="collapse-btn" @click="appStore.toggleSidebar">
            <el-icon><Fold v-if="!appStore.sidebarCollapsed" /><Expand v-else /></el-icon>
          </button>
          <span class="breadcrumb">{{ currentTitle }}</span>
        </div>
        <div class="header-right">
          <el-badge :value="3" :max="99">
            <el-icon :size="20" style="cursor:pointer; color: var(--text-secondary)"><Bell /></el-icon>
          </el-badge>
          <el-dropdown>
            <div style="display:flex; align-items:center; gap:8px; cursor:pointer;">
              <el-avatar :size="32" style="background: var(--primary);">
                <el-icon><User /></el-icon>
              </el-avatar>
              <span style="font-size:14px; font-weight:500; color: var(--text-primary);">管理员</span>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item>个人设置</el-dropdown-item>
                <el-dropdown-item divided>退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <!-- 页面内容 -->
      <main class="content">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useAppStore } from '@/stores/app'

const route = useRoute()
const appStore = useAppStore()

const menuItems = [
  { path: '/dashboard',   name: 'Dashboard',   title: '仪表盘',   icon: 'Odometer' },
  { path: '/hosts',       name: 'Hosts',       title: '主机管理', icon: 'Monitor' },
  { path: '/deployments', name: 'Deployments', title: '部署管理', icon: 'Promotion' },
  { path: '/logs',        name: 'Logs',        title: '日志中心', icon: 'Document' },
  { path: '/alerts',      name: 'Alerts',      title: '告警中心', icon: 'Bell' },
  { path: '/users',       name: 'Users',       title: '用户管理', icon: 'User' },
]

const currentRoute = computed(() => route.name)
const currentTitle = computed(() => {
  const item = menuItems.find(m => m.name === route.name)
  return item ? item.title : ''
})
</script>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.25s ease, transform 0.25s ease;
}
.fade-enter-from {
  opacity: 0;
  transform: translateY(8px);
}
.fade-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}
</style>
