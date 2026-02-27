<template>
  <div class="loki-explore fade-in">
    <!-- ═══ 顶部筛选区 ═══ -->
    <div class="explore-toolbar">
      <!-- 第一行：标签筛选 -->
      <div class="filter-section">
        <div class="filter-label">
          <el-icon><Filter /></el-icon>
          <span>标签筛选</span>
        </div>
        <div class="label-filters">
          <div v-for="(filter, idx) in labelFilters" :key="idx" class="label-filter-item">
            <el-select
              v-model="filter.key"
              placeholder="标签名"
              filterable
              size="default"
              class="label-key-select"
              @change="onLabelKeyChange(idx)"
            >
              <el-option v-for="l in labels" :key="l" :label="l" :value="l" />
            </el-select>
            <el-select
              v-model="filter.operator"
              size="default"
              class="label-op-select"
            >
              <el-option label="=" value="=" />
              <el-option label="!=" value="!=" />
              <el-option label="=~" value="=~" />
              <el-option label="!~" value="!~" />
            </el-select>
            <el-select
              v-model="filter.value"
              placeholder="标签值"
              filterable
              allow-create
              size="default"
              class="label-value-select"
              :loading="filter._loading"
              @focus="loadLabelValues(idx)"
            >
              <el-option v-for="v in (filter._values || [])" :key="v" :label="v" :value="v" />
            </el-select>
            <el-button
              text type="danger" size="small"
              class="filter-remove-btn"
              @click="removeLabelFilter(idx)"
            >
              <el-icon><Close /></el-icon>
            </el-button>
          </div>
          <el-button text type="primary" size="small" class="add-filter-btn" @click="addLabelFilter">
            <el-icon><Plus /></el-icon>
            添加标签
          </el-button>
        </div>
      </div>

      <!-- 第二行：日志内容搜索 -->
      <div class="filter-section">
        <div class="filter-label">
          <el-icon><Search /></el-icon>
          <span>内容搜索</span>
        </div>
        <div class="content-search">
          <el-input
            v-model="contentSearch"
            placeholder="输入关键词搜索日志内容，多个关键词用空格分隔"
            clearable
            size="default"
            class="search-input"
            @input="generateLogQL"
          >
            <template #prepend>
              <el-select v-model="contentMatchMode" style="width: 80px" size="default">
                <el-option label="包含" value="include" />
                <el-option label="排除" value="exclude" />
                <el-option label="正则" value="regex" />
              </el-select>
            </template>
          </el-input>
        </div>
      </div>

      <!-- 第三行：自动生成的 LogQL（可编辑）-->
      <div class="filter-section logql-section">
        <div class="filter-label">
          <el-icon><Edit /></el-icon>
          <span>LogQL</span>
        </div>
        <div class="logql-row">
          <div class="logql-input-wrap" :class="{ 'logql-edited': logqlManuallyEdited }">
            <input
              v-model="logql"
              class="logql-input"
              placeholder='{job="nginx"} |= "error"'
              @keydown.enter="runQuery"
              @input="onLogqlManualEdit"
            />
            <el-tooltip v-if="logqlManuallyEdited" content="已手动编辑，点击重新生成" placement="top">
              <el-button text size="small" class="logql-reset-btn" @click="generateLogQL">
                <el-icon><RefreshRight /></el-icon>
              </el-button>
            </el-tooltip>
          </div>
          <el-button type="primary" class="run-btn" :loading="loading" @click="runQuery">
            <el-icon v-if="!loading"><CaretRight /></el-icon>
            查询
          </el-button>
        </div>
      </div>

      <!-- 第四行：时间范围 + 结果meta -->
      <div class="time-row">
        <div class="time-presets">
          <el-button
            v-for="preset in timePresets" :key="preset.value"
            :type="selectedPreset === preset.value ? 'primary' : ''"
            size="small" text
            :class="{ 'preset-active': selectedPreset === preset.value }"
            @click="selectPreset(preset.value)"
          >{{ preset.label }}</el-button>
        </div>
        <div class="time-custom">
          <el-date-picker
            v-model="timeRange"
            type="datetimerange"
            range-separator="—"
            start-placeholder="开始时间"
            end-placeholder="结束时间"
            size="small"
            format="YYYY-MM-DD HH:mm:ss"
            value-format="x"
            @change="onCustomTimeChange"
          />
        </div>
        <div class="result-meta" v-if="logLines.length">
          <span>{{ logLines.length }} 条日志</span>
          <span v-if="queryDuration"> · {{ queryDuration }}ms</span>
        </div>
      </div>
    </div>

    <!-- ═══ 日志量直方图 ═══ -->
    <div class="volume-chart-card" v-if="logLines.length || loading">
      <div ref="volumeChartRef" class="volume-chart"></div>
    </div>

    <!-- ═══ 日志流区域 ═══ -->
    <div class="log-stream-area">
      <!-- 错误提示 -->
      <div v-if="errorMsg" class="log-error">
        <el-alert :title="errorMsg" type="error" show-icon :closable="false" />
      </div>

      <!-- 空状态 -->
      <div v-if="!loading && logLines.length === 0 && !errorMsg" class="log-empty">
        <el-empty description="选择标签筛选条件或输入搜索关键词，点击「查询」">
          <template #image>
            <el-icon :size="48" style="color:var(--text-muted)"><Document /></el-icon>
          </template>
        </el-empty>
      </div>

      <!-- Loading -->
      <div v-if="loading" class="log-loading">
        <el-icon class="is-loading" :size="24"><Loading /></el-icon>
        <span>查询中...</span>
      </div>

      <!-- 公共标签展示 -->
      <div class="common-labels-bar" v-if="commonLabels && Object.keys(commonLabels).length">
        <span class="common-labels-title">公共标签</span>
        <span v-for="(v, k) in commonLabels" :key="k" class="common-label-chip">
          <span class="clc-key">{{ k }}</span><span class="clc-eq">=</span><span class="clc-val">{{ v }}</span>
        </span>
      </div>

      <!-- 日志行 -->
      <div class="log-lines" v-if="logLines.length">
        <div
          v-for="(line, idx) in logLines" :key="idx"
          class="log-line"
          :class="{ expanded: expandedLines.has(idx) }"
          @click="toggleLine(idx)"
        >
          <div class="log-line-main">
            <span class="log-message" v-html="highlightContent(line.line)"></span>
          </div>

          <!-- 展开详情 -->
          <transition name="slide">
            <div v-if="expandedLines.has(idx)" class="log-detail" @click.stop>
              <div class="log-detail-section">
                <div class="log-detail-title">Labels</div>
                <div class="log-detail-labels">
                  <div v-for="(v, k) in line.streamLabels" :key="k" class="log-detail-label">
                    <span class="ldl-key">{{ k }}</span>
                    <span class="ldl-eq">=</span>
                    <span class="ldl-val">{{ v }}</span>
                    <el-button text size="small" class="ldl-action" @click.stop="quickAddLabel(k, v)">
                      <el-icon><Plus /></el-icon>
                    </el-button>
                  </div>
                </div>
              </div>
              <div class="log-detail-section">
                <div class="log-detail-title">Log Line</div>
                <pre class="log-detail-message">{{ line.line }}</pre>
              </div>
            </div>
          </transition>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import * as echarts from 'echarts'
import { getLokiLabels, getLokiLabelValues, queryLokiLogs } from '@/api/modules/ops'

// ─── 标签筛选 ───
const labels = ref([])
const labelFilters = ref([])
const labelsLoading = ref(false)

const addLabelFilter = () => {
  labelFilters.value.push({ key: '', operator: '=', value: '', _values: [], _loading: false })
}

const removeLabelFilter = (idx) => {
  labelFilters.value.splice(idx, 1)
  generateLogQL()
}

const onLabelKeyChange = (idx) => {
  labelFilters.value[idx].value = ''
  labelFilters.value[idx]._values = []
  loadLabelValues(idx)
  generateLogQL()
}

const loadLabelValues = async (idx) => {
  const filter = labelFilters.value[idx]
  if (!filter.key || filter._values.length > 0) return
  filter._loading = true
  try {
    const { start, end } = getTimeRange()
    const res = await getLokiLabelValues(filter.key, { start, end })
    filter._values = res.data || []
  } catch (e) {
    filter._values = []
  } finally {
    filter._loading = false
  }
}

const quickAddLabel = (key, value) => {
  // 检查是否已有该标签
  const existing = labelFilters.value.find(f => f.key === key)
  if (existing) {
    existing.value = value
  } else {
    labelFilters.value.push({ key, operator: '=', value, _values: [], _loading: false })
  }
  generateLogQL()
}

// ─── 内容搜索 ───
const contentSearch = ref('')
const contentMatchMode = ref('include')

// ─── LogQL ───
const logql = ref('')
const logqlManuallyEdited = ref(false)

const generateLogQL = () => {
  logqlManuallyEdited.value = false

  // 构建 stream selector
  const selectorParts = labelFilters.value
    .filter(f => f.key && f.value)
    .map(f => {
      const val = f.operator === '=~' || f.operator === '!~' ? f.value : f.value
      return `${f.key}${f.operator}"${val}"`
    })

  let selector = selectorParts.length > 0
    ? `{${selectorParts.join(', ')}}`
    : '{job!=""}'

  // 构建 pipeline（内容搜索）
  let pipeline = ''
  const search = contentSearch.value.trim()
  if (search) {
    const keywords = search.split(/\s+/).filter(Boolean)
    for (const kw of keywords) {
      if (contentMatchMode.value === 'include') {
        pipeline += ` |= "${kw}"`
      } else if (contentMatchMode.value === 'exclude') {
        pipeline += ` != "${kw}"`
      } else if (contentMatchMode.value === 'regex') {
        pipeline += ` |~ "${kw}"`
      }
    }
  }

  logql.value = selector + pipeline
}

const onLogqlManualEdit = () => {
  logqlManuallyEdited.value = true
}

// 监听标签筛选变化自动生成 LogQL
watch(labelFilters, generateLogQL, { deep: true })

// ─── 查询状态 ───
const loading = ref(false)
const errorMsg = ref('')
const queryDuration = ref(0)

// ─── 时间范围 ───
const timePresets = [
  { label: '5m',  value: 5 * 60 },
  { label: '15m', value: 15 * 60 },
  { label: '30m', value: 30 * 60 },
  { label: '1h',  value: 3600 },
  { label: '3h',  value: 3 * 3600 },
  { label: '6h',  value: 6 * 3600 },
  { label: '12h', value: 12 * 3600 },
  { label: '24h', value: 24 * 3600 },
  { label: '3d',  value: 3 * 86400 },
  { label: '7d',  value: 7 * 86400 },
]
const selectedPreset = ref(3600)
const timeRange = ref(null)

const getTimeRange = () => {
  if (timeRange.value && timeRange.value.length === 2) {
    return {
      start: (timeRange.value[0] * 1000000).toString(),
      end: (timeRange.value[1] * 1000000).toString(),
    }
  }
  const now = Date.now()
  return {
    start: ((now - selectedPreset.value * 1000) * 1000000).toString(),
    end: (now * 1000000).toString(),
  }
}

const selectPreset = (val) => {
  selectedPreset.value = val
  timeRange.value = null
}

const onCustomTimeChange = (val) => {
  if (val) selectedPreset.value = null
}

// ─── 日志结果 ───
const logLines = ref([])
const expandedLines = ref(new Set())

// 提取所有 stream 共有的标签
const commonLabels = computed(() => {
  if (logLines.value.length === 0) return {}
  // 收集所有不同的 stream（按 JSON key 去重）
  const seen = new Map()
  for (const line of logLines.value) {
    if (line.streamLabels) {
      const key = JSON.stringify(line.streamLabels)
      if (!seen.has(key)) seen.set(key, line.streamLabels)
    }
  }
  const streams = [...seen.values()]
  if (streams.length === 0) return {}
  // 找出所有 stream 都相同的标签
  const first = streams[0]
  const result = {}
  for (const [k, v] of Object.entries(first)) {
    if (streams.every(s => s[k] === v)) {
      result[k] = v
    }
  }
  return result
})

const runQuery = async () => {
  const q = logql.value.trim()
  if (!q) {
    generateLogQL()
    if (!logql.value.trim()) return
  }
  loading.value = true
  errorMsg.value = ''
  logLines.value = []
  expandedLines.value = new Set()
  const startTime = Date.now()

  try {
    const { start, end } = getTimeRange()
    const res = await queryLokiLogs({
      query: logql.value.trim(),
      start, end,
      limit: 1000,
      direction: 'backward',
    })
    queryDuration.value = Date.now() - startTime

    const streams = res.data?.result || []
    const lines = []
    for (const stream of streams) {
      const streamLabels = stream.stream || {}
      for (const [ts, line] of (stream.values || [])) {
        lines.push({ timestamp: ts, line, streamLabels })
      }
    }
    lines.sort((a, b) => (b.timestamp > a.timestamp ? 1 : b.timestamp < a.timestamp ? -1 : 0))
    logLines.value = lines

    await nextTick()
    renderVolumeChart()
  } catch (e) {
    queryDuration.value = Date.now() - startTime
    if (e.response?.status === 502) {
      errorMsg.value = '无法连接 Loki 服务，请检查 Loki 是否正常运行'
    } else if (e.response?.data?.error) {
      errorMsg.value = e.response.data.error
    } else {
      errorMsg.value = e.message || '查询失败'
    }
  } finally {
    loading.value = false
  }
}

const toggleLine = (idx) => {
  const set = new Set(expandedLines.value)
  if (set.has(idx)) set.delete(idx)
  else set.add(idx)
  expandedLines.value = set
}

// ─── 日志级别检测 ───
const detectLevel = (line) => {
  const lower = line.toLowerCase()
  if (lower.includes('error') || lower.includes('fatal') || lower.includes('panic') || lower.includes('err=')) return 'level-error'
  if (lower.includes('warn')) return 'level-warn'
  if (lower.includes('info')) return 'level-info'
  if (lower.includes('debug') || lower.includes('trace')) return 'level-debug'
  return 'level-unknown'
}

const detectLevelText = (line) => {
  const lower = line.toLowerCase()
  if (lower.includes('error') || lower.includes('fatal') || lower.includes('panic') || lower.includes('err=')) return 'ERR'
  if (lower.includes('warn')) return 'WRN'
  if (lower.includes('info')) return 'INF'
  if (lower.includes('debug') || lower.includes('trace')) return 'DBG'
  return '---'
}

const getTopLabels = (labels) => {
  const priority = ['job', 'app', 'namespace', 'pod', 'container', 'instance', 'level', 'host', 'server', 'service_name', 'env']
  const result = {}
  let count = 0
  for (const key of priority) {
    if (labels[key] && count < 3) { result[key] = labels[key]; count++ }
  }
  if (count === 0) {
    for (const [k, v] of Object.entries(labels)) {
      if (count >= 3) break
      result[k] = v; count++
    }
  }
  return result
}

// ─── 高亮搜索关键词 ───
const highlightContent = (line) => {
  const search = contentSearch.value.trim()
  if (!search || contentMatchMode.value === 'exclude') {
    return escapeHtml(line)
  }
  const keywords = search.split(/\s+/).filter(Boolean)
  let result = escapeHtml(line)
  for (const kw of keywords) {
    try {
      const pattern = contentMatchMode.value === 'regex' ? new RegExp(`(${kw})`, 'gi') : new RegExp(`(${escapeRegex(kw)})`, 'gi')
      result = result.replace(pattern, '<mark class="log-highlight">$1</mark>')
    } catch (e) { /* regex 无效则忽略 */ }
  }
  return result
}

const escapeHtml = (str) => str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
const escapeRegex = (str) => str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

// ─── 时间格式化 ───
const formatNanoTs = (nanoTs) => {
  const ms = parseInt(nanoTs) / 1000000
  const d = new Date(ms)
  const pad = (n, l = 2) => String(n).padStart(l, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`
}

// ─── 日志量柱状图 ───
const volumeChartRef = ref(null)
let volumeChart = null

const renderVolumeChart = () => {
  if (!volumeChartRef.value || logLines.value.length === 0) return
  const lines = logLines.value
  const minTs = parseInt(lines[lines.length - 1].timestamp) / 1e6
  const maxTs = parseInt(lines[0].timestamp) / 1e6
  const range = maxTs - minTs || 60000
  const bucketCount = Math.min(60, Math.max(20, Math.floor(range / 10000)))
  const bucketSize = range / bucketCount

  const bucketsNormal = new Array(bucketCount).fill(0)
  const bucketsError = new Array(bucketCount).fill(0)
  const categories = []

  for (let i = 0; i < bucketCount; i++) {
    const t = new Date(minTs + bucketSize * i + bucketSize / 2)
    const pad = (n) => String(n).padStart(2, '0')
    categories.push(`${pad(t.getHours())}:${pad(t.getMinutes())}`)
  }

  for (const line of lines) {
    const ms = parseInt(line.timestamp) / 1e6
    const idx = Math.min(Math.floor((ms - minTs) / bucketSize), bucketCount - 1)
    if (idx >= 0) {
      if (detectLevel(line.line) === 'level-error') bucketsError[idx]++
      else bucketsNormal[idx]++
    }
  }

  if (!volumeChart) volumeChart = echarts.init(volumeChartRef.value)
  volumeChart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 45, right: 15, top: 10, bottom: 25 },
    xAxis: {
      type: 'category', data: categories,
      axisLabel: { fontSize: 11, color: '#94a3b8' },
      axisLine: { lineStyle: { color: '#334155' } },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      axisLabel: { fontSize: 11, color: '#94a3b8' },
      splitLine: { lineStyle: { color: '#1e293b' } },
    },
    series: [
      { name: '正常', type: 'bar', stack: 'total', data: bucketsNormal, itemStyle: { color: '#3b82f6' }, barWidth: '60%' },
      { name: '错误', type: 'bar', stack: 'total', data: bucketsError, itemStyle: { color: '#ef4444', borderRadius: [2,2,0,0] } },
    ],
  }, true)
}

const handleResize = () => { volumeChart?.resize() }

// ─── 初始化 ───
const fetchLabels = async () => {
  labelsLoading.value = true
  try {
    const { start, end } = getTimeRange()
    const res = await getLokiLabels({ start, end })
    labels.value = (res.data || []).filter(l => l !== '__name__')
  } catch (e) {
    labels.value = []
  } finally {
    labelsLoading.value = false
  }
}

onMounted(() => {
  fetchLabels()
  generateLogQL()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  volumeChart?.dispose()
})
</script>

<style scoped>
/* ========== Explore 布局 ========== */
.loki-explore {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 100%;
  max-width: 100%;
  overflow: hidden;
}

/* ───── 筛选工具栏 ───── */
.explore-toolbar {
  background: #ffffff;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.filter-section {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.filter-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: #475569;
  min-width: 80px;
  flex-shrink: 0;
  padding-top: 8px;
  white-space: nowrap;
}

/* 标签筛选 */
.label-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  flex: 1;
}

.label-filter-item {
  display: flex;
  align-items: center;
  gap: 4px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 4px 4px 4px 8px;
  transition: all 0.2s;
}
.label-filter-item:hover {
  border-color: #6366f1;
  background: #fafafe;
}

.label-key-select {
  width: 130px;
}
.label-op-select {
  width: 70px;
}
.label-value-select {
  width: 160px;
}

.filter-remove-btn {
  padding: 4px;
  color: #94a3b8;
}
.filter-remove-btn:hover {
  color: #ef4444;
}

.add-filter-btn {
  font-size: 13px;
  padding: 8px 12px;
  border: 1px dashed #cbd5e1;
  border-radius: 8px;
}
.add-filter-btn:hover {
  border-color: #6366f1;
}

/* 内容搜索 */
.content-search {
  flex: 1;
}
.search-input {
  width: 100%;
}

/* LogQL 行 */
.logql-section {
  border-top: 1px solid #f1f5f9;
  padding-top: 14px;
}
.logql-row {
  flex: 1;
  display: flex;
  gap: 12px;
  align-items: center;
}
.logql-input-wrap {
  flex: 1;
  display: flex;
  align-items: center;
  background: #f1f5f9;
  border: 2px solid #e2e8f0;
  border-radius: 8px;
  padding: 0 8px 0 12px;
  transition: border-color 0.2s;
}
.logql-input-wrap:focus-within {
  border-color: #6366f1;
  background: #fff;
}
.logql-input-wrap.logql-edited {
  border-color: #f59e0b;
  background: #fffbeb;
}
.logql-input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 13.5px;
  padding: 9px 0;
  color: #1e293b;
}
.logql-input::placeholder {
  color: #94a3b8;
  font-family: 'Inter', sans-serif;
}
.logql-reset-btn {
  color: #f59e0b;
  padding: 2px;
}

.run-btn {
  height: 40px;
  padding: 0 28px;
  font-weight: 600;
  border-radius: 8px;
  font-size: 14px;
}

/* 时间行 */
.time-row {
  display: flex;
  align-items: center;
  gap: 12px;
  border-top: 1px solid #f1f5f9;
  padding-top: 14px;
  flex-wrap: wrap;
}
.time-presets {
  display: flex;
  gap: 2px;
  background: #f1f5f9;
  border-radius: 6px;
  padding: 2px;
}
.time-presets .el-button {
  font-size: 12px;
  font-weight: 500;
  padding: 4px 10px;
  border-radius: 4px;
}
.preset-active {
  background: #6366f1 !important;
  color: #fff !important;
}
.result-meta {
  margin-left: auto;
  font-size: 13px;
  color: #64748b;
  font-weight: 500;
}

/* ───── 日志量直方图 ───── */
.volume-chart-card {
  background: #0f172a;
  border-radius: 10px;
  padding: 12px 16px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}
.volume-chart { height: 100px; }

/* ───── 日志流 ───── */
.log-stream-area {
  display: flex;
  flex-direction: column;
  min-height: 400px;
}
.log-error { margin-bottom: 12px; }
.log-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #fff;
  border-radius: 10px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  min-height: 300px;
}
.log-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 40px;
  color: #6366f1;
  font-size: 14px;
}

/* 公共标签栏 */
.common-labels-bar {
  background: #1e293b;
  border-radius: 8px 8px 0 0;
  padding: 10px 16px;
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.common-labels-title {
  font-size: 12px;
  color: #64748b;
  font-weight: 600;
  margin-right: 4px;
}
.common-label-chip {
  font-size: 12px;
  background: rgba(99,102,241,0.15);
  border: 1px solid rgba(99,102,241,0.25);
  border-radius: 4px;
  padding: 2px 8px;
  font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
}
.clc-key { color: #818cf8; }
.clc-eq { color: #64748b; margin: 0 1px; }
.clc-val { color: #fbbf24; }

.log-lines {
  display: flex;
  flex-direction: column;
  background: #0f172a;
  border-radius: 10px;
  padding: 8px 0;
  font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 12.5px;
  line-height: 1.6;
  overflow-x: auto;
  max-width: 100%;
  width: 100%;
}

.log-line {
  cursor: pointer;
  transition: background 0.1s;
  border-left: 3px solid transparent;
}
.log-line:hover { background: rgba(255,255,255,0.03); }
.log-line.expanded { background: rgba(255,255,255,0.05); }

.log-line-main {
  padding: 3px 12px;
  overflow: hidden;
}

.log-ts {
  color: #64748b;
  flex-shrink: 0;
  font-size: 12px;
}

.log-level-badge {
  font-size: 11px;
  font-weight: 700;
  padding: 0px 5px;
  border-radius: 3px;
  flex-shrink: 0;
  letter-spacing: 0.5px;
}
.log-level-badge.level-error { background: rgba(239,68,68,0.2); color: #fca5a5; }
.log-line:has(.level-error) { border-left-color: #ef4444; }
.log-level-badge.level-warn { background: rgba(245,158,11,0.2); color: #fcd34d; }
.log-line:has(.level-warn) { border-left-color: #f59e0b; }
.log-level-badge.level-info { background: rgba(16,185,129,0.15); color: #6ee7b7; }
.log-line:has(.level-info) { border-left-color: #10b981; }
.log-level-badge.level-debug { background: rgba(59,130,246,0.15); color: #93c5fd; }
.log-level-badge.level-unknown { background: rgba(148,163,184,0.15); color: #94a3b8; }

.log-labels-inline { display: flex; gap: 4px; flex-shrink: 0; }
.log-label-chip {
  font-size: 11px;
  background: rgba(99,102,241,0.15);
  color: #a5b4fc;
  padding: 0 5px;
  border-radius: 3px;
}

.log-message {
  color: #e2e8f0;
  white-space: pre-wrap;
  word-break: break-all;
  display: block;
  width: 100%;
}

/* 搜索高亮 */
:deep(.log-highlight) {
  background: rgba(250, 204, 21, 0.35);
  color: #fef08a;
  padding: 0 1px;
  border-radius: 2px;
}

/* ─── 展开详情 ─── */
.log-detail {
  padding: 10px 16px 10px 40px;
  border-top: 1px solid rgba(255,255,255,0.06);
}
.log-detail-section { margin-bottom: 10px; }
.log-detail-title {
  font-size: 11px;
  font-weight: 700;
  color: #6366f1;
  text-transform: uppercase;
  letter-spacing: 1px;
  margin-bottom: 6px;
}
.log-detail-labels { display: flex; flex-wrap: wrap; gap: 4px 12px; }
.log-detail-label { display: flex; align-items: center; gap: 2px; font-size: 12px; }
.ldl-key { color: #818cf8; }
.ldl-eq  { color: #64748b; }
.ldl-val { color: #fbbf24; }
.ldl-action { opacity: 0; padding: 0; font-size: 11px; color: #818cf8; }
.log-detail-label:hover .ldl-action { opacity: 1; }
.log-detail-message {
  background: rgba(0,0,0,0.3);
  border-radius: 6px;
  padding: 10px 12px;
  color: #e2e8f0;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
  max-height: 300px;
  overflow-y: auto;
}

/* ─── 动画 ─── */
.slide-enter-active, .slide-leave-active { transition: all 0.2s ease; max-height: 500px; overflow: hidden; }
.slide-enter-from, .slide-leave-to { max-height: 0; opacity: 0; }
</style>
