<template>
  <div class="dashboard fade-in">
    <!-- 统计卡片 -->
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-icon primary">
          <el-icon :size="24"><Monitor /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ stats.hosts?.total || 0 }}</div>
          <div class="stat-label">主机总数</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon success">
          <el-icon :size="24"><CircleCheck /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ stats.hosts?.online || 0 }}</div>
          <div class="stat-label">在线主机</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon info">
          <el-icon :size="24"><Promotion /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ stats.deployments?.total || 0 }}</div>
          <div class="stat-label">部署次数</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon danger">
          <el-icon :size="24"><Bell /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ stats.alerts?.unacknowledged || 0 }}</div>
          <div class="stat-label">未处理告警</div>
        </div>
      </div>
    </div>

    <!-- 图表 -->
    <div class="charts-row">
      <div class="chart-card">
        <div class="chart-title">主机状态分布</div>
        <div ref="hostChartRef" style="height: 300px;"></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">资源平均使用率</div>
        <div ref="resourceChartRef" style="height: 300px;"></div>
      </div>
    </div>

    <!-- 最近动态 -->
    <div class="charts-row">
      <div class="chart-card">
        <div class="chart-title">最近部署</div>
        <el-table :data="stats.recent_deploys || []" stripe style="width: 100%" size="small">
          <el-table-column prop="app_name" label="应用" width="140" />
          <el-table-column prop="version" label="版本" width="100" />
          <el-table-column prop="environment_display" label="环境" width="80" />
          <el-table-column prop="status_display" label="状态" width="80">
            <template #default="{ row }">
              <span>
                <span class="status-dot" :class="row.status"></span>
                {{ row.status_display }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="deployer" label="部署人" />
        </el-table>
      </div>
      <div class="chart-card">
        <div class="chart-title">未处理告警</div>
        <el-table :data="stats.recent_alerts || []" stripe style="width: 100%" size="small">
          <el-table-column prop="title" label="标题" />
          <el-table-column prop="level_display" label="级别" width="80">
            <template #default="{ row }">
              <el-tag :type="levelType(row.level)" size="small">{{ row.level_display }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="source" label="来源" width="120" />
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts'
import { getDashboardStats } from '@/api/modules/ops'

const stats = ref({})
const hostChartRef = ref(null)
const resourceChartRef = ref(null)
let hostChart = null
let resourceChart = null

const levelType = (level) => {
  const map = { critical: 'danger', warning: 'warning', info: 'info' }
  return map[level] || 'info'
}

const initCharts = () => {
  // 主机状态饼图
  if (hostChartRef.value) {
    hostChart = echarts.init(hostChartRef.value)
    hostChart.setOption({
      tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      color: ['#10b981', '#ef4444', '#f59e0b'],
      series: [{
        type: 'pie',
        radius: ['45%', '70%'],
        center: ['50%', '55%'],
        avoidLabelOverlap: true,
        itemStyle: { borderRadius: 8, borderColor: '#fff', borderWidth: 2 },
        label: { show: true, fontSize: 13 },
        data: [
          { value: stats.value.hosts?.online || 0, name: '在线' },
          { value: stats.value.hosts?.offline || 0, name: '离线' },
          { value: stats.value.hosts?.warning || 0, name: '告警' },
        ],
      }],
    })
  }

  // 资源使用率柱状图
  if (resourceChartRef.value) {
    resourceChart = echarts.init(resourceChartRef.value)
    resourceChart.setOption({
      tooltip: { trigger: 'axis' },
      grid: { left: 50, right: 30, top: 30, bottom: 30 },
      xAxis: {
        type: 'category',
        data: ['CPU', '内存', '磁盘'],
        axisLabel: { fontSize: 13 },
      },
      yAxis: {
        type: 'value',
        max: 100,
        axisLabel: { formatter: '{value}%' },
      },
      series: [{
        type: 'bar',
        barWidth: 40,
        data: [
          {
            value: stats.value.hosts?.avg_cpu || 0,
            itemStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: '#6366f1' }, { offset: 1, color: '#818cf8' }
            ]), borderRadius: [6, 6, 0, 0] },
          },
          {
            value: stats.value.hosts?.avg_memory || 0,
            itemStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: '#10b981' }, { offset: 1, color: '#34d399' }
            ]), borderRadius: [6, 6, 0, 0] },
          },
          {
            value: stats.value.hosts?.avg_disk || 0,
            itemStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: '#f59e0b' }, { offset: 1, color: '#fbbf24' }
            ]), borderRadius: [6, 6, 0, 0] },
          },
        ],
      }],
    })
  }
}

const handleResize = () => {
  hostChart?.resize()
  resourceChart?.resize()
}

onMounted(async () => {
  try {
    stats.value = await getDashboardStats()
  } catch (e) {
    console.error('获取统计数据失败', e)
  }
  await nextTick()
  initCharts()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  hostChart?.dispose()
  resourceChart?.dispose()
})
</script>
