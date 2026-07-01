<template>
  <div class="event-wall-page fade-in">
    <section class="hero panel">
      <div class="hero-copy">
        <div class="hero-title-row">
          <span class="hero-icon">
            <el-icon><Aim /></el-icon>
          </span>
          <h2>事件中心</h2>
          <span class="hero-tagline">汇聚发布、变更、任务与 Webhook 外部事件，按时间线沉淀排障线索，辅助故障定位与 AIOps 分析。</span>
        </div>
      </div>
      <div class="hero-actions">
        <el-button size="small" :loading="loading" @click="loadWall">
          <el-icon><RefreshRight /></el-icon>
          刷新
        </el-button>
      </div>
    </section>

    <EventWallTabs />

    <section class="query-panel panel">
      <div class="query-head">
        <div class="query-title-block">
          <h3>事件筛选</h3>
          <span>环境必选，先选择环境，再选择系统、服务和事件源。</span>
        </div>
        <div class="query-actions">
          <el-button size="small" type="primary" :loading="loading" @click="applyQuery">查询</el-button>
          <el-button size="small" plain @click="clearAllFilters">重置</el-button>
        </div>
      </div>

      <div class="query-body">
        <div class="query-grid query-grid--primary">
          <label class="inline-filter is-required">
            <span>环境</span>
            <el-select v-model="scope.environment" size="small" placeholder="请选择环境" filterable @change="handleEnvironmentChange">
              <el-option v-for="item in environmentOptions" :key="item.code || item" :label="item.name || item.label || item.code || item" :value="item.code || item" />
            </el-select>
          </label>
          <label class="inline-filter">
            <span>系统</span>
            <el-select v-model="scope.system_name" size="small" placeholder="选择系统" clearable filterable :disabled="!scope.environment" @change="handleSystemChange">
              <el-option v-for="item in systemOptions" :key="item" :label="item" :value="item" />
            </el-select>
          </label>
          <label class="inline-filter">
            <span>服务</span>
            <el-select v-model="scope.application" size="small" placeholder="选择服务" clearable filterable :disabled="!scope.environment">
              <el-option v-for="item in applicationOptions" :key="item" :label="item" :value="item" />
            </el-select>
          </label>
          <label class="inline-filter">
            <span>事件源</span>
            <el-select v-model="eventSourceCode" size="small" placeholder="全部事件源" clearable filterable>
              <el-option v-for="item in sourceOptions" :key="item.code" :label="item.name" :value="item.code" />
            </el-select>
          </label>
        </div>

        <div class="query-grid query-grid--advanced">
          <label class="inline-filter inline-filter--compact">
            <span>结果</span>
            <el-select v-model="resultFilter" size="small" placeholder="全部结果" clearable>
              <el-option label="失败" value="failed" />
              <el-option label="部分成功" value="partial" />
              <el-option label="待处理" value="pending" />
              <el-option label="成功" value="success" />
            </el-select>
          </label>
          <label class="inline-filter inline-filter--time">
            <span>时间</span>
            <el-date-picker
              v-model="analysisRange"
              size="small"
              type="datetimerange"
              range-separator="至"
              start-placeholder="开始"
              end-placeholder="结束"
              :shortcuts="rangeShortcuts"
              class="query-time"
            />
          </label>
          <label class="inline-filter inline-filter--keyword">
            <span>关键字</span>
            <el-input v-model="keyword" size="small" placeholder="标题 / 资源 / 操作人" clearable>
              <template #prefix><el-icon><Search /></el-icon></template>
            </el-input>
          </label>
        </div>
      </div>

      <div class="search-summary-bar trace-query-summary-bar">
        <button
          v-for="item in querySummaryItems"
          :key="item.key"
          type="button"
          class="query-pill"
          :disabled="!item.clearable"
          @click="clearFilter(item.key)"
        >
          {{ item.label }}：{{ item.value }}
          <i v-if="item.clearable">×</i>
        </button>
        <button v-if="activeFilterChips.length" type="button" class="query-pill query-pill--clear" @click="clearAllFilters">清空条件</button>
      </div>
    </section>

    <section class="panel timeline-panel" v-loading="loading">
      <div class="section-head">
        <h3>事件时间线</h3>
        <span>{{ timelineCategoryLabel }} · {{ formatTransactionWindow }}</span>
      </div>
      <div class="axis-row">
        <div class="axis-label">事件窗口</div>
        <div
          class="axis-track"
          :class="{ selecting: timelineSelection.active && timelineDrag.source === 'axis' }"
        >
          <span>{{ formatShortTime(transactionTimelineWindow.start_at) }}</span>
          <strong ref="axisRailRef">
            <i
              v-if="timelineSelection.active && timelineDrag.source === 'axis'"
              class="axis-selection"
              :style="timelineSelectionStyle"
            ></i>
            <em v-if="timelineSelection.active && timelineDrag.source === 'axis'">{{ timelineSelection.label }}</em>
          </strong>
          <span>{{ formatShortTime(transactionTimelineWindow.end_at) }}</span>
        </div>
      </div>
      <div class="lane-stack">
        <article
          v-for="lane in transactionTimelineLanes"
          :key="lane.key"
          class="lane-row"
          :class="{ active: timelineCategoryFilter === lane.key, muted: timelineCategoryFilter !== 'all' && timelineCategoryFilter !== lane.key, empty: lane.count === 0 }"
        >
          <button type="button" class="lane-label" @click="toggleTimelineCategory(lane.key)">
            <strong>{{ lane.label }}</strong>
            <span>{{ lane.count }} 条 · 失败 {{ lane.failed }}</span>
            <em>{{ timelineCategoryFilter === lane.key ? '再次点击显示全部' : '点击聚焦' }}</em>
          </button>
          <div
            class="lane-track"
            :class="{ selecting: timelineSelection.active }"
            :style="laneTrackStyle(lane)"
            @mousedown="startTimelineSelection($event, 'lane')"
          >
            <i
              v-if="timelineSelection.active"
              class="lane-selection"
              :style="timelineSelectionStyle"
            >
              <em>{{ timelineSelection.label }}</em>
            </i>
            <button
              v-for="event in lane.events"
              :key="event.id"
              type="button"
              class="event-dot"
              :class="[`is-${event.result}`, { 'is-suspect': event.suspicion_score >= 35 }]"
              :style="eventDotStyle(event)"
              :title="event.title"
              @mousedown.stop
              @click="openDetail(event)"
            >
              <span>{{ formatDotTime(event.occurred_at) }}</span>
              <strong>{{ event.title }}</strong>
            </button>
          </div>
        </article>
      </div>
    </section>

    <section class="panel category-panel">
      <div class="section-head">
        <h3>分类事件列表</h3>
        <span>{{ formatTransactionWindow }} · {{ activeCategorySection.events.length }} / {{ activeCategorySection.total }} 条 · 失败 {{ activeCategorySection.failed }}</span>
      </div>
      <div class="category-tabs">
        <button
          v-for="section in categorySections"
          :key="section.key"
          type="button"
          :class="{ active: activeCategoryTab === section.key }"
          @click="activeCategoryTab = section.key"
        >
          <strong>{{ section.label }}</strong>
          <span>{{ section.events.length }} / {{ section.total }}</span>
        </button>
      </div>
      <div class="category-filter-row" :class="`is-${activeCategoryTab}`">
        <template v-if="activeCategoryTab === 'application_release'">
          <el-input v-model="categoryFilters.application_release.service" size="small" placeholder="服务" clearable />
          <el-input v-model="categoryFilters.application_release.version" size="small" placeholder="版本 / 镜像" clearable />
          <el-select v-model="categoryFilters.application_release.action" size="small" placeholder="发布动作" clearable>
            <el-option label="发布" value="deploy" />
            <el-option label="回滚" value="rollback" />
            <el-option label="重跑" value="rerun" />
          <el-option label="构建" value="build" />
            <el-option label="流水线" value="pipeline" />
            <el-option label="启停下线" value="lifecycle" />
          </el-select>
        </template>
        <el-input v-else-if="activeCategoryTab === 'db_change'" v-model="categoryFilters.db_change.keyword" size="small" placeholder="数据库 / SQL / 执行单关键字" clearable>
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-input v-else-if="activeCategoryTab === 'config_change'" v-model="categoryFilters.config_change.keyword" size="small" placeholder="配置项 / 配置对象关键字" clearable>
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-input v-else-if="activeCategoryTab === 'ops_transaction'" v-model="categoryFilters.ops_transaction.keyword" size="small" placeholder="事务类型 / 资源对象关键字" clearable>
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-input v-else v-model="categoryFilters.task_center.keyword" size="small" placeholder="任务名称 / 目标资源 / 执行人关键字" clearable>
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
      </div>
      <el-table :data="activeCategorySection.events" size="small" row-key="id" class="category-table" @row-click="openDetail">
        <el-table-column label="事件时间" width="138">
          <template #default="{ row }">{{ formatTime(row.occurred_at) }}</template>
        </el-table-column>
        <el-table-column label="环境" width="88" show-overflow-tooltip>
          <template #default="{ row }">{{ environmentLabel(row) }}</template>
        </el-table-column>
        <el-table-column label="系统" min-width="120" show-overflow-tooltip>
          <template #default="{ row }">{{ systemLabel(row) }}</template>
        </el-table-column>
        <el-table-column v-if="activeCategoryTab === 'application_release'" label="服务" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ releaseService(row) }}</template>
        </el-table-column>
        <el-table-column v-if="activeCategoryTab === 'application_release'" label="版本" min-width="130" show-overflow-tooltip>
          <template #default="{ row }">{{ releaseVersion(row) }}</template>
        </el-table-column>
        <el-table-column v-if="activeCategoryTab === 'application_release'" label="动作" width="96" show-overflow-tooltip>
          <template #default="{ row }">{{ releaseAction(row) }}</template>
        </el-table-column>
        <el-table-column label="事件" min-width="260">
          <template #default="{ row }">
            <div class="event-cell">
              <strong>{{ eventTitle(row) }}</strong>
              <span v-if="eventDescription(row)">{{ eventDescription(row) }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作人" width="116" show-overflow-tooltip>
          <template #default="{ row }">{{ actorLabel(row) }}</template>
        </el-table-column>
        <el-table-column label="结果" width="86">
          <template #default="{ row }">
            <el-tag size="small" :type="tagType(row.result)">{{ resultLabel(row) }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !activeCategorySection.events.length" :description="`暂无${activeCategorySection.label}事件`" />
    </section>

    <el-drawer v-model="drawerVisible" class="event-detail-drawer" title="事件详情" size="720px" append-to-body destroy-on-close>
      <div v-if="activeEvent" class="detail-stack">
        <section class="detail-section detail-section--main">
          <strong>{{ activeEvent.title }}</strong>
          <p>{{ activeEvent.summary || activeEvent.detail || '-' }}</p>
          <div class="reason-tags">
            <span v-for="reason in visibleSuspicionReasons(activeEvent)" :key="reason">{{ reason }}</span>
          </div>
        </section>
        <section class="detail-section detail-section--meta">
          <div class="detail-row"><span>时间</span><b>{{ formatTime(activeEvent.occurred_at) }}</b></div>
          <div class="detail-row"><span>事件源</span><b>{{ activeEvent.event_source?.name || moduleLabel(activeEvent.module) }}</b></div>
          <div class="detail-row"><span>事件分类</span><b>{{ eventCategoryLabel(activeEvent) }}</b></div>
          <div class="detail-row"><span>结果</span><b>{{ resultLabel(activeEvent) }}</b></div>
          <div class="detail-row"><span>环境 / 系统</span><b>{{ scopeLabel(activeEvent) }}</b></div>
          <div class="detail-row"><span>资源</span><b>{{ activeEvent.resource_type || '-' }} / {{ activeEvent.resource_name || activeEvent.resource_id || '-' }}</b></div>
          <div class="detail-row"><span>操作人</span><b>{{ actorLabel(activeEvent) }}</b></div>
          <div class="detail-row"><span>关联 ID</span><b>{{ activeEvent.correlation_id || '-' }}</b></div>
        </section>
        <section class="detail-section">
          <h4>元数据</h4>
          <pre>{{ prettyJson(activeEvent.metadata || {}) }}</pre>
        </section>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Aim, RefreshRight, Search } from '@element-plus/icons-vue'
import { getEventSources, getEventWallAnalysis, getEventWallFilterOptions } from '@/api/modules/eventwall'
import EventWallTabs from '@/components/eventwall/EventWallTabs.vue'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const drawerVisible = ref(false)
const axisRailRef = ref(null)
const activeEvent = ref(null)
const wall = ref({ summary: {}, window: {}, lanes: [], suspects: [], events: [], source_breakdown: [], tips: [] })
const filterOptions = ref({ system_names: [], environments: [], applications: [] })
const sourceOptions = ref([])
const eventCategoryOptions = [
  { key: 'application_release', label: '应用发布' },
  { key: 'db_change', label: 'DB变更' },
  { key: 'config_change', label: '配置变更' },
  { key: 'ops_transaction', label: '运维事务' },
  { key: 'task_center', label: '任务调度' },
]
const categoryFilters = reactive({
  application_release: { service: '', action: '', version: '' },
  db_change: { keyword: '' },
  config_change: { keyword: '' },
  ops_transaction: { keyword: '' },
  task_center: { keyword: '' },
})
const analysisRange = ref(defaultAnalysisRange())
const activeCategoryTab = ref('application_release')
const timelineCategoryFilter = ref('all')
const eventSourceCode = ref('')
const resultFilter = ref('')
const keyword = ref('')
const scope = reactive({ system_name: '', environment: '', application: '' })
const timelineSelection = reactive({ active: false, startPercent: 0, endPercent: 0, label: '' })
const timelineDrag = reactive({ active: false, source: '', startX: 0, currentX: 0, moved: false, railLeft: 0, railWidth: 0 })
const rangeShortcuts = [
  { text: '最近 30 分钟', value: () => defaultAnalysisRange(30) },
  { text: '最近 1 小时', value: () => defaultAnalysisRange(60) },
  { text: '最近 2 小时', value: () => defaultAnalysisRange(120) },
  { text: '最近 4 小时', value: () => defaultAnalysisRange(240) },
  { text: '最近 12 小时', value: () => defaultAnalysisRange(720) },
  { text: '最近 24 小时', value: () => defaultAnalysisRange(1440) },
]

const environmentOptions = computed(() => {
  const options = filterOptions.value.environment_options || []
  if (options.length) return options
  return (filterOptions.value.environments || []).map(item => ({ code: item, name: item, label: item }))
})
const environmentNameMap = computed(() => {
  return Object.fromEntries(environmentOptions.value.map(item => [item.code || item, item.name || item.label || item.code || item]))
})
const systemOptions = computed(() => {
  if (!scope.environment) return []
  const scoped = filterOptions.value.systems_by_environment?.[scope.environment]
  return Array.isArray(scoped) ? scoped : (filterOptions.value.system_names || [])
})
const applicationOptions = computed(() => {
  if (!scope.environment) return []
  const byEnvironmentSystem = filterOptions.value.applications_by_environment_system?.[scope.environment] || {}
  if (scope.system_name && Array.isArray(byEnvironmentSystem[scope.system_name])) return byEnvironmentSystem[scope.system_name]
  const scoped = filterOptions.value.applications_by_environment?.[scope.environment]
  return Array.isArray(scoped) ? scoped : (filterOptions.value.applications || [])
})

const filteredEvents = computed(() => filterEvents(wall.value.events || []))
const categorySections = computed(() => eventCategoryOptions.map((category) => {
  const categoryEvents = filteredEvents.value.filter(item => eventCategoryKey(item) === category.key)
  const scopedFilter = categoryFilters[category.key] || {}
  const keywordValue = String(scopedFilter.keyword || '').trim().toLowerCase()
  const events = categoryEvents.filter((item) => {
    if (scopedFilter.action) {
      const actionGroup = scopedFilter.action === 'lifecycle' ? ['start', 'stop', 'remove'] : [scopedFilter.action]
      if (!actionGroup.includes(item.action)) return false
    }
    if (scopedFilter.service) {
      const serviceKey = scopedFilter.service.trim().toLowerCase()
      if (!String(releaseService(item) || '').toLowerCase().includes(serviceKey)) return false
    }
    if (scopedFilter.version) {
      const versionKey = scopedFilter.version.trim().toLowerCase()
      if (!String(releaseVersion(item) || '').toLowerCase().includes(versionKey)) return false
    }
    if (!keywordValue) return true
    return categorySearchFields(item).some(value => String(value || '').toLowerCase().includes(keywordValue))
  })
  return {
    ...category,
    events,
    total: categoryEvents.length,
    failed: events.filter(item => item.result === 'failed').length,
    warning: events.filter(item => ['warning', 'danger'].includes(item.severity)).length,
  }
}))
const activeCategorySection = computed(() => {
  return categorySections.value.find(item => item.key === activeCategoryTab.value) || categorySections.value[0] || {
    key: 'application_release',
    label: '应用发布',
    events: [],
    total: 0,
    failed: 0,
  }
})
const activeFilterChips = computed(() => {
  const chips = []
  if (scope.system_name) chips.push({ key: 'system_name', label: `系统 ${scope.system_name}` })
  if (scope.application) chips.push({ key: 'application', label: `服务 ${scope.application}` })
  if (eventSourceCode.value) {
    const source = sourceOptions.value.find(item => item.code === eventSourceCode.value)
    chips.push({ key: 'event_source_code', label: `事件源 ${source?.name || eventSourceCode.value}` })
  }
  if (resultFilter.value) chips.push({ key: 'result', label: `结果 ${resultLabel({ result: resultFilter.value })}` })
  if (keyword.value.trim()) chips.push({ key: 'search', label: `搜索 ${keyword.value.trim()}` })
  return chips
})
const querySummaryItems = computed(() => {
  const [startAt, endAt] = normalizeAnalysisRange()
  const items = [
    { key: 'time', label: '时间', value: `${formatTime(startAt)} - ${formatTime(endAt)}`, clearable: false },
  ]
  if (scope.environment) items.push({ key: 'environment', label: '环境', value: environmentDisplayName(scope.environment), clearable: false })
  if (scope.system_name) items.push({ key: 'system_name', label: '系统', value: scope.system_name, clearable: true })
  if (scope.application) items.push({ key: 'application', label: '服务', value: scope.application, clearable: true })
  if (eventSourceCode.value) {
    const source = sourceOptions.value.find(item => item.code === eventSourceCode.value)
    items.push({ key: 'event_source_code', label: '事件源', value: source?.name || eventSourceCode.value, clearable: true })
  }
  if (resultFilter.value) items.push({ key: 'result', label: '结果', value: resultLabel({ result: resultFilter.value }), clearable: true })
  if (keyword.value.trim()) items.push({ key: 'search', label: '搜索', value: keyword.value.trim(), clearable: true })
  return items
})
const transactionTimelineWindow = computed(() => {
  const [startAt, endAt] = normalizeAnalysisRange()
  return {
    start_at: startAt,
    end_at: endAt,
  }
})
const formatTransactionWindow = computed(() => formatWindow(transactionTimelineWindow.value))
const timelineSelectionStyle = computed(() => {
  const left = Math.min(timelineSelection.startPercent, timelineSelection.endPercent)
  const right = Math.max(timelineSelection.startPercent, timelineSelection.endPercent)
  return {
    left: `${left}%`,
    width: `${Math.max(0, right - left)}%`,
  }
})
const timelineCategoryLabel = computed(() => {
  if (timelineCategoryFilter.value === 'all') return '全部事件'
  return eventCategoryOptions.find(item => item.key === timelineCategoryFilter.value)?.label || '全部事件'
})
const transactionTimelineEvents = computed(() => {
  const start = new Date(transactionTimelineWindow.value.start_at).getTime()
  const end = new Date(transactionTimelineWindow.value.end_at).getTime()
  return filteredEvents.value
    .filter((item) => {
      const occurredAt = new Date(item.occurred_at).getTime()
      if (Number.isFinite(start) && occurredAt < start) return false
      if (Number.isFinite(end) && occurredAt > end) return false
      return true
    })
    .sort((a, b) => new Date(a.occurred_at) - new Date(b.occurred_at))
})
const transactionTimelineLanes = computed(() => {
  return eventCategoryOptions
    .filter(category => timelineCategoryFilter.value === 'all' || category.key === timelineCategoryFilter.value)
    .map((category) => {
      const events = layoutTimelineEvents(transactionTimelineEvents.value.filter(item => eventCategoryKey(item) === category.key))
      return {
        ...category,
        events,
        count: events.length,
        failed: events.filter(item => item.result === 'failed').length,
        stackDepth: Math.max(1, ...events.map(item => (item._timelineStackIndex || 0) + 1)),
      }
    })
})

function filterEvents(events) {
  const key = keyword.value.trim().toLowerCase()
  return events.filter((item) => {
    if (resultFilter.value && item.result !== resultFilter.value) return false
    if (eventSourceCode.value && item.event_source?.code !== eventSourceCode.value) return false
    if (!key) return true
    return categorySearchFields(item)
      .some(value => String(value || '').toLowerCase().includes(key))
  })
}

function categorySearchFields(item) {
  return [
    item.title,
    item.summary,
    item.detail,
    item.resource_name,
    item.resource_id,
    item.actor_username,
    item.application,
    item.environment,
    item.system_name,
    item.correlation_id,
    releaseService(item),
    releaseVersion(item),
  ]
}

function restoreFromRoute() {
  const query = route.query
  analysisRange.value = defaultAnalysisRange()
  eventSourceCode.value = String(query.event_source_code || '')
  resultFilter.value = String(query.result || '')
  keyword.value = String(query.search || '')
  scope.system_name = String(query.system_name || query.business_line || '')
  scope.environment = String(query.environment || '')
  scope.application = String(query.application || '')
}

function buildParams() {
  const [safeStartAt, safeEndAt] = normalizeAnalysisRange()
  const lookbackMinutes = Math.max(1, Math.round((safeEndAt.getTime() - safeStartAt.getTime()) / 60000))
  const params = {
    fault_at: safeEndAt.toISOString(),
    lookback_minutes: lookbackMinutes,
    after_minutes: 0,
    limit: 240,
  }
  if (scope.system_name) params.system_name = scope.system_name
  if (scope.environment) params.environment = scope.environment
  if (scope.application) params.application = scope.application
  if (eventSourceCode.value) params.event_source_code = eventSourceCode.value
  return params
}

async function loadFilterOptions() {
  const [options, sources] = await Promise.all([
    getEventWallFilterOptions(),
    getEventSources({ page_size: 100 }),
  ])
  filterOptions.value = options || {}
  sourceOptions.value = sources.results || sources || []
  ensureRequiredEnvironment()
  reconcileScopeOptions()
}

async function loadWall() {
  loading.value = true
  try {
    wall.value = await getEventWallAnalysis(buildParams())
  } finally {
    loading.value = false
  }
}

async function applyQuery() {
  ensureRequiredEnvironment()
  reconcileScopeOptions()
  const query = {
    ...buildParams(),
    result: resultFilter.value || undefined,
    search: keyword.value || undefined,
  }
  await router.replace({ path: '/events/wall', query })
  await loadWall()
}

async function clearFilter(key) {
  if (key === 'system_name') scope.system_name = ''
  else if (key === 'application') scope.application = ''
  else if (key === 'event_source_code') eventSourceCode.value = ''
  else if (key === 'result') resultFilter.value = ''
  else if (key === 'search') keyword.value = ''
  await applyQuery()
}

async function clearAllFilters() {
  scope.system_name = ''
  scope.application = ''
  eventSourceCode.value = ''
  resultFilter.value = ''
  keyword.value = ''
  ensureRequiredEnvironment()
  await applyQuery()
}

function ensureRequiredEnvironment() {
  if (!scope.environment && environmentOptions.value.length) {
    scope.environment = environmentOptions.value[0].code || environmentOptions.value[0]
  }
}

function reconcileScopeOptions() {
  if (scope.system_name && !systemOptions.value.includes(scope.system_name)) {
    scope.system_name = ''
  }
  if (scope.application && !applicationOptions.value.includes(scope.application)) {
    scope.application = ''
  }
}

function handleEnvironmentChange() {
  scope.system_name = ''
  scope.application = ''
}

function handleSystemChange() {
  if (scope.application && !applicationOptions.value.includes(scope.application)) {
    scope.application = ''
  }
}

function defaultAnalysisRange(minutes = 60) {
  const end = new Date()
  return [new Date(end.getTime() - minutes * 60 * 1000), end]
}

function normalizeAnalysisRange() {
  const [startValue, endValue] = Array.isArray(analysisRange.value) ? analysisRange.value : []
  const endAt = endValue ? new Date(endValue) : new Date()
  const startAt = startValue ? new Date(startValue) : new Date(endAt.getTime() - 60 * 60 * 1000)
  const safeEndAt = Number.isNaN(endAt.getTime()) ? new Date() : endAt
  const safeStartAt = Number.isNaN(startAt.getTime()) ? new Date(safeEndAt.getTime() - 60 * 60 * 1000) : startAt
  return safeStartAt <= safeEndAt ? [safeStartAt, safeEndAt] : [new Date(safeEndAt.getTime() - 60 * 60 * 1000), safeEndAt]
}

function openDetail(row) {
  activeEvent.value = row
  drawerVisible.value = true
}

function datePosition(value, windowValue = wall.value.window) {
  const start = new Date(windowValue?.start_at).getTime()
  const end = new Date(windowValue?.end_at).getTime()
  const current = new Date(value).getTime()
  if (![start, end, current].every(Number.isFinite) || end <= start) return '50%'
  const percent = ((current - start) / (end - start)) * 100
  return `${Math.min(96, Math.max(2, percent))}%`
}

function transactionEventPosition(event) {
  return datePosition(event.occurred_at, transactionTimelineWindow.value)
}

function timelineEventPercent(event) {
  const start = new Date(transactionTimelineWindow.value.start_at).getTime()
  const end = new Date(transactionTimelineWindow.value.end_at).getTime()
  const current = new Date(event?.occurred_at).getTime()
  if (![start, end, current].every(Number.isFinite) || end <= start) return 50
  return Math.min(96, Math.max(2, ((current - start) / (end - start)) * 100))
}

function layoutTimelineEvents(events) {
  const levels = []
  const isFocusedLane = timelineCategoryFilter.value !== 'all'
  const minGapPercent = isFocusedLane ? 4.5 : 8
  const maxVisibleLevels = isFocusedLane ? 8 : 3
  return events.map((event) => {
    const percent = timelineEventPercent(event)
    let stackIndex = levels.findIndex(lastPercent => Math.abs(percent - lastPercent) >= minGapPercent)
    if (stackIndex === -1) {
      stackIndex = levels.length
      levels.push(percent)
    } else {
      levels[stackIndex] = percent
    }
    const compressedIndex = Math.min(stackIndex, maxVisibleLevels - 1)
    const overflowIndex = Math.max(0, stackIndex - compressedIndex)
    return {
      ...event,
      _timelinePercent: percent,
      _timelineStackIndex: stackIndex,
      _timelineCompressedIndex: compressedIndex,
      _timelineOverflowIndex: overflowIndex,
    }
  })
}

function eventDotStyle(event) {
  const compressedIndex = event?._timelineCompressedIndex || 0
  const overflowIndex = event?._timelineOverflowIndex || 0
  const overlapOffset = Math.min(overflowIndex, 8)
  const isFocusedLane = timelineCategoryFilter.value !== 'all'
  const topBase = isFocusedLane ? 14 : 12
  const verticalStep = isFocusedLane ? 30 : 28
  return {
    left: `calc(${event?._timelinePercent ?? timelineEventPercent(event)}% + ${overlapOffset * (isFocusedLane ? 4 : 7)}px)`,
    top: `${topBase + compressedIndex * verticalStep}px`,
    zIndex: 60 - compressedIndex + Math.min(overlapOffset, 8),
  }
}

function laneTrackStyle(lane) {
  const depth = Math.max(1, lane?.stackDepth || 1)
  const isFocusedLane = timelineCategoryFilter.value !== 'all'
  const visibleDepth = Math.min(depth, isFocusedLane ? 8 : 3)
  return {
    minHeight: `${Math.max(isFocusedLane ? 118 : 72, 24 + visibleDepth * (isFocusedLane ? 38 : 34))}px`,
  }
}

function startTimelineSelection(event, source = 'axis') {
  const railRect = source === 'lane'
    ? event.currentTarget?.getBoundingClientRect()
    : axisRailRef.value?.getBoundingClientRect()
  if (event.button !== 0 || loading.value || !railRect?.width) return
  const start = new Date(transactionTimelineWindow.value.start_at).getTime()
  const end = new Date(transactionTimelineWindow.value.end_at).getTime()
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return
  event.preventDefault()
  timelineDrag.active = true
  timelineDrag.startX = event.clientX
  timelineDrag.currentX = event.clientX
  timelineDrag.moved = false
  timelineDrag.railLeft = railRect.left
  timelineDrag.railWidth = railRect.width
  timelineDrag.source = source
  timelineSelection.active = true
  updateTimelineSelection(event.clientX)
  window.addEventListener('mousemove', handleTimelineSelectionMove)
  window.addEventListener('mouseup', finishTimelineSelection)
}

function handleTimelineSelectionMove(event) {
  if (!timelineDrag.active) return
  timelineDrag.currentX = event.clientX
  timelineDrag.moved = timelineDrag.moved || Math.abs(timelineDrag.currentX - timelineDrag.startX) >= 4
  updateTimelineSelection(event.clientX)
}

function finishTimelineSelection() {
  if (!timelineDrag.active) return
  window.removeEventListener('mousemove', handleTimelineSelectionMove)
  window.removeEventListener('mouseup', finishTimelineSelection)
  const shouldApply = timelineDrag.moved
  timelineDrag.active = false
  timelineDrag.source = ''
  if (!shouldApply) {
    timelineSelection.active = false
    return
  }
  const range = timelineSelectionRange()
  timelineSelection.active = false
  if (!range) return
  analysisRange.value = range
  applyQuery()
}

function updateTimelineSelection(clientX) {
  const startPercent = timelineClientXToPercent(timelineDrag.startX)
  const endPercent = timelineClientXToPercent(clientX)
  timelineSelection.startPercent = startPercent
  timelineSelection.endPercent = endPercent
  const range = timelineSelectionRange()
  timelineSelection.label = range ? `${formatShortTime(range[0])} - ${formatShortTime(range[1])}` : '拖动选择时间'
}

function timelineClientXToPercent(clientX) {
  if (!timelineDrag.railWidth) return 0
  return Math.min(100, Math.max(0, ((clientX - timelineDrag.railLeft) / timelineDrag.railWidth) * 100))
}

function timelineSelectionRange() {
  const start = new Date(transactionTimelineWindow.value.start_at).getTime()
  const end = new Date(transactionTimelineWindow.value.end_at).getTime()
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return null
  const left = Math.min(timelineSelection.startPercent, timelineSelection.endPercent) / 100
  const right = Math.max(timelineSelection.startPercent, timelineSelection.endPercent) / 100
  const selectedStart = new Date(start + (end - start) * left)
  let selectedEnd = new Date(start + (end - start) * right)
  if (selectedEnd.getTime() - selectedStart.getTime() < 60 * 1000) {
    selectedEnd = new Date(selectedStart.getTime() + 60 * 1000)
  }
  return selectedEnd.getTime() <= end ? [selectedStart, selectedEnd] : [new Date(selectedEnd.getTime() - 60 * 1000), new Date(end)]
}

function cleanupTimelineSelection() {
  window.removeEventListener('mousemove', handleTimelineSelectionMove)
  window.removeEventListener('mouseup', finishTimelineSelection)
}

function toggleTimelineCategory(key) {
  timelineCategoryFilter.value = timelineCategoryFilter.value === key ? 'all' : key
}

function tagType(result) {
  return { success: 'success', failed: 'danger', partial: 'warning', pending: 'warning' }[result] || 'info'
}

function resultLabel(row) {
  return row.result_display || { success: '成功', failed: '失败', partial: '部分成功', pending: '待处理' }[row.result] || row.result || '-'
}

function actorLabel(row) {
  return row?.actor_display || row?.actor_username || row?.metadata?.actor || row?.metadata?.user || 'system'
}

function moduleLabel(module) {
  return {
    ops: '运维平台',
    cmdb: 'CMDB',
    sqlaudit: 'SQL 审计',
    marketplace: '工具市场',
    eventwall: '事件中心',
  }[module] || module || '其他事件'
}

function eventCategoryKey(row) {
  const key = row?.event_category?.key || row?.metadata?.event_category || row?.metadata?.wall_category || ''
  if (eventCategoryOptions.some(item => item.key === key)) return key
  const traits = [row?.resource_type, row?.action, row?.metadata?.event_type, row?.metadata?.event_source_type]
    .map(value => String(value || '').toLowerCase())
  if (traits.some(value => ['host_task', 'host_task_batch', 'host_task_schedule', 'task', 'task_center', 'automation_task', 'scheduled_task'].includes(value))) {
    return 'task_center'
  }
  if (traits.some(value => ['deployment', 'deployment_approval_flow', 'deploy', 'deploy_finish', 'rollback', 'rerun', 'pipeline', 'build', 'start', 'stop', 'remove'].includes(value))) {
    return 'application_release'
  }
  return 'ops_transaction'
}

function eventCategoryLabel(row) {
  return row?.event_category?.label || eventCategoryOptions.find(item => item.key === eventCategoryKey(row))?.label || '运维事务'
}

function environmentLabel(row) {
  return environmentDisplayName(row?.environment) || '未标注环境'
}

function environmentDisplayName(value) {
  return environmentNameMap.value[value] || value || ''
}

function systemLabel(row) {
  return row?.system_name || row?.business_line || '-'
}

function eventTitle(row) {
  return row?.title || '-'
}

function eventDescription(row) {
  const category = eventCategoryKey(row)
  if (category === 'application_release') return row?.summary || row?.detail || ''
  if (category === 'db_change') return dbChangeDescription(row)
  if (category === 'config_change') return configChangeDescription(row)
  return row?.summary || row?.detail || ''
}

function dbChangeDescription(row) {
  const metadata = row?.metadata || {}
  const database = metadata.database || metadata.db || metadata.schema || ''
  const table = metadata.table || metadata.table_name || metadata.tables || ''
  const target = [database, Array.isArray(table) ? table.join(',') : table].filter(Boolean).join('.')
  const sqlType = sqlTypeLabel(metadata.sql_type || metadata.change_type || row?.action)
  const affectedRows = metadata.affected_rows
  const parts = []
  if (target) parts.push(`对象 ${target}`)
  if (sqlType) parts.push(`类型 ${sqlType}`)
  if (affectedRows !== undefined && affectedRows !== null && affectedRows !== '') parts.push(`影响 ${affectedRows} 行`)
  if (parts.length) return `DB 变更：${parts.join('，')}`
  return row?.summary || row?.detail || ''
}

function configChangeDescription(row) {
  const metadata = row?.metadata || {}
  const configKey = metadata.config_key || metadata.key || row?.resource_name || ''
  const before = metadata.before
  const after = metadata.after
  const parts = []
  if (configKey) parts.push(`配置项 ${configKey}`)
  if (before !== undefined && before !== null && before !== '') parts.push(`从 ${before}`)
  if (after !== undefined && after !== null && after !== '') parts.push(`改为 ${after}`)
  if (parts.length) return `配置变更：${parts.join('，')}`
  return row?.summary || row?.detail || ''
}

function sqlTypeLabel(value) {
  return {
    alter_index: '索引调整',
    data_fix: '数据修复',
    alter_table: '表结构变更',
    ddl: 'DDL',
    dml: 'DML',
    execute: '执行 SQL',
  }[value] || value || ''
}

function releaseService(row) {
  return row?.metadata?.service || row?.metadata?.service_name || row?.metadata?.app_name || row?.application || row?.resource_name || '-'
}

function releaseVersion(row) {
  const changes = row?.changes || {}
  return row?.metadata?.version ||
    row?.metadata?.release_version ||
    row?.metadata?.image_tag ||
    row?.metadata?.build_number ||
    changes?.version?.after ||
    changes?.image_tag?.after ||
    '-'
}

function releaseAction(row) {
  return {
    deploy: '发布',
    deploy_finish: '发布完成',
    release: '发布',
    deployment: '发布',
    rollback: '回滚',
    rerun: '重跑',
    build: '构建',
    pipeline: '流水线',
    sync: '同步',
    start: '启动',
    stop: '停止',
    remove: '下线',
    reject: '驳回',
    approve: '审批',
  }[row?.action] || row?.action || '-'
}

function scopeLabel(row) {
  return [environmentLabel(row), systemLabel(row)].filter(Boolean).join(' / ')
}

function visibleSuspicionReasons(row) {
  const hiddenReasons = new Set(['靠近故障前窗口', '处于故障分析窗口'])
  return (row?.suspicion_reasons || []).filter(reason => !hiddenReasons.has(reason))
}

function formatTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
}

function formatShortTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
}

function formatDotTime(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
}

function formatWindow(window) {
  if (!window?.start_at || !window?.end_at) return '最近事件窗口'
  return `${formatTime(window.start_at)} - ${formatTime(window.end_at)}`
}

function prettyJson(value) {
  return JSON.stringify(value || {}, null, 2)
}

onMounted(async () => {
  restoreFromRoute()
  await loadFilterOptions()
  await loadWall()
})

onUnmounted(cleanupTimelineSelection)
</script>

<style scoped>
.event-wall-page {
  display: flex;
  flex-direction: column;
  gap: 8px;
  color: #1f2329;
}

.panel {
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  background: linear-gradient(180deg, #ffffff 0%, #fffdf8 100%);
  box-shadow: 0 6px 16px rgba(15, 23, 42, 0.04);
}

.hero {
  min-height: 68px;
  padding: 12px 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.hero-copy,
.hero-title-row,
.hero-actions,
.section-head,
.axis-row {
  display: flex;
  align-items: center;
}

.hero-copy {
  gap: 4px;
  flex-wrap: wrap;
}

.hero-title-row {
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.hero-title-row h2 {
  margin: 0;
  font-size: 23px;
  font-weight: 700;
  line-height: 1.1;
}

.hero-tagline {
  color: #646a73;
  font-size: 13px;
  line-height: 1.45;
  max-width: 620px;
}

.hero-icon {
  width: 42px;
  height: 42px;
  border-radius: 14px;
  background: linear-gradient(180deg, #f3f7ff 0%, #ebf2ff 100%);
  border: 1px solid rgba(36, 91, 219, 0.12);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.8);
  color: #245bdb;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
}

.hero-actions {
  gap: 8px;
}

.hero-actions :deep(.el-button) {
  min-height: 32px;
  border-radius: 10px;
  font-weight: 500;
  padding: 0 14px;
}

.hero.panel {
  background: linear-gradient(135deg, #fbfdff 0%, #f7faff 52%, #f9fbfd 100%);
  border-color: rgba(36, 91, 219, 0.09);
  border-radius: 20px;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.04);
}

.suspect-row em,
.suspect-row small,
.lane-label span {
  font-style: normal;
  color: #646a73;
}

.query-panel {
  margin-top: -6px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.query-panel :deep(.el-input__wrapper),
.query-panel :deep(.el-select__wrapper) {
  border-radius: 10px;
  box-shadow: 0 0 0 1px #e5e7eb inset;
}

.query-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}

.query-title-block {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.query-title-block h3 {
  margin: 0;
  color: #0f172a;
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 0.01em;
}

.query-title-block span {
  color: #64748b;
  font-size: 11px;
  line-height: 1.2;
}

.query-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 4px;
  flex-shrink: 0;
}

.query-actions :deep(.el-button) {
  border-radius: 10px;
  min-height: 30px;
}

.query-body {
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.query-grid {
  display: grid;
  gap: 8px;
}

.query-grid--primary {
  grid-template-columns: repeat(4, minmax(150px, 1fr));
}

.query-grid--advanced {
  grid-template-columns: minmax(140px, 0.75fr) minmax(320px, 1.35fr) minmax(220px, 1fr);
}

.inline-filter {
  min-width: 0;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  column-gap: 8px;
}

.inline-filter > span {
  color: #475569;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.inline-filter.is-required > span::after {
  content: "*";
  margin-left: 2px;
  color: #ef4444;
}

.inline-filter :deep(.el-select),
.inline-filter :deep(.el-input),
.inline-filter :deep(.el-date-editor) {
  width: 100%;
}

.query-time {
  width: 100%;
}

.search-summary-bar {
  margin-top: 2px;
  padding-top: 8px;
  border-top: 1px solid rgba(241, 245, 249, 0.92);
  display: flex;
  align-items: center;
  gap: 6px;
  overflow-x: auto;
  scrollbar-width: none;
}

.trace-query-summary-bar::-webkit-scrollbar {
  display: none;
}

.query-pill {
  flex: 0 0 auto;
  min-height: 24px;
  padding: 2px 8px;
  border: 1px solid #e5e7eb;
  border-radius: 999px;
  background: #f8fafc;
  color: #4e5969;
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.query-pill:hover {
  border-color: #bacefd;
  color: #245bdb;
  background: #f7faff;
}

.query-pill i {
  margin-left: 5px;
  color: #8f959e;
  font-style: normal;
}

.query-pill:disabled {
  cursor: default;
  opacity: 1;
}

.query-pill:disabled:hover {
  border-color: #e5e7eb;
  color: #4e5969;
  background: #f8fafc;
}

.query-pill--clear {
  background: #fff;
  color: #245bdb;
}

.focus-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 8px;
}

.category-filter-row {
  margin-bottom: 10px;
  display: grid;
  grid-template-columns: minmax(220px, 1fr);
  gap: 8px;
}

.category-filter-row :deep(.el-input__wrapper),
.category-filter-row :deep(.el-select__wrapper) {
  border-radius: 10px;
  box-shadow: 0 0 0 1px #e5e7eb inset;
}

.category-filter-row.is-application_release {
  grid-template-columns: repeat(3, minmax(160px, 1fr));
}

.category-tabs {
  margin-bottom: 10px;
  padding: 4px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 12px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(248, 250, 252, 0.9));
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 4px;
}

.category-tabs button {
  min-width: 0;
  min-height: 40px;
  padding: 6px 10px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: #4e5969;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  cursor: pointer;
}

.category-tabs button:hover {
  background: rgba(51, 112, 255, 0.06);
}

.category-tabs button.active {
  background: #e8f0ff;
  color: #245bdb;
  box-shadow: inset 0 0 0 1px rgba(51, 112, 255, 0.08);
}

.category-tabs strong,
.category-tabs span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.category-tabs strong {
  font-size: 13px;
}

.category-tabs span {
  color: #8f959e;
  font-size: 12px;
}

.category-tabs button.active span {
  color: #245bdb;
}

.analysis-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.focus-panel,
.analysis-panel,
.category-panel,
.timeline-panel,
.table-panel {
  padding: 14px;
}

.category-table :deep(.el-table__header th),
.event-table :deep(.el-table__header th) {
  background: #f8fafc;
  color: #646a73;
  font-weight: 600;
}

.category-table :deep(.el-table__inner-wrapper::before),
.event-table :deep(.el-table__inner-wrapper::before) {
  display: none;
}

.category-table :deep(.el-table__row),
.event-table :deep(.el-table__row) {
  cursor: pointer;
}

.event-cell {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.event-cell strong,
.event-cell span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.event-cell strong {
  color: #1f2329;
  font-weight: 700;
}

.event-cell span {
  color: #646a73;
  font-size: 12px;
}

.timeline-panel {
  --timeline-label-width: 160px;
  --timeline-column-gap: 12px;
}

.section-head {
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
}

.section-head h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
}

.section-head span {
  color: #8f959e;
  font-size: 12px;
}

.suspect-list,
.analysis-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.suspect-row,
.scope-row,
.chain-row,
.lane-label,
.event-dot {
  border: 0;
  background: transparent;
  font: inherit;
  cursor: pointer;
}

.suspect-row {
  width: 100%;
  padding: 10px;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  display: grid;
  grid-template-columns: 52px minmax(0, 1fr) 190px;
  gap: 10px;
  text-align: left;
}

.suspect-row:hover,
.scope-row:hover,
.chain-row:hover {
  border-color: rgba(51, 112, 255, 0.24);
  background: #f7faff;
}

.scope-row,
.chain-row {
  width: 100%;
  padding: 10px;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  display: grid;
  gap: 5px 10px;
  text-align: left;
}

.scope-row {
  grid-template-columns: minmax(0, 1fr) auto;
}

.scope-row span,
.chain-row {
  min-width: 0;
}

.scope-row strong,
.scope-row em,
.scope-row small,
.chain-row strong,
.chain-row span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.scope-row span {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.scope-row em,
.scope-row small,
.chain-row span {
  color: #646a73;
  font-size: 12px;
  font-style: normal;
}

.scope-row b {
  color: #245bdb;
}

.scope-row small {
  grid-column: 1 / -1;
}

.score {
  width: 40px;
  height: 40px;
  border-radius: 8px;
  background: #e8f0ff;
  color: #245bdb;
  display: grid;
  place-items: center;
}

.suspect-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.suspect-main b,
.suspect-main em {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.reason-stack {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  flex-wrap: wrap;
}

.reason-stack i,
.reason-tags span {
  padding: 2px 7px;
  border-radius: 6px;
  background: #f2f3f5;
  color: #4e5969;
  font-size: 12px;
  font-style: normal;
}

.axis-row {
  display: grid;
  grid-template-columns: var(--timeline-label-width) minmax(0, 1fr);
  gap: var(--timeline-column-gap);
  align-items: center;
  font-size: 12px;
  color: #646a73;
}

.axis-label {
  height: 34px;
  padding: 0 10px;
  border-radius: 8px;
  background: #f7f8fa;
  color: #245bdb;
  display: flex;
  align-items: center;
  font-weight: 700;
}

.axis-track {
  height: 34px;
  padding: 0 12px;
  border-radius: 8px;
  background: #f7f8fa;
  position: relative;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  cursor: default;
  user-select: none;
}

.axis-track.selecting {
  background: #eef4ff;
}

.axis-track strong {
  height: 2px;
  border-radius: 999px;
  background: linear-gradient(90deg, rgba(51, 112, 255, 0.2), rgba(51, 112, 255, 0.55), rgba(51, 112, 255, 0.2));
  position: relative;
  display: block;
}

.axis-track span {
  color: #646a73;
}

.axis-track strong > em {
  position: absolute;
  left: 50%;
  bottom: 8px;
  transform: translateX(-50%);
  padding: 2px 7px;
  border-radius: 6px;
  background: #1f2329;
  color: #fff;
  font-size: 11px;
  font-style: normal;
  white-space: nowrap;
  pointer-events: none;
}

.axis-selection {
  position: absolute;
  top: -8px;
  bottom: -8px;
  min-width: 4px;
  border-radius: 999px;
  background: rgba(36, 91, 219, 0.18);
  box-shadow: inset 0 0 0 1px rgba(36, 91, 219, 0.3);
  pointer-events: none;
}

.axis-row strong {
  color: #245bdb;
}

.timeline-panel:has(.lane-row:only-child) {
  --timeline-label-width: 148px;
}

.lane-stack {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.lane-row {
  display: grid;
  grid-template-columns: var(--timeline-label-width) minmax(0, 1fr);
  gap: var(--timeline-column-gap);
  align-items: center;
}

.lane-stack:has(.lane-row:only-child) .lane-track {
  min-height: 118px;
}

.lane-stack:has(.lane-row:only-child) .event-dot {
  width: 156px;
  padding: 7px 10px;
}

.lane-label {
  width: 100%;
  min-width: 0;
  min-height: 72px;
  padding: 9px 10px;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  background: linear-gradient(180deg, #ffffff, #f8fafc);
  color: #1f2329;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 3px;
  text-align: left;
  box-shadow: 0 6px 14px rgba(15, 23, 42, 0.035);
  cursor: pointer;
}

.lane-label:hover {
  border-color: rgba(51, 112, 255, 0.28);
  background: #f7faff;
}

.lane-label strong,
.lane-label span,
.lane-label em {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.lane-label strong {
  font-size: 13px;
}

.lane-label span {
  color: #646a73;
  font-size: 12px;
}

.lane-label em {
  color: #8f959e;
  font-size: 11px;
  font-style: normal;
}

.lane-row.active .lane-label {
  border-color: rgba(51, 112, 255, 0.32);
  background: linear-gradient(180deg, #e8f0ff, #f7faff);
  color: #245bdb;
  box-shadow: inset 0 0 0 1px rgba(51, 112, 255, 0.08);
}

.lane-row.active .lane-label span,
.lane-row.active .lane-label em {
  color: #245bdb;
}

.lane-row.empty .lane-label {
  background: #fbfbfc;
}

.lane-track {
  position: relative;
  min-height: 72px;
  border-radius: 8px;
  background: #f7f8fa;
  overflow: hidden;
  cursor: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24'%3E%3Cpath d='M12 3v18M3 12h18' stroke='%231f2329' stroke-width='2' stroke-linecap='round'/%3E%3Ccircle cx='12' cy='12' r='2' fill='%231f2329'/%3E%3C/svg%3E") 12 12, crosshair;
  user-select: none;
}

.lane-track.selecting {
  background: #eef4ff;
}

.lane-selection {
  position: absolute;
  top: 0;
  bottom: 0;
  min-width: 4px;
  border-radius: 8px;
  background: rgba(36, 91, 219, 0.12);
  box-shadow: inset 0 0 0 1px rgba(36, 91, 219, 0.22);
  pointer-events: none;
  z-index: 2;
}

.lane-selection em {
  position: absolute;
  left: 50%;
  top: 6px;
  transform: translateX(-50%);
  padding: 2px 7px;
  border-radius: 6px;
  background: #1f2329;
  color: #fff;
  font-size: 11px;
  font-style: normal;
  white-space: nowrap;
}

.event-dot {
  position: absolute;
  top: 9px;
  width: 118px;
  transform: translateX(-12px);
  padding: 5px 8px;
  border: 1px solid #dee0e3;
  border-radius: 8px;
  background: #fff;
  text-align: left;
  overflow: hidden;
  box-shadow: 0 5px 12px rgba(15, 23, 42, 0.05);
  transition: transform 0.16s ease, box-shadow 0.16s ease, border-color 0.16s ease;
  z-index: 3;
}

.event-dot:hover {
  z-index: 80 !important;
  border-color: rgba(51, 112, 255, 0.45);
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.14);
  transform: translateX(-12px) translateY(-2px);
}

.event-dot span,
.event-dot strong {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.event-dot span {
  font-size: 11px;
  color: #8f959e;
}

.event-dot strong {
  font-size: 12px;
  font-weight: 600;
}

.event-dot.is-failed,
.event-dot.is-suspect {
  border-color: #f54a45;
}

.event-dot.is-partial,
.event-dot.is-pending {
  border-color: #ffb11a;
}

.event-table :deep(.el-table__row) {
  cursor: pointer;
}

.detail-stack {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.detail-section {
  padding: 10px 12px;
  border: 1px solid #dee0e3;
  border-radius: 8px;
  background: #fff;
}

.detail-section--main {
  background: #f7faff;
  border-color: #bacefd;
}

.detail-section strong {
  font-size: 15px;
}

.detail-section p {
  margin: 4px 0 0;
  color: #646a73;
  line-height: 1.5;
}

.detail-section h4 {
  margin: 0 0 8px;
  font-size: 13px;
}

.detail-section--meta {
  font-size: 12px;
  padding: 8px 10px;
}

.detail-section--meta .detail-row {
  gap: 10px;
  padding: 6px 0;
}

.detail-section--meta .detail-row span,
.detail-section--meta .detail-row b {
  font-size: 12px;
}

.chain-event-row {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid #dee0e3;
  border-radius: 8px;
  background: #fff;
  display: grid;
  grid-template-columns: 145px minmax(0, 1fr);
  gap: 4px 10px;
  text-align: left;
  cursor: pointer;
}

.chain-event-row + .chain-event-row {
  margin-top: 6px;
}

.chain-event-row:hover,
.chain-event-row.active {
  border-color: #bacefd;
  background: #f7faff;
}

.chain-event-row time {
  color: #8f959e;
  font-size: 12px;
}

.chain-event-row strong,
.chain-event-row span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chain-event-row span {
  grid-column: 2;
  color: #646a73;
  font-size: 12px;
}

.detail-row {
  display: grid;
  grid-template-columns: 96px minmax(0, 1fr);
  gap: 12px;
  padding: 7px 0;
  border-bottom: 1px solid #eff0f1;
}

.detail-row:last-child {
  border-bottom: 0;
}

.detail-row span {
  color: #8f959e;
}

.detail-row b {
  min-width: 0;
  font-weight: 500;
  overflow-wrap: anywhere;
}

:deep(.event-detail-drawer .el-drawer__header) {
  margin-bottom: 0;
  padding: 10px 18px 2px;
}

:deep(.event-detail-drawer .el-drawer__body) {
  padding: 0 18px 18px;
}

.reason-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

pre {
  margin: 0;
  padding: 10px;
  border-radius: 8px;
  background: #f7f8fa;
  color: #1f2329;
  overflow: auto;
  font-size: 12px;
  line-height: 1.6;
}

@media (max-width: 1100px) {
  .analysis-grid,
  .query-grid--primary,
  .query-grid--advanced {
    grid-template-columns: 1fr 1fr;
  }

  .suspect-row {
    grid-template-columns: 44px minmax(0, 1fr);
  }

  .reason-stack {
    grid-column: 1 / -1;
    justify-content: flex-start;
  }
}

@media (max-width: 760px) {
  .hero,
  .hero-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .hero-tagline {
    max-width: none;
  }

  .focus-grid,
  .analysis-grid,
  .query-grid--primary,
  .query-grid--advanced,
  .category-tabs,
  .axis-row,
  .lane-row {
    grid-template-columns: 1fr;
  }

  .category-filter-row {
    grid-template-columns: 1fr;
  }

  .category-filter-row.is-application_release {
    grid-template-columns: 1fr;
  }

  .query-head,
  .query-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .query-title-block {
    align-items: flex-start;
    gap: 3px;
  }

  .inline-filter {
    grid-template-columns: 1fr;
    row-gap: 4px;
  }

  .chain-event-row {
    grid-template-columns: 1fr;
  }

  .chain-event-row span {
    grid-column: 1;
  }
}
</style>
