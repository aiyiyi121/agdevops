<template>
  <div class="neo-tabs theme-blue log-center-tabs trace-center-tabs event-tabs-shell">
    <button
      v-for="item in tabs"
      :key="item.path"
      type="button"
      class="neo-tab-btn event-tab"
      :class="{ active: route.path === item.path }"
      @click="go(item.path)"
    >
      <el-icon style="margin-right:4px;"><component :is="item.icon" /></el-icon>
      {{ item.title }}
    </button>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Aim, CollectionTag, Share } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const tabs = computed(() => [
  { path: '/events/wall', title: '事件中心', icon: Aim, permission: 'eventwall.view' },
  { path: '/events/environments', title: '事件环境', icon: CollectionTag, permission: 'eventwall.environment.view' },
  { path: '/events/sources', title: '事件源', icon: Share, permission: 'eventwall.source.view' },
].filter(item => authStore.hasPermission(item.permission)))

function go(path) {
  if (route.path !== path) {
    router.push({ path, query: { ...route.query } })
  }
}
</script>

<style scoped>
.event-tabs-shell {
  display: flex;
  width: 100%;
  padding: 4px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 12px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(248, 250, 252, 0.9));
  box-shadow: 0 12px 26px rgba(15, 23, 42, 0.04);
}

.event-tab {
  min-height: 38px;
  padding: 0 20px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: #4e5969;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font-size: 13px;
  font-weight: 700;
  line-height: 1.2;
}

.event-tab:hover {
  background: rgba(51, 112, 255, 0.06);
}

.event-tab.active {
  background: #e8f0ff;
  color: #245bdb;
  box-shadow: inset 0 0 0 1px rgba(51, 112, 255, 0.08);
}

@media (max-width: 700px) {
  .event-tabs-shell {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .event-tab {
    min-width: 0;
  }
}
</style>
