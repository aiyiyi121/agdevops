<template>
  <div class="event-source-page fade-in">
    <section class="hero panel">
      <div class="hero-copy">
        <div class="hero-title-row">
          <span class="hero-icon">
            <el-icon><Share /></el-icon>
          </span>
          <h2>事件源</h2>
          <span class="hero-tagline">汇聚发布、变更、任务与 Webhook 外部事件，按时间线沉淀排障线索，辅助故障定位与 AIOps 分析。</span>
        </div>
      </div>
      <div class="hero-actions">
        <el-button size="small" :loading="loading" @click="loadAll">
          <el-icon><RefreshRight /></el-icon>
          刷新
        </el-button>
      </div>
    </section>

    <EventWallTabs />

    <section class="source-board">
      <div class="panel source-map-panel" v-loading="loading">
        <div class="section-head">
          <h3>平台内置事件源</h3>
          <div class="section-head-actions">
            <span>{{ builtinSources.length }} 个事件源</span>
          </div>
        </div>
        <div class="source-card-grid source-card-grid--builtin">
          <article
            v-for="item in builtinSources"
            :key="item.code"
            class="source-card"
            :class="{ disabled: !item.enabled }"
          >
            <header>
              <div class="source-avatar" :class="`is-${item.source_kind}`">{{ sourceInitial(item) }}</div>
              <span>
                <strong>{{ item.name }}</strong>
                <em>事件源类型：{{ item.code }}</em>
              </span>
              <i class="status-dot" :class="item.enabled ? 'is-enabled' : 'is-disabled'"></i>
            </header>
            <p>{{ item.description || `${typeLabel(item.source_type)} 事件进入故障分析时间线` }}</p>
            <div class="source-meta">
              <span>{{ typeLabel(item.source_type) }}</span>
              <span>{{ sourceEventCategoryLabel(item) }}</span>
              <span>{{ enabledLabel(item) }}</span>
            </div>
            <footer>
              <span>
                <b>{{ item.recent_event_count || 0 }}</b>
                <em>7 天事件</em>
              </span>
              <span>
                <b>{{ formatShortTime(item.last_event_at || item.last_sync_at) }}</b>
                <em>最近写入</em>
              </span>
            </footer>
            <div class="card-actions">
              <el-button size="small" text type="primary" @click="openEvents(item)">看事件</el-button>
            </div>
          </article>
        </div>
        <el-empty v-if="!loading && !builtinSources.length" description="暂无平台内置事件源" />
      </div>

      <div class="panel source-map-panel" v-loading="loading">
        <div class="section-head">
          <h3>外部接入事件源</h3>
          <div class="section-head-actions section-head-actions--external">
            <span>{{ externalSources.length }} 个事件源</span>
            <el-button size="small" text type="primary" @click="helpDialogVisible = true">接入帮助</el-button>
            <el-button v-if="canManageSources" size="small" type="primary" @click="openCreateDialog">
              <el-icon><Plus /></el-icon>
              新建接入
            </el-button>
          </div>
        </div>
        <div class="source-filter-bar">
          <button
            v-for="item in enabledSummary"
            :key="item.value"
            type="button"
            class="source-filter-pill"
            :class="{ active: enabledFilter === item.value }"
            @click="enabledFilter = enabledFilter === item.value ? '' : item.value"
          >
            <em :class="item.value === 'enabled' ? 'is-enabled' : 'is-disabled'"></em>
            {{ item.label }} <b>{{ item.count }}</b>
          </button>
          <button v-if="enabledFilter" type="button" class="source-filter-pill clear" @click="clearAllFilters">清空</button>
        </div>
        <div class="source-card-grid">
          <article
            v-for="item in externalSources"
            :key="item.code"
            class="source-card source-card--clickable"
            :class="{ disabled: !item.enabled }"
            role="button"
            tabindex="0"
            @click="openSpec(item)"
            @keydown.enter.prevent="openSpec(item)"
          >
            <header>
              <div class="source-avatar" :class="`is-${item.source_kind}`">{{ sourceInitial(item) }}</div>
              <span>
                <strong>{{ item.name }}</strong>
                <em>事件源类型：{{ item.code }}</em>
              </span>
              <i class="status-dot" :class="item.enabled ? 'is-enabled' : 'is-disabled'"></i>
            </header>
            <p>{{ item.description || `${typeLabel(item.source_type)} 事件进入故障分析时间线` }}</p>
            <div class="source-meta">
              <span>{{ typeLabel(item.source_type) }}</span>
              <span>{{ sourceEventCategoryLabel(item) }}</span>
              <span>{{ enabledLabel(item) }}</span>
            </div>
            <footer>
              <span>
                <b>{{ item.recent_event_count || 0 }}</b>
                <em>7 天事件</em>
              </span>
              <span>
                <b>{{ formatShortTime(item.last_event_at || item.last_sync_at) }}</b>
                <em>最近写入</em>
              </span>
            </footer>
            <div class="card-actions">
              <el-button size="small" text type="primary" @click.stop="openEvents(item)">看事件</el-button>
              <el-button v-if="canManageSources && item.source_kind === 'external'" size="small" text @click.stop="openEditAccess(item)">编辑</el-button>
              <el-button v-if="canDeleteSource(item)" size="small" text type="danger" @click.stop="removeSource(item)">删除</el-button>
            </div>
          </article>
        </div>
        <el-empty v-if="!loading && !externalSources.length" description="当前筛选条件下没有外部接入事件源" />
      </div>
    </section>

    <el-dialog v-model="helpDialogVisible" title="Webhook 接入帮助" width="760px" append-to-body destroy-on-close>
      <div class="help-doc">
        <section>
          <h4>接入入口</h4>
          <p>外部系统通过统一 Webhook 写入事件中心，平台按事件源类型区分来源。</p>
          <pre>POST /api/event-sources/{type}/ingest/
Authorization: Bearer &lt;token&gt;
Content-Type: application/json</pre>
          <p>也可以使用请求头 <code>X-Event-Token: &lt;token&gt;</code> 传递令牌。</p>
        </section>

        <section>
          <h4>配置步骤</h4>
          <div class="help-step-grid">
            <span><b>1</b> 在事件源中创建或编辑外部接入，选择默认事件分类。</span>
            <span><b>2</b> 复制平台生成的 Webhook 地址和令牌。</span>
            <span><b>3</b> 在 ArgoCD、GitLab、Jenkins、Jira 中配置 Webhook URL 和请求头。</span>
            <span><b>4</b> 推送后在事件中心按环境、系统、事件源过滤验证入库结果。</span>
          </div>
        </section>

        <section>
          <h4>环境字段对应</h4>
          <p>载荷中的 <code>environment</code> 用于匹配事件中心里的事件环境。</p>
          <div class="help-rule-list">
            <span v-for="item in ingestSpec.environment_rules || []" :key="item">{{ item }}</span>
          </div>
        </section>

        <section>
          <h4>系统配置要点</h4>
          <div class="help-source-grid">
            <article>
              <strong>ArgoCD</strong>
              <span>推荐接入 Application 同步和健康状态事件；Degraded、Missing、Unknown 会被标记为失败。</span>
            </article>
            <article>
              <strong>GitLab</strong>
              <span>推荐接入 Pipeline、Deployment、Merge Request 事件；pipeline 会归入应用发布。</span>
            </article>
            <article>
              <strong>Jenkins</strong>
              <span>推荐推送 job_name、build_number、status；failure、failed、aborted 会被标记为失败。</span>
            </article>
            <article>
              <strong>Jira</strong>
              <span>推荐接入 Issue 创建、流转和故障工单事件；issue key 会作为资源 ID。</span>
            </article>
          </div>
        </section>

        <section>
          <h4>标准载荷示例</h4>
          <pre>{
  "event_id": "deploy-20260509-001",
  "event_category": "application_release",
  "title": "payment-api 发布失败",
  "result": "failed",
  "severity": "danger",
  "system_name": "交易",
  "environment": "ecommerce-prod",
  "application": "payment-api",
  "resource_type": "jenkins_build",
  "resource_id": "payment-api#184"
}</pre>
        </section>
      </div>
    </el-dialog>

    <el-dialog v-model="sourceDialogVisible" title="新建自定义 Webhook 接入" width="620px" append-to-body destroy-on-close>
      <div class="access-create-tip">
        <strong>接入流程</strong>
        <span>先选择默认事件分类并创建来源，平台会立即生成接收地址和令牌；外部系统只负责 POST 事务事件。</span>
      </div>
      <el-form label-position="top" :model="sourceForm" class="access-create-form">
        <el-form-item label="接入名称">
          <el-input v-model="sourceForm.name" placeholder="例如：内部发布平台" />
        </el-form-item>
        <el-form-item label="接入类型（用于生成 Webhook 地址，创建后不建议修改）">
          <el-input v-model="sourceForm.code" placeholder="例如：internal-release" />
        </el-form-item>
        <el-form-item label="默认事件分类">
          <el-select v-model="sourceForm.event_category" placeholder="请选择接入事件分类" style="width: 100%">
            <el-option v-for="item in eventCategoryOptions" :key="item.key" :label="item.label" :value="item.key" />
          </el-select>
        </el-form-item>
        <el-form-item label="来源系统地址（可选，仅用于备注来源，不是平台接收地址）">
          <el-input v-model="sourceForm.endpoint_url" placeholder="例如：https://release.example.com" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="sourceForm.description" type="textarea" :rows="3" placeholder="说明这个接入会推送哪些事务事件" />
        </el-form-item>
        <div class="access-endpoint-preview">
          <span>创建后的平台接收地址</span>
          <strong>{{ endpointPreview }}</strong>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="sourceDialogVisible = false">取消</el-button>
        <el-button @click="resetSourceForm">重置</el-button>
        <el-button type="primary" :loading="saving" @click="saveSource">创建并签发令牌</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="specDrawerVisible" title="事件源接入规范" size="660px" append-to-body destroy-on-close class="event-source-spec-drawer">
      <div class="drawer-stack">
        <section class="detail-section detail-section--main">
          <strong>{{ activeSource?.name || '自定义事件源' }}</strong>
          <p>{{ activeSource?.description || '外部系统按统一载荷写入事件中心，进入故障分析时间线。' }}</p>
          <div class="spec-connection-box">
            <div class="connection-line">
              <span>接入地址</span>
              <b>http://&lt;sxdevops地址&gt;{{ endpointFor(activeSource) }}</b>
            </div>
            <div class="connection-line">
              <span>接入令牌</span>
              <b>{{ activeSource?.token_preview || '未签发' }}</b>
              <em>完整令牌仅在签发时展示，规范中显示令牌预览。</em>
              <el-button v-if="canManageSources && activeSource?.source_kind === 'external'" size="small" text type="primary" @click="reissueActiveToken">重新签发</el-button>
            </div>
          </div>
        </section>
        <section class="detail-section">
          <h4>必填字段</h4>
          <div class="chip-wrap">
            <span v-for="item in ingestSpec.required_fields || []" :key="item">{{ item }}</span>
          </div>
        </section>
        <section class="detail-section">
          <h4>推荐字段</h4>
          <div class="chip-wrap">
            <span v-for="item in ingestSpec.recommended_fields || []" :key="item">{{ item }}</span>
          </div>
        </section>
        <section class="detail-section">
          <h4>环境字段对应</h4>
          <p>载荷中的 <code>environment</code> 会按事件环境里的环境标识或环境别名进行匹配。</p>
          <div class="mapping-list mapping-list--stack">
            <span v-for="item in ingestSpec.environment_rules || []" :key="item">{{ item }}</span>
          </div>
        </section>
        <section class="detail-section">
          <h4>事件分类结构</h4>
          <div class="category-spec-list">
            <div v-for="item in ingestSpec.event_categories || eventCategoryOptions" :key="item.key">
              <strong>{{ item.label }}</strong>
              <span>{{ item.description || '-' }}</span>
              <em>必填：{{ (item.required_fields || []).join(' / ') || 'title / event_category' }}</em>
            </div>
          </div>
        </section>
        <section class="detail-section">
          <h4>字段映射</h4>
          <div class="mapping-list">
            <span v-for="entry in mappingEntries(activeSource || {})" :key="entry">{{ entry }}</span>
            <em v-if="!mappingEntries(activeSource || {}).length">暂无字段映射</em>
          </div>
        </section>
        <section class="detail-section">
          <h4>示例载荷</h4>
          <pre>{{ prettyJson(ingestSpec.example || {}) }}</pre>
        </section>
      </div>
    </el-drawer>

    <el-dialog v-model="editDialogVisible" title="编辑事件源接入" width="620px" append-to-body destroy-on-close>
      <el-form label-position="top" :model="sourceEditForm" class="access-edit-form">
        <el-form-item label="接入类型">
          <el-input v-model="sourceEditForm.code" placeholder="例如：jenkins-prod" />
        </el-form-item>
        <el-form-item label="Webhook 接收地址">
          <el-input :model-value="editEndpointPreview" readonly>
            <template #append>
              <el-button @click="copyText(editEndpointPreview, '接入地址已复制')">复制</el-button>
            </template>
          </el-input>
        </el-form-item>
        <el-form-item label="接入名称">
          <el-input v-model="sourceEditForm.name" />
        </el-form-item>
        <el-form-item label="默认事件分类">
          <el-select v-model="sourceEditForm.event_category" style="width: 100%">
            <el-option v-for="item in eventCategoryOptions" :key="item.key" :label="item.label" :value="item.key" />
          </el-select>
        </el-form-item>
        <el-form-item label="来源系统地址（可选，仅备注）">
          <el-input v-model="sourceEditForm.endpoint_url" placeholder="例如：https://release.example.com" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="sourceEditForm.description" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="启用状态">
          <el-switch v-model="sourceEditForm.enabled" active-text="启用" inactive-text="停用" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveEditAccess">保存修改</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="tokenDialogVisible" title="接入令牌" width="560px" append-to-body>
      <div class="token-box">
        <span>完整令牌只在本次签发后展示，请配置到外部系统的请求头；后续可在接入规范查看令牌预览。</span>
        <pre>{{ issuedToken }}</pre>
      </div>
      <template #footer>
        <el-button @click="copyToken">复制令牌</el-button>
        <el-button type="primary" @click="tokenDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, RefreshRight, Share } from '@element-plus/icons-vue'
import {
  createEventSource,
  deleteEventSource,
  getEventSourceIngestSpec,
  getEventSourceSummary,
  getEventSources,
  issueEventSourceToken,
  updateEventSource,
} from '@/api/modules/eventwall'
import EventWallTabs from '@/components/eventwall/EventWallTabs.vue'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()
const loading = ref(false)
const saving = ref(false)
const sources = ref([])
const summary = ref({})
const ingestSpec = ref({})
const enabledFilter = ref('')
const specDrawerVisible = ref(false)
const sourceDialogVisible = ref(false)
const editDialogVisible = ref(false)
const tokenDialogVisible = ref(false)
const helpDialogVisible = ref(false)
const activeSource = ref(null)
const editingSource = ref(null)
const issuedToken = ref('')
const sourceForm = reactive({ name: '', code: '', description: '', endpoint_url: '', event_category: 'ops_transaction' })
const sourceEditForm = reactive({ code: '', name: '', description: '', endpoint_url: '', event_category: 'ops_transaction', enabled: false })

const canManageSources = computed(() => authStore.hasPermission('eventwall.source.manage'))
const eventCategoryOptions = [
  { key: 'application_release', label: '应用发布', description: '应用发布、回滚、启停、下线和流水线发布类事件。' },
  { key: 'db_change', label: 'DB变更', description: 'SQL 上线、数据库结构变更、数据修复和执行结果类事件。' },
  { key: 'config_change', label: '配置变更', description: '配置发布、参数调整、网络策略、域名路由和中间件配置类事件。' },
  { key: 'ops_transaction', label: '运维事务', description: '权限开通、网络配置、机器申请释放和通用运维处理类事件。' },
  { key: 'task_center', label: '任务调度', description: '平台内任务中心与外部自动化任务平台推送的任务执行、定时编排和批量处理事件。' },
]
const builtinSources = computed(() => sortSources(sources.value.filter(source => source.source_kind === 'builtin')))
const externalSources = computed(() => {
  const external = sources.value.filter(source => source.source_kind === 'external')
  const filtered = enabledFilter.value
    ? external.filter(source => (enabledFilter.value === 'enabled' ? source.enabled : !source.enabled))
    : external
  return sortSources(filtered)
})
const enabledSummary = computed(() => {
  const external = sources.value.filter(source => source.source_kind === 'external')
  return [
    { value: 'enabled', label: '启用' },
    { value: 'disabled', label: '停用' },
  ].map((item) => {
    const count = external.filter(source => (item.value === 'enabled' ? source.enabled : !source.enabled)).length
    return { ...item, count }
  })
})
const endpointPreview = computed(() => endpointFor({ code: sourceForm.code.trim() || '{type}' }))
const editEndpointPreview = computed(() => endpointFor({ code: sourceEditForm.code.trim() || editingSource.value?.code || '{type}' }))

function typeLabel(type) {
  return {
    builtin_workorder: '工单系统',
    builtin_task: '任务中心',
    jira: 'Jira',
    jenkins: 'Jenkins',
    argocd: 'ArgoCD',
    gitlab: 'GitLab',
    custom: '自定义事件源',
  }[type] || type || '-'
}

function sourceEventCategoryKey(item) {
  return item?.config?.default_event_category || ''
}

function sourceEventCategoryLabel(item) {
  const key = sourceEventCategoryKey(item)
  if (!key && item?.source_kind === 'builtin') return '多分类'
  return eventCategoryOptions.find(option => option.key === key)?.label || '-'
}

function enabledLabel(item) {
  return item?.enabled ? '启用' : '停用'
}

function canDeleteSource(item) {
  return canManageSources.value && item?.source_kind === 'external'
}

function sourceInitial(item) {
  return String(item?.name || item?.code || '?').trim().slice(0, 1).toUpperCase()
}

function sortSources(list) {
  return [...list].sort((a, b) => {
    if (a.enabled !== b.enabled) return a.enabled ? -1 : 1
    return (b.recent_event_count || 0) - (a.recent_event_count || 0)
  })
}

function formatShortTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
}

function mappingEntries(item) {
  return Object.entries(item?.field_mapping || {}).slice(0, 8).map(([from, to]) => `${from} -> ${to}`)
}

function endpointFor(item) {
  const type = item?.code || '{type}'
  return (ingestSpec.value.endpoint_template || '/api/event-sources/{type}/ingest/')
    .replaceAll('{type}', type)
    .replaceAll('{code}', type)
}

function prettyJson(value) {
  return JSON.stringify(value || {}, null, 2)
}

async function loadAll() {
  loading.value = true
  try {
    const [sourceResponse, summaryResponse, specResponse] = await Promise.all([
      getEventSources({ page_size: 100 }),
      getEventSourceSummary(),
      getEventSourceIngestSpec(),
    ])
    sources.value = sourceResponse.results || sourceResponse || []
    summary.value = summaryResponse || {}
    ingestSpec.value = specResponse || {}
  } finally {
    loading.value = false
  }
}

function openEvents(item) {
  router.push({ path: '/events/wall', query: { event_source_code: item.code } })
}

function openSpec(item) {
  activeSource.value = item || null
  specDrawerVisible.value = true
}

function openCreateDialog() {
  resetSourceForm()
  sourceDialogVisible.value = true
}

function resetSourceForm() {
  Object.assign(sourceForm, { name: '', code: '', description: '', endpoint_url: '', event_category: 'ops_transaction' })
}

function openEditAccess(item) {
  if (!item || item.source_kind !== 'external') return
  editingSource.value = item
  Object.assign(sourceEditForm, {
    code: item.code,
    name: item.name || '',
    description: item.description || '',
    endpoint_url: item.endpoint_url || '',
    event_category: sourceEventCategoryKey(item) || 'ops_transaction',
    enabled: Boolean(item.enabled),
  })
  editDialogVisible.value = true
}

function clearAllFilters() {
  enabledFilter.value = ''
}

async function saveSource() {
  if (!sourceForm.name.trim() || !sourceForm.code.trim() || !sourceForm.event_category) {
    ElMessage.warning('请填写名称、接入类型和默认事件分类')
    return
  }
  saving.value = true
  try {
    const { event_category, ...formData } = sourceForm
    const createdSource = await createEventSource({
      ...formData,
      source_kind: 'external',
      source_type: 'custom',
      enabled: false,
      status: 'not_configured',
      auth_type: 'webhook',
      config: { default_event_category: event_category, created_from: 'event_source_page' },
      field_mapping: { event_id: 'event_id', event_category: 'event_category', occurred_at: 'occurred_at', title: 'title' },
    })
    const tokenResponse = await issueEventSourceToken(createdSource.code || sourceForm.code.trim())
    issuedToken.value = tokenResponse.token
    tokenDialogVisible.value = true
    sourceDialogVisible.value = false
    ElMessage.success('接入已创建并签发令牌')
    resetSourceForm()
    await loadAll()
  } finally {
    saving.value = false
  }
}

async function saveEditAccess() {
  if (!editingSource.value?.code) return
  if (!sourceEditForm.name.trim() || !sourceEditForm.code.trim() || !sourceEditForm.event_category) {
    ElMessage.warning('请填写接入名称、接入类型和默认事件分类')
    return
  }
  saving.value = true
  try {
    await updateEventSource(editingSource.value.code, {
      code: sourceEditForm.code.trim(),
      name: sourceEditForm.name.trim(),
      description: sourceEditForm.description,
      endpoint_url: sourceEditForm.endpoint_url,
      enabled: sourceEditForm.enabled,
      config: {
        ...(editingSource.value.config || {}),
        default_event_category: sourceEditForm.event_category,
      },
    })
    editDialogVisible.value = false
    ElMessage.success('接入配置已更新')
    await loadAll()
  } finally {
    saving.value = false
  }
}

async function copyToken() {
  if (!issuedToken.value) return
  await navigator.clipboard.writeText(issuedToken.value)
  ElMessage.success('令牌已复制')
}

async function copyText(text, message = '已复制') {
  if (!text) return
  await navigator.clipboard.writeText(text)
  ElMessage.success(message)
}

async function reissueActiveToken() {
  if (!activeSource.value?.code) return
  saving.value = true
  try {
    const tokenResponse = await issueEventSourceToken(activeSource.value.code)
    issuedToken.value = tokenResponse.token
    activeSource.value = {
      ...activeSource.value,
      token_preview: tokenResponse.token_preview,
      enabled: true,
      status: 'healthy',
    }
    tokenDialogVisible.value = true
    ElMessage.success('接入令牌已重新签发')
    await loadAll()
  } finally {
    saving.value = false
  }
}

async function removeSource(item) {
  if (!item?.code || item.source_kind !== 'external') return
  try {
    await ElMessageBox.confirm(`确认删除事件源「${item.name}」吗？删除后该接入地址将不可用，历史事件不会被删除。`, '删除事件源', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch (error) {
    return
  }
  await deleteEventSource(item.code)
  ElMessage.success('事件源已删除')
  if (activeSource.value?.code === item.code) activeSource.value = null
  if (editingSource.value?.code === item.code) editDialogVisible.value = false
  await loadAll()
}

onMounted(loadAll)
</script>

<style scoped>
.event-source-page {
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
.section-head {
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

.access-create-tip {
  margin-bottom: 12px;
  padding: 10px 12px;
  border: 1px solid rgba(51, 112, 255, 0.14);
  border-radius: 12px;
  background: #fff;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.access-create-tip strong {
  color: #1f2329;
  font-size: 14px;
}

.access-create-tip span {
  color: #646a73;
  font-size: 13px;
}

.access-create-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 12px;
}

.access-edit-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 12px;
}

.access-create-form :deep(.el-form-item:nth-child(5)),
.access-edit-form :deep(.el-form-item:nth-child(2)),
.access-edit-form :deep(.el-form-item:nth-child(5)),
.access-edit-form :deep(.el-form-item:nth-child(6)),
.access-endpoint-preview {
  grid-column: 1 / -1;
}

.access-endpoint-preview {
  margin-bottom: 14px;
  padding: 10px 12px;
  border-radius: 10px;
  background: #fff;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.access-endpoint-preview span {
  color: #8f959e;
  font-size: 12px;
}

.access-endpoint-preview strong {
  color: #245bdb;
  overflow-wrap: anywhere;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
}

.source-board {
  margin-top: -6px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.source-map-panel {
  padding: 14px;
}

.source-filter-bar {
  margin-bottom: 10px;
  padding: 4px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 12px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(248, 250, 252, 0.9));
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

.source-filter-pill {
  min-height: 28px;
  padding: 0 10px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: #4e5969;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  font: inherit;
  font-size: 12px;
  font-weight: 700;
}

.source-filter-pill:hover,
.source-filter-pill.active {
  background: #e8f0ff;
  color: #245bdb;
}

.source-filter-pill.clear {
  color: #245bdb;
  background: #fff;
  box-shadow: inset 0 0 0 1px rgba(51, 112, 255, 0.12);
}

.source-filter-pill b {
  font-size: 12px;
}

.source-filter-pill em {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #8f959e;
  flex: 0 0 auto;
}

.source-card-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.source-card {
  min-width: 0;
  padding: 12px;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 6px 18px rgba(31, 35, 41, 0.035);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.source-card:hover {
  border-color: rgba(51, 112, 255, 0.24);
  background: #f7faff;
}

.source-card--clickable {
  cursor: pointer;
}

.source-card--clickable:focus-visible {
  outline: 2px solid rgba(51, 112, 255, 0.32);
  outline-offset: 2px;
}

.source-card.disabled {
  background: #fbfbfc;
  color: #646a73;
}

.source-card header,
.source-card footer,
.source-meta,
.card-actions {
  display: flex;
  align-items: center;
}

.source-card header {
  gap: 8px;
}

.source-card header span {
  min-width: 0;
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 2px;
}

.source-card strong,
.source-card em,
.source-card p,
.source-meta span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-card header em,
.source-card footer em,
.source-meta span {
  color: #8f959e;
  font-size: 12px;
  font-style: normal;
}

.source-avatar {
  width: 30px;
  height: 30px;
  border-radius: 12px;
  background: #e8f0ff;
  color: #245bdb;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  font-size: 13px;
  font-weight: 700;
}

.source-avatar.is-external {
  background: #e8f8f3;
  color: #0c8f63;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #8f959e;
  flex: 0 0 auto;
}

.status-dot.is-enabled,
.source-filter-pill em.is-enabled {
  background: #34c759;
}

.status-dot.is-disabled,
.source-filter-pill em.is-disabled {
  background: #8f959e;
}

.source-card p {
  margin: 0;
  color: #4e5969;
  font-size: 13px;
}

.source-meta {
  gap: 6px;
  flex-wrap: wrap;
}

.source-meta span {
  max-width: 100%;
  padding: 2px 7px;
  border-radius: 6px;
  background: #f2f3f5;
}

.source-card footer {
  justify-content: space-between;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px solid #eff0f1;
}

.source-card footer span {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.source-card footer b {
  max-width: 120px;
  overflow: hidden;
  color: #1f2329;
  font-size: 14px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-actions {
  min-height: 24px;
  gap: 4px;
  flex-wrap: wrap;
}

.card-actions :deep(.el-button) {
  margin-left: 0;
  padding: 0 4px;
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

.section-head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #8f959e;
  font-size: 12px;
}

.section-head-actions :deep(.el-button) {
  padding: 0 4px;
  font-weight: 700;
}

.section-head-actions--external > span {
  margin-right: 12px;
}

.section-head-actions :deep(.el-button--primary) {
  padding: 5px 11px;
}

:deep(.event-source-spec-drawer .el-drawer__body) {
  padding: 0 18px 18px;
}

:deep(.event-source-spec-drawer .el-drawer__header) {
  margin-bottom: 0;
  padding: 10px 18px 0;
}

.drawer-stack {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.detail-section {
  padding: 12px;
  border: 1px solid #dee0e3;
  border-radius: 8px;
  background: #fff;
}

.detail-section--main {
  background: #f7faff;
  border-color: #bacefd;
}

.detail-section p {
  margin: 8px 0;
  color: #646a73;
  line-height: 1.6;
}

.detail-section h4 {
  margin: 0 0 10px;
  font-size: 14px;
}

.spec-connection-box {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.connection-line {
  padding: 8px 10px;
  border-radius: 8px;
  background: #fff;
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
}

.connection-line span {
  color: #1f2329;
  font-size: 12px;
  font-weight: 700;
}

.connection-line b {
  color: #245bdb;
  overflow-wrap: anywhere;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  font-weight: 700;
}

.connection-line em {
  color: #8f959e;
  font-size: 12px;
  font-style: normal;
}

.chip-wrap,
.mapping-list,
.help-rule-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.chip-wrap span,
.mapping-list span,
.help-rule-list span {
  padding: 2px 7px;
  border-radius: 6px;
  background: #f2f3f5;
  color: #4e5969;
  font-size: 12px;
}

.mapping-list--stack,
.help-rule-list {
  flex-direction: column;
}

.mapping-list--stack span,
.help-rule-list span {
  line-height: 1.6;
}

.mapping-list em {
  color: #8f959e;
  font-style: normal;
}

.category-spec-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.category-spec-list div {
  padding: 10px;
  border-radius: 8px;
  background: #f7f8fa;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.category-spec-list strong {
  color: #1f2329;
}

.category-spec-list span,
.category-spec-list em {
  color: #646a73;
  font-style: normal;
  font-size: 12px;
}

.help-doc {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.help-doc section {
  padding: 12px;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  background: #fff;
}

.help-doc h4 {
  margin: 0 0 8px;
  color: #1f2329;
  font-size: 14px;
}

.help-doc p {
  margin: 0 0 8px;
  color: #646a73;
  line-height: 1.6;
}

.help-doc code {
  color: #245bdb;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.help-step-grid,
.help-source-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.help-step-grid span,
.help-source-grid article {
  min-width: 0;
  padding: 10px;
  border-radius: 10px;
  background: #f7f8fa;
  color: #4e5969;
  font-size: 12px;
  line-height: 1.6;
}

.help-step-grid b {
  width: 18px;
  height: 18px;
  margin-right: 6px;
  border-radius: 999px;
  background: #e8f0ff;
  color: #245bdb;
  display: inline-grid;
  place-items: center;
  font-size: 11px;
}

.help-source-grid article {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.help-source-grid strong {
  color: #1f2329;
}

.token-box {
  display: flex;
  flex-direction: column;
  gap: 10px;
  color: #646a73;
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

@media (max-width: 980px) {
  .source-card-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

}

@media (max-width: 700px) {
  .hero,
  .hero-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .hero-tagline {
    max-width: none;
  }

  .access-create-form,
  .access-edit-form,
  .help-step-grid,
  .help-source-grid,
  .source-board,
  .source-card-grid {
    grid-template-columns: 1fr;
  }

}
</style>
