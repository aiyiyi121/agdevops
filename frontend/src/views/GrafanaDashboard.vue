<template>
  <div class="observability-page" :class="{ 'is-immersive': fullscreenVisible }">
    <section v-if="fullscreenVisible && selectedDashboardUrl" class="immersive-shell panel">
      <div class="immersive-toolbar">
        <div class="immersive-toolbar__meta">
          <div class="immersive-toolbar__title-row">
            <strong>{{ selectedDashboard.title }}</strong>
            <div v-if="selectedDashboard.tags?.length" class="dashboard-tags dashboard-tags--inline immersive-toolbar__tags">
              <span v-for="tag in selectedDashboard.tags" :key="`immersive-${selectedDashboard.key}-${tag}`" class="dashboard-chip">{{ tag }}</span>
            </div>
          </div>
          <span>{{ immersiveFolderLabel }}</span>
        </div>
        <span class="immersive-toolbar__hint">注意：看板首次加载会比较慢</span>
        <div class="immersive-toolbar__actions">
          <el-button size="small" v-if="canViewTracing" type="success" plain @click="openTraceFromDashboard(selectedDashboard)">查链路</el-button>
          <el-button size="small" v-if="canQueryLogs" type="warning" plain @click="openLogsFromDashboard(selectedDashboard)">查日志</el-button>
          <el-button size="small" @click="openExternal(selectedDashboardUrl)">全屏打开</el-button>
          <el-button size="small" type="primary" @click="closeFullscreen">退出看板</el-button>
        </div>
      </div>
      <div class="immersive-stage">
        <iframe
          ref="immersiveFrameRef"
          class="immersive-frame"
          :src="selectedDashboardUrl"
          :style="{ height: `${immersiveFrameHeight}px` }"
          :title="`${selectedDashboard.title}-immersive`"
          @load="handleGrafanaFrameLoad"
        />
      </div>
    </section>

    <template v-else>
      <section class="hero panel">
        <div class="hero-copy">
          <div class="hero-title-row">
            <span class="hero-icon">
              <el-icon><Histogram /></el-icon>
            </span>
            <h2>仪表盘</h2>
            <p class="page-inline-desc">{{ pageDescription }}</p>
          </div>
        </div>
        <div class="hero-actions">
          <el-button size="small" @click="loadOverview" :loading="loading">
            <el-icon><RefreshRight /></el-icon>
            刷新
          </el-button>
        </div>
      </section>

      <ObservabilityRouteTabs group="boards" />

      <section class="panel">
        <div class="section-head section-head--list">
          <div class="section-title-block">
            <div class="section-title-main">
              <h3>看板列表</h3>
            </div>
          </div>
          <div class="list-head-actions">
            <el-button size="small" plain @click="collapseAllFolders">全部折叠</el-button>
            <el-button v-if="canManageGrafana" size="small" type="primary" plain @click="openFolderDialog()">新增目录</el-button>
            <el-button size="small" plain @click="embedHelpVisible = true">
              <el-icon><QuestionFilled /></el-icon>
              Grafana 嵌入帮助
            </el-button>
          </div>
        </div>

        <div class="list-toolbar">
          <div class="list-toolbar__filters">
            <el-input size="small" v-model.trim="filters.keyword" placeholder="按看板名称或目录搜索" clearable />
            <el-select size="small" v-model="filters.tag" clearable placeholder="按标签筛选">
              <el-option v-for="item in tagOptions" :key="item" :label="item" :value="item" />
            </el-select>
          </div>
          <div class="list-toolbar__summary">
            <span>{{ folderCount }} 个目录</span>
            <span>{{ tagOptions.length }} 个标签</span>
            <el-button v-if="hasActiveFilters" size="small" link @click="resetFilters">清空筛选</el-button>
          </div>
        </div>

        <div class="dashboard-groups">
          <template v-for="node in visibleDashboardNodes" :key="node.type === 'folder' ? node.key : node.treeKey">
            <section v-if="node.type === 'folder'" class="dashboard-group" :style="{ '--tree-depth': node.depth }">
              <div
                class="group-head"
                :class="{ 'group-head--nested': node.depth > 0, 'is-selected': selectedFolderPath === node.fullPath }"
                @click="selectFolder(node)"
              >
                <div class="group-head__main">
                  <button class="group-head__toggle" type="button" @click.stop="toggleFolder(node.key)">
                    <el-icon><ArrowDown v-if="isFolderExpanded(node.key)" /><ArrowRight v-else /></el-icon>
                  </button>
                  <span class="group-head__folder-icon">
                    <el-icon><FolderOpened v-if="isFolderExpanded(node.key)" /><Folder v-else /></el-icon>
                  </span>
                  <div class="group-head__meta">
                    <strong>{{ node.label }}</strong>
                    <span v-if="node.hint">{{ node.hint }}</span>
                  </div>
                </div>
                <div class="group-head__stats">
                  <span class="group-head__count">{{ node.itemCount }} 个看板</span>
                  <div v-if="canManageGrafana" class="group-head__actions">
                    <el-dropdown trigger="click" @command="(command) => handleFolderCommand(command, node)" @click.stop>
                      <el-button size="small" link class="row-more-btn row-more-btn--folder" @click.stop>
                        <el-icon><MoreFilled /></el-icon>
                      </el-button>
                      <template #dropdown>
                        <el-dropdown-menu>
                          <el-dropdown-item command="add-dashboard">
                            <span class="dropdown-item-label">
                              <el-icon><Plus /></el-icon>
                              <span>新增看板</span>
                            </span>
                          </el-dropdown-item>
                          <el-dropdown-item command="add-subfolder">
                            <span class="dropdown-item-label">
                              <el-icon><FolderAdd /></el-icon>
                              <span>新增子目录</span>
                            </span>
                          </el-dropdown-item>
                          <el-dropdown-item command="edit">
                            <span class="dropdown-item-label">
                              <el-icon><EditPen /></el-icon>
                              <span>编辑目录</span>
                            </span>
                          </el-dropdown-item>
                          <el-dropdown-item command="delete" divided>
                            <span class="dropdown-item-label dropdown-item-label--danger">
                              <el-icon><Delete /></el-icon>
                              <span>删除目录</span>
                            </span>
                          </el-dropdown-item>
                        </el-dropdown-menu>
                      </template>
                    </el-dropdown>
                  </div>
                </div>
              </div>
            </section>

            <article
              v-else
              class="dashboard-card dashboard-card--tree"
              :class="{ active: selectedDashboard?.key === node.key }"
              :style="{ '--tree-depth': node.depth }"
              @click="selectDashboard(node)"
            >
              <div class="dashboard-row">
                <div class="dashboard-row__meta">
                  <div class="dashboard-row__mainline">
                    <span class="dashboard-row__kind" aria-hidden="true">
                      <span class="dashboard-row__kind-grid">
                        <i></i>
                        <i></i>
                        <i></i>
                        <i></i>
                      </span>
                    </span>
                    <strong>{{ node.title }}</strong>
                    <div class="dashboard-tags dashboard-tags--inline">
                      <span v-for="tag in node.tags" :key="`${node.key}-${tag}`" class="dashboard-chip">{{ tag }}</span>
                    </div>
                  </div>
                </div>
                <div class="dashboard-row__aside">
                  <div class="dashboard-actions">
                    <el-button size="small" v-if="node.url" link type="primary" @click.stop="openFullscreen(node)">打开看板</el-button>
                    <el-dropdown
                      v-if="canManageGrafana"
                      trigger="click"
                      @command="(command) => handleDashboardCommand(command, node)"
                      @click.stop
                    >
                      <el-button size="small" link class="row-more-btn" @click.stop>
                        <el-icon><MoreFilled /></el-icon>
                      </el-button>
                      <template #dropdown>
                        <el-dropdown-menu>
                          <el-dropdown-item v-if="node.url" command="external">
                            <span class="dropdown-item-label">
                              <el-icon><Link /></el-icon>
                              <span>外部打开</span>
                            </span>
                          </el-dropdown-item>
                          <el-dropdown-item command="edit">
                            <span class="dropdown-item-label">
                              <el-icon><EditPen /></el-icon>
                              <span>编辑</span>
                            </span>
                          </el-dropdown-item>
                          <el-dropdown-item command="delete" divided>
                            <span class="dropdown-item-label dropdown-item-label--danger">
                              <el-icon><Delete /></el-icon>
                              <span>删除</span>
                            </span>
                          </el-dropdown-item>
                        </el-dropdown-menu>
                      </template>
                    </el-dropdown>
                    <el-button size="small" v-if="!node.url" link disabled>未配置 URL</el-button>
                  </div>
                </div>
              </div>
            </article>
          </template>
        </div>
      </section>
    </template>

    <el-dialog v-model="folderDialog.visible" :title="folderDialogTitle" width="420px" destroy-on-close>
      <div class="dialog-form">
        <div v-if="folderDialog.parentPath" class="dialog-field">
          <label>{{ folderDialog.mode === 'edit' ? '上级路径' : '上级目录' }}</label>
          <div class="dialog-field__content">{{ folderDialog.parentPath }}</div>
        </div>
        <div class="dialog-field">
          <label class="dialog-field-label">
            <span>目录名称</span>
            <small>用“/”划分层级</small>
          </label>
          <el-input v-model.trim="folderDialog.name" placeholder="例如：基础设施 / 应用服务 / 节点" />
        </div>
        <div class="dialog-field">
          <label>目录说明</label>
          <el-input v-model.trim="folderDialog.description" placeholder="显示在目录标题下方，可留空" />
        </div>
        <div class="dialog-field">
          <label>保存路径</label>
          <div class="config-folder-preview">
            <template v-if="folderDialogPreviewSegments.length">
              <span
                v-for="(segment, index) in folderDialogPreviewSegments"
                :key="`folder-preview-${index}-${segment}`"
                class="config-folder-level"
              >
                {{ segment }}
              </span>
            </template>
            <span v-else class="config-folder-preview__empty">请输入目录名称后生成目录路径</span>
          </div>
        </div>
        <div class="dialog-field dialog-field--inline">
          <label>默认折叠</label>
          <el-switch v-model="folderDialog.folder_collapsed" />
        </div>
      </div>
      <template #footer>
        <el-button @click="folderDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="configSaving" @click="submitFolderDialog">{{ folderDialog.mode === 'edit' ? '保存修改' : '保存目录' }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="embedHelpVisible" title="Grafana 嵌入帮助" width="720px" destroy-on-close>
      <div class="help-dialog">
        <section class="help-section">
          <h4>1. Grafana 侧前置配置</h4>
          <p>要让看板能在本页面 iframe 中打开，Grafana 侧至少要允许被嵌入。</p>
          <pre class="help-code">[security]
allow_embedding = true

[auth.anonymous]
enabled = true
org_role = Viewer</pre>
          <p class="help-note">如果不准备开启匿名访问，也可以保留登录鉴权，但当前用户必须已经能正常访问该 Grafana。</p>
        </section>

        <section class="help-section">
          <h4>2. 跨域与 Cookie 建议</h4>
          <p>如果 Grafana 和当前系统不是同域，常见问题是登录页循环、白屏或被浏览器拦截。</p>
          <ul class="help-list">
            <li>优先推荐把 Grafana 通过同域反向代理暴露，这样最稳定。</li>
            <li>如果必须跨域嵌入，建议使用 HTTPS，并检查 Cookie SameSite / Secure 配置。</li>
            <li>浏览器控制台如果提示 `X-Frame-Options`、`CSP frame-ancestors`、第三方 Cookie，被嵌入会失败。</li>
          </ul>
        </section>

        <section class="help-section">
          <h4>3. 在本系统里配置看板</h4>
          <ol class="help-list help-list--ordered">
            <li>先在 Grafana 中打开目标仪表盘，确认链接本身可直接访问。</li>
            <li>复制完整的仪表盘 URL。</li>
            <li>回到本页面，在对应目录下新增看板或编辑现有看板。</li>
            <li>把完整 URL 粘贴到“完整 Grafana URL”字段并保存。</li>
            <li>保存后点击“打开看板”，确认能在右侧主内容区正常展示。</li>
          </ol>
        </section>

        <section class="help-section">
          <h4>4. 常见排查</h4>
          <ul class="help-list">
            <li>打开后跳到登录页：通常是未登录、Cookie 跨域失效或匿名访问未开启。</li>
            <li>页面空白：先检查 Grafana 是否允许 iframe 嵌入。</li>
            <li>URL 能外部打开但页面内打不开：优先排查跨域策略和浏览器安全限制。</li>
          </ul>
        </section>
      </div>
      <template #footer>
        <el-button type="primary" @click="embedHelpVisible = false">我知道了</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="dashboardDrawer.visible" :title="dashboardDrawer.mode === 'edit' ? '编辑看板' : '新建看板'" size="560px" destroy-on-close>
      <div class="drawer-form">
        <div class="drawer-field">
          <label>看板名称</label>
          <el-input v-model.trim="dashboardDraft.title" placeholder="看板名称" />
        </div>
        <div class="drawer-field">
          <label>目录</label>
          <div class="config-folder-field">
            <el-autocomplete
              v-model.trim="dashboardDraft.folder"
              :fetch-suggestions="queryFolderSuggestions"
              placeholder="例如：基础设施/节点"
              clearable
            />
            <div class="config-folder-preview">
              <template v-if="splitFolderSegments(dashboardDraft.folder).length">
                <span
                  v-for="(segment, index) in splitFolderSegments(dashboardDraft.folder)"
                  :key="`dashboard-folder-${index}-${segment}`"
                  class="config-folder-level"
                >
                  {{ segment }}
                </span>
              </template>
              <span v-else class="config-folder-preview__empty">留空时按系统推荐目录归类</span>
            </div>
          </div>
        </div>
        <div class="drawer-field">
          <label>标签</label>
          <el-select
            v-model="dashboardDraft.tags"
            multiple
            filterable
            allow-create
            default-first-option
            collapse-tags
            collapse-tags-tooltip
            style="width: 100%"
          />
        </div>
        <div class="drawer-field">
          <label>完整 Grafana URL</label>
          <div class="config-url-field">
            <el-input
              v-model.trim="dashboardDraft.full_url"
              :class="{ 'is-invalid': Boolean(getDashboardUrlError(dashboardDraft.full_url)) }"
              placeholder="直接填写完整 Grafana 看板链接"
            />
            <span v-if="getDashboardUrlError(dashboardDraft.full_url)" class="config-url-error">
              {{ getDashboardUrlError(dashboardDraft.full_url) }}
            </span>
            <span v-else class="config-url-hint">建议粘贴可直接打开的完整仪表盘地址</span>
          </div>
        </div>
        <div class="drawer-field drawer-field--inline">
          <label>展示参数</label>
          <div class="drawer-inline-control">
            <el-switch v-model="dashboardDrawer.appendKioskParams" active-text="自动追加 kiosk=true&theme=light" inactive-text="不追加" />
            <span class="config-url-hint">用于嵌入展示时隐藏 Grafana 菜单并使用浅色主题。</span>
          </div>
        </div>
        <div class="drawer-field__hint">
          新建看板会直接写入当前目录；保存后会立刻同步到看板列表。
        </div>
      </div>
      <template #footer>
        <div class="drawer-footer">
          <el-button @click="dashboardDrawer.visible = false">取消</el-button>
          <el-button type="primary" :loading="configSaving" @click="submitDashboardDrawer">保存看板</el-button>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowDown, ArrowRight, Delete, EditPen, Folder, FolderAdd, FolderOpened, Histogram, Link, MoreFilled, Plus, QuestionFilled, RefreshRight } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getGrafanaConfig, getObservabilityOverview, resolveGrafanaToLogs, resolveGrafanaToTrace, updateGrafanaConfig } from '@/api/modules/ops'
import { useAuthStore } from '@/stores/auth'
import { openRouteInNewTab } from '@/utils/router'
import ObservabilityRouteTabs from '@/components/observability/ObservabilityRouteTabs.vue'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const loading = ref(false)
const configSaving = ref(false)
const overviewLoaded = ref(false)
const fullscreenVisible = ref(false)
const embedHelpVisible = ref(false)
const immersiveFrameRef = ref(null)
const immersiveFrameHeight = ref(fallbackGrafanaFrameHeight())
const overview = ref({ modules: {}, summary: {}, tips: [] })
const selectedKey = ref('')
const selectedFolderPath = ref('')
const folderStates = reactive({})
const filters = reactive({
  keyword: '',
  tag: '',
})
const grafanaConfig = reactive({
  url: '',
  default_path: '',
  folders: [],
  dashboards: [],
})
const folderDialog = reactive({
  visible: false,
  mode: 'create',
  editingPath: '',
  parentPath: '',
  name: '',
  description: '',
  folder_collapsed: false,
})
const dashboardDrawer = reactive({
  visible: false,
  mode: 'create',
  editingKey: '',
  appendKioskParams: true,
})
const dashboardDraft = reactive(createEmptyDashboard())
let grafanaFrameMeasureTimer = null
let grafanaFrameMeasureInterval = null
let grafanaFrameResizeObserver = null

const grafana = computed(() => overview.value.modules?.grafana || {})
const dashboards = computed(() => grafana.value.dashboards || [])
const tagOptions = computed(() => Array.from(new Set(dashboards.value.flatMap((item) => item.tags || []))))
const pageDescription = computed(() => {
  return canManageGrafana.value
    ? '按目录组织和维护多套 Grafana 看板，支持页面内直接打开查看'
    : '按目录浏览 Grafana 看板，并在页面内直接打开查看'
})

const filteredDashboards = computed(() => {
  const keyword = filters.keyword.toLowerCase()
  return dashboards.value.filter((item) => {
    const matchesKeyword = !keyword || `${item.title} ${item.folder || ''}`.toLowerCase().includes(keyword)
    const matchesTag = !filters.tag || (item.tags || []).includes(filters.tag)
    return matchesKeyword && matchesTag
  })
})

const hasActiveFilters = computed(() => Boolean(filters.keyword || filters.tag))
const folderDefinitions = computed(() => {
  const source = canManageGrafana.value ? grafanaConfig.folders : (grafana.value.folders || [])
  return Array.isArray(source)
    ? source.map((item, index) => normalizeFolder(item, index)).filter((item) => item.path)
    : []
})

function dashboardGroupMeta(item) {
  const text = `${item.key} ${item.title} ${(item.tags || []).join(' ')}`.toLowerCase()
  if (/(log|audit|loki|sls|elk)/.test(text)) {
    return { key: 'logs', label: '日志排障', hint: '面向日志回放、审计与错误定位' }
  }
  if (/(nginx|ingress|gateway|availability|latency)/.test(text)) {
    return { key: 'ingress', label: '入口与可用性', hint: '关注入口流量、延迟和 SLO' }
  }
  if (/(infra|node|cpu|memory|pod|disk)/.test(text)) {
    return { key: 'infra', label: '基础设施', hint: '覆盖主机、节点和资源使用情况' }
  }
  return { key: 'apm', label: '应用与链路', hint: '优先查看链路、吞吐和错误趋势' }
}

function splitFolderSegments(folder = '') {
  return String(folder)
    .split(/[\\/]+/)
    .map((part) => part.trim())
    .filter(Boolean)
}

function normalizeFolderPath(folder = '') {
  return splitFolderSegments(folder).join('/')
}

function collectFolderAncestors(folder = '') {
  const segments = splitFolderSegments(folder)
  return segments.map((_, index) => segments.slice(0, index + 1).join('/'))
}

function getFolderParentPath(folder = '') {
  const segments = splitFolderSegments(folder)
  return segments.slice(0, -1).join('/')
}

function getFolderLeafName(folder = '') {
  const segments = splitFolderSegments(folder)
  return segments[segments.length - 1] || ''
}

function remapFolderPath(path = '', sourcePath = '', targetPath = '') {
  const normalizedPath = normalizeFolderPath(path)
  const normalizedSource = normalizeFolderPath(sourcePath)
  const normalizedTarget = normalizeFolderPath(targetPath)
  if (!normalizedSource || !isSameOrChildFolder(normalizedPath, normalizedSource)) {
    return normalizedPath
  }
  const suffix = normalizedPath === normalizedSource ? '' : normalizedPath.slice(normalizedSource.length + 1)
  return normalizeFolderPath([normalizedTarget, suffix].filter(Boolean).join('/'))
}

function createEmptyDashboard(folder = '') {
  return {
    key: '',
    slug: '',
    title: '',
    description: '',
    folder: normalizeFolderPath(folder),
    folder_collapsed: false,
    path: '',
    full_url: '',
    tags: [],
    panel_count: 0,
  }
}

function resetDashboardDraft(item = {}) {
  const normalized = normalizeDashboard(item)
  dashboardDraft.key = normalized.key
  dashboardDraft.slug = normalized.slug
  dashboardDraft.title = normalized.title
  dashboardDraft.description = normalized.description
  dashboardDraft.folder = normalized.folder
  dashboardDraft.folder_collapsed = normalized.folder_collapsed
  dashboardDraft.path = normalized.path
  dashboardDraft.full_url = normalized.full_url
  dashboardDraft.tags = [...normalized.tags]
  dashboardDraft.panel_count = normalized.panel_count
}

function normalizeFolder(item = {}, index = 0) {
  const path = normalizeFolderPath(item.path || item.folder || '')
  return {
    key: path || `folder-${index + 1}`,
    path,
    description: String(item.description || '').trim(),
    folder_collapsed: Boolean(item.folder_collapsed),
  }
}

function dashboardFolderMeta(item) {
  const configuredFolder = normalizeFolderPath(item.folder || '')
  if (configuredFolder) {
    return {
      key: `folder:${configuredFolder}`,
      label: configuredFolder,
      hint: '',
      collapsedByDefault: Boolean(item.folder_collapsed),
    }
  }
  return {
    ...dashboardGroupMeta(item),
    collapsedByDefault: false,
  }
}

function dashboardFolderInfo(item) {
  const meta = dashboardFolderMeta(item)
  const configuredFolder = normalizeFolderPath(item.folder || '')
  const segments = configuredFolder ? splitFolderSegments(configuredFolder) : [meta.label]
  const fullPath = segments.join('/')
  return {
    ...meta,
    segments,
    fullPath,
  }
}

const dashboardTree = computed(() => {
  const roots = []
  const folders = new Map()

  function ensureFolderPath(path, options = {}) {
    const segments = splitFolderSegments(path)
    const lineage = []
    let currentChildren = roots
    const pathParts = []

    segments.forEach((segment, index) => {
      pathParts.push(segment)
      const fullPath = pathParts.join('/')
      const folderKey = `folder:${fullPath}`
      const isLeaf = index === segments.length - 1
      let node = folders.get(folderKey)
      if (!node) {
        node = {
          type: 'folder',
          key: folderKey,
          fullPath,
          label: segment,
          depth: index,
          collapsedByDefault: false,
          explicit: false,
          hint: `${segment} 目录`,
          itemCount: 0,
          configuredCount: 0,
          children: [],
        }
        folders.set(folderKey, node)
        currentChildren.push(node)
      }
      if (options.explicit) {
        node.explicit = true
      }
      if (isLeaf) {
        if ('hint' in options) {
          node.hint = options.hint
        }
        if (typeof options.collapsedByDefault === 'boolean' && !node.explicit) {
          node.collapsedByDefault = options.collapsedByDefault
        }
      }
      lineage.push(node)
      currentChildren = node.children
    })

    return lineage
  }

  folderDefinitions.value.forEach((item) => {
    ensureFolderPath(item.path, {
      explicit: true,
      collapsedByDefault: item.folder_collapsed,
      hint: item.description || '',
    })
  })

  filteredDashboards.value.forEach((item) => {
    const info = dashboardFolderInfo(item)
    const lineage = ensureFolderPath(info.fullPath, {
      explicit: Boolean(normalizeFolderPath(item.folder)),
      collapsedByDefault: info.collapsedByDefault,
      hint: info.hint,
    })

    lineage.forEach((folder) => {
      folder.itemCount += 1
      if (item.url) {
        folder.configuredCount += 1
      }
    })

    lineage[lineage.length - 1].children.push({
      ...item,
      type: 'dashboard',
      treeKey: `dashboard:${item.key}`,
      depth: info.segments.length,
      folderLabel: info.fullPath,
    })
  })

  function sortTree(nodes) {
    nodes.sort((left, right) => {
      if (left.type !== right.type) {
        return left.type === 'folder' ? -1 : 1
      }
      const leftLabel = left.type === 'folder' ? left.label : left.title
      const rightLabel = right.type === 'folder' ? right.label : right.title
      return String(leftLabel).localeCompare(String(rightLabel), 'zh-CN')
    })
    nodes.forEach((node) => {
      if (node.type === 'folder') {
        sortTree(node.children)
      }
    })
  }

  sortTree(roots)

  return {
    roots,
    folderCount: folders.size,
    folderKeys: [...folders.values()].map((folder) => ({
      key: folder.key,
      collapsedByDefault: folder.collapsedByDefault,
    })),
    folderMap: new Map([...folders.values()].map((folder) => [folder.fullPath, folder])),
  }
})

const visibleDashboardNodes = computed(() => {
  const result = []

  function walk(nodes) {
    nodes.forEach((node) => {
      result.push(node)
      if (node.type === 'folder' && isFolderExpanded(node.key)) {
        walk(node.children)
      }
    })
  }

  walk(dashboardTree.value.roots)
  return result
})

const folderCount = computed(() => dashboardTree.value.folderCount)
const configuredDashboardCount = computed(() => dashboards.value.filter((item) => item.url).length)
const knownFolderOptions = computed(() => {
  const folders = new Set()
  folderDefinitions.value.forEach((item) => {
    collectFolderAncestors(item.path).forEach((path) => folders.add(path))
  })
  dashboards.value.forEach((item) => {
    collectFolderAncestors(item.folder || '').forEach((path) => folders.add(path))
  })
  return [...folders].sort((a, b) => a.localeCompare(b, 'zh-CN'))
})

const selectedDashboard = computed(() => findDashboardByIdentity(selectedKey.value) || filteredDashboards.value[0] || null)
const selectedDashboardUrl = computed(() => appendGrafanaContext(selectedDashboard.value?.url || ''))
const immersiveFolderLabel = computed(() => {
  const folderPath = normalizeFolderPath(selectedDashboard.value?.folder || '')
  return folderPath ? `目录：${folderPath}` : '目录：未分类'
})

const folderDialogPreviewPath = computed(() => {
  const parent = normalizeFolderPath(folderDialog.parentPath)
  const name = normalizeFolderPath(folderDialog.name)
  return normalizeFolderPath([parent, name].filter(Boolean).join('/'))
})

const folderDialogPreviewSegments = computed(() => splitFolderSegments(folderDialogPreviewPath.value))
const folderDialogTitle = computed(() => {
  if (folderDialog.mode === 'edit') {
    return '编辑目录'
  }
  return folderDialog.parentPath ? '新增子目录' : '新增目录'
})

const canViewTracing = computed(() => authStore.hasPermission('ops.trace.view'))
const canQueryLogs = computed(() => authStore.hasPermission('ops.log.query'))
const canViewAlerts = computed(() => authStore.hasPermission('ops.alert.view'))
const canManageGrafana = computed(() => authStore.hasPermission('ops.grafana.manage'))

function normalizeDashboard(item = {}, index = null) {
  const fallbackKey = index === null ? '' : `dashboard-${index + 1}`
  return {
    key: String(item.key || item.slug || fallbackKey).trim(),
    slug: String(item.slug || item.key || fallbackKey).trim(),
    title: String(item.title || '').trim(),
    description: String(item.description || '').trim(),
    folder: normalizeFolderPath(item.folder || ''),
    folder_collapsed: Boolean(item.folder_collapsed),
    path: String(item.path || '').trim(),
    full_url: String(item.full_url || item.url || '').trim(),
    tags: Array.isArray(item.tags) ? [...item.tags] : [],
    panel_count: Number(item.panel_count || 0),
  }
}

function normalizeDashboardIdentity(value = '') {
  return String(value || '').trim().toLowerCase().replace(/[^a-z0-9\u4e00-\u9fa5]+/g, '')
}

function findDashboardByIdentity(value = '') {
  const normalized = normalizeDashboardIdentity(value)
  if (!normalized) return null
  return dashboards.value.find((item) => {
    return [item.key, item.slug, item.title].some((candidate) => normalizeDashboardIdentity(candidate) === normalized)
  }) || null
}

function buildDashboardFullUrl(item = {}, baseUrl = '') {
  const fullUrl = String(item.full_url || item.url || '').trim()
  if (fullUrl) {
    return normalizeGrafanaUrl(fullUrl)
  }
  const path = String(item.path || '').trim()
  const normalizedBase = String(baseUrl || '').trim().replace(/\/+$/, '')
  if (!path || !normalizedBase) {
    return ''
  }
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  return normalizeGrafanaUrl(`${normalizedBase}${normalizedPath}`)
}

function getDashboardUrlError(url = '') {
  const value = String(url || '').trim()
  if (!value) {
    return ''
  }
  try {
    const parsed = new URL(value)
    if (!/^https?:$/.test(parsed.protocol)) {
      return 'URL 需以 http:// 或 https:// 开头'
    }
    return ''
  } catch {
    return '请输入可直接访问的完整 URL'
  }
}

function normalizeGrafanaUrl(url = '') {
  const value = String(url || '').trim()
  if (!value) return ''
  try {
    const parsed = new URL(value, window.location.origin)
    const current = new URL(window.location.origin)
    const path = parsed.pathname || '/'
    const looksLikeGrafanaPath = path === '/' || ['/d/', '/dashboard/', '/explore', '/public/', '/api/'].some((prefix) => path.startsWith(prefix))
    const alreadyProxied = parsed.origin === current.origin && path.startsWith('/grafana/')
    const shouldProxy = current.protocol === 'https:' && looksLikeGrafanaPath && !alreadyProxied
      && (parsed.protocol === 'http:' || parsed.origin !== current.origin || value.startsWith('/'))
    if (!shouldProxy) {
      return parsed.toString()
    }
    const proxiedPath = path.startsWith('/grafana/') ? path : `/grafana${path.startsWith('/') ? path : `/${path}`}`
    const proxied = new URL(proxiedPath, current.origin)
    proxied.search = parsed.search
    proxied.hash = parsed.hash
    return proxied.toString()
  } catch {
    return value
  }
}

function appendGrafanaDisplayParams(url = '') {
  const value = normalizeGrafanaUrl(url)
  if (!value) return ''
  try {
    const parsed = new URL(value)
    parsed.searchParams.set('kiosk', 'true')
    parsed.searchParams.set('theme', 'light')
    return parsed.toString()
  } catch {
    const base = value.replace(/[?&](?:kiosk|theme)=[^&#]*/g, '').replace(/[?&]$/, '')
    const separator = base.includes('?') ? '&' : '?'
    return `${base}${separator}kiosk=true&theme=light`
  }
}

function queryFolderSuggestions(queryString, callback) {
  const keyword = String(queryString || '').trim().toLowerCase()
  const matches = knownFolderOptions.value
    .filter((item) => !keyword || item.toLowerCase().includes(keyword))
    .slice(0, 12)
    .map((item) => ({ value: item }))
  callback(matches)
}

function applyGrafanaConfig(data = {}) {
  grafanaConfig.url = String(data.url || '').trim()
  grafanaConfig.default_path = String(data.default_path || '').trim()
  grafanaConfig.folders = Array.isArray(data.folders)
    ? data.folders.map((item, index) => normalizeFolder(item, index)).filter((item) => item.path)
    : []
  grafanaConfig.dashboards = Array.isArray(data.dashboards)
    ? data.dashboards.map((item, index) => ({
        ...normalizeDashboard(item, index),
        full_url: buildDashboardFullUrl(item, data.url),
      }))
    : []
}

async function loadOverview() {
  loading.value = true
  try {
    const [overviewData, configData] = await Promise.all([
      getObservabilityOverview(),
      canManageGrafana.value ? getGrafanaConfig() : Promise.resolve(null),
    ])
    overview.value = overviewData
    if (configData) {
      applyGrafanaConfig(configData)
    }
  } finally {
    loading.value = false
    overviewLoaded.value = true
  }
}

function resetFilters() {
  filters.keyword = ''
  filters.tag = ''
}

function buildDashboardKey(item, existingKeys, editingKey = '') {
  const raw = String(item.key || item.slug || item.title || '').trim().toLowerCase()
  const slugSeed = raw
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  const base = slugSeed || `dashboard-${Date.now()}`
  let candidate = editingKey || base
  if (!candidate) {
    candidate = base
  }
  if (candidate === editingKey) {
    return candidate
  }
  let suffix = 2
  while (existingKeys.has(candidate)) {
    candidate = `${base}-${suffix}`
    suffix += 1
  }
  return candidate
}

function mergeFolderConfigs(foldersSource = [], dashboardsSource = []) {
  const folderMap = new Map()

  foldersSource
    .map((item, index) => normalizeFolder(item, index))
    .filter((item) => item.path)
    .forEach((item) => {
      folderMap.set(item.path, item)
    })

  dashboardsSource.forEach((item) => {
    const ancestors = collectFolderAncestors(item.folder)
    ancestors.forEach((path) => {
      if (!folderMap.has(path)) {
        folderMap.set(path, {
          key: path,
          path,
          description: '',
          folder_collapsed: false,
        })
      }
    })
  })

  return [...folderMap.values()].sort((a, b) => a.path.localeCompare(b.path, 'zh-CN'))
}

function buildGrafanaPayload({ dashboardsSource = grafanaConfig.dashboards, foldersSource = grafanaConfig.folders } = {}) {
  const normalizedDashboards = dashboardsSource.map((item, index) => {
    const normalized = normalizeDashboard(item, index)
    return {
      key: normalized.key || `dashboard-${index + 1}`,
      slug: normalized.slug || normalized.key || `dashboard-${index + 1}`,
      title: normalized.title,
      description: '',
      folder: normalizeFolderPath(normalized.folder),
      folder_collapsed: false,
      path: String(normalized.path || '').trim(),
      full_url: String(normalized.full_url || '').trim(),
      panel_count: Number(normalized.panel_count || 0),
      tags: Array.isArray(normalized.tags) ? normalized.tags.map((tag) => String(tag).trim()).filter(Boolean) : [],
    }
  })

  const pendingRows = normalizedDashboards
    .map((item, index) => ({ item, index }))
    .filter(({ item }) => item.title || item.folder || item.path || item.full_url || (item.tags || []).length)

  const missingTitleRow = pendingRows.find(({ item }) => !item.title)
  if (missingTitleRow) {
    throw new Error(`第 ${missingTitleRow.index + 1} 行缺少看板名称`)
  }

  const missingUrlRow = pendingRows.find(({ item }) => !item.full_url && !item.path)
  if (missingUrlRow) {
    throw new Error(`第 ${missingUrlRow.index + 1} 行缺少完整 Grafana URL 或 Grafana 路径`)
  }

  const invalidUrlRow = pendingRows.find(({ item }) => item.full_url && getDashboardUrlError(item.full_url))
  if (invalidUrlRow) {
    throw new Error(`第 ${invalidUrlRow.index + 1} 行 Grafana URL 格式无效`)
  }

  const mergedFolders = mergeFolderConfigs(foldersSource, normalizedDashboards)

  return {
    enabled: true,
    url: grafanaConfig.url,
    default_path: grafanaConfig.default_path,
    folders: mergedFolders.map((item) => ({
      path: item.path,
      description: String(item.description || '').trim(),
      folder_collapsed: Boolean(item.folder_collapsed),
    })),
    dashboards: normalizedDashboards.filter((item) => item.title && (item.full_url || item.path)),
  }
}

async function persistGrafanaConfig(nextState, successMessage) {
  configSaving.value = true
  try {
    const payload = buildGrafanaPayload(nextState)
    await updateGrafanaConfig(payload)
    ElMessage.success(successMessage)
    await loadOverview()
  } catch (error) {
    ElMessage.error(error?.message || 'Grafana 配置保存失败')
    throw error
  } finally {
    configSaving.value = false
  }
}

function openFolderDialog(parentNode = null) {
  folderDialog.mode = 'create'
  folderDialog.editingPath = ''
  folderDialog.parentPath = parentNode?.fullPath || ''
  folderDialog.name = ''
  folderDialog.description = ''
  folderDialog.folder_collapsed = Boolean(parentNode?.collapsedByDefault)
  folderDialog.visible = true
}

function openFolderEditDialog(node) {
  const currentPath = normalizeFolderPath(node?.fullPath || '')
  const currentConfig = grafanaConfig.folders.find((item) => normalizeFolderPath(item.path) === currentPath)
  folderDialog.mode = 'edit'
  folderDialog.editingPath = currentPath
  folderDialog.parentPath = getFolderParentPath(currentPath)
  folderDialog.name = getFolderLeafName(currentPath)
  folderDialog.description = String(currentConfig?.description || '').trim()
  folderDialog.folder_collapsed = currentConfig ? Boolean(currentConfig.folder_collapsed) : Boolean(node?.collapsedByDefault)
  folderDialog.visible = true
}

async function submitFolderDialog() {
  const nextPath = folderDialogPreviewPath.value
  if (!nextPath) {
    ElMessage.error('请先填写目录名称')
    return
  }
  const isEditing = folderDialog.mode === 'edit'
  const editingPath = normalizeFolderPath(folderDialog.editingPath)
  let nextFolders = []
  let nextDashboards = grafanaConfig.dashboards

  if (!isEditing) {
    if (dashboardTree.value.folderMap.has(nextPath)) {
      ElMessage.error('该目录已存在，请更换目录名称')
      return
    }
    nextFolders = [
      ...grafanaConfig.folders,
      {
        path: nextPath,
        description: String(folderDialog.description || '').trim(),
        folder_collapsed: Boolean(folderDialog.folder_collapsed),
      },
    ]
  } else {
    if (!editingPath) {
      ElMessage.error('目录路径无效，请刷新后重试')
      return
    }
    if (nextPath !== editingPath && isSameOrChildFolder(nextPath, editingPath)) {
      ElMessage.error('目录不能移动到自己的子目录下')
      return
    }

    const folderSeed = grafanaConfig.folders.some((item) => normalizeFolderPath(item.path) === editingPath)
      ? grafanaConfig.folders
      : [
          ...grafanaConfig.folders,
          {
            path: editingPath,
            description: '',
            folder_collapsed: false,
          },
        ]

    nextFolders = folderSeed.map((item) => {
      const currentPath = normalizeFolderPath(item.path)
      if (!isSameOrChildFolder(currentPath, editingPath)) {
        return normalizeFolder(item)
      }
      const remappedPath = remapFolderPath(currentPath, editingPath, nextPath)
      return {
        ...normalizeFolder(item),
        path: remappedPath,
        description: remappedPath === nextPath ? String(folderDialog.description || '').trim() : String(item.description || '').trim(),
        folder_collapsed: remappedPath === nextPath ? Boolean(folderDialog.folder_collapsed) : Boolean(item.folder_collapsed),
      }
    })

    const seenFolderPaths = new Set()
    for (const item of nextFolders) {
      const path = normalizeFolderPath(item.path)
      if (!path) {
        continue
      }
      if (seenFolderPaths.has(path)) {
        ElMessage.error('目录路径与现有目录冲突，请调整后重试')
        return
      }
      seenFolderPaths.add(path)
    }

    nextDashboards = grafanaConfig.dashboards.map((item) => {
      const currentFolderPath = dashboardFolderInfo(item).fullPath
      if (!currentFolderPath || !isSameOrChildFolder(currentFolderPath, editingPath)) {
        return item
      }
      return {
        ...normalizeDashboard(item),
        folder: remapFolderPath(currentFolderPath, editingPath, nextPath),
      }
    })
  }

  try {
    await persistGrafanaConfig(
      {
        foldersSource: nextFolders,
        dashboardsSource: nextDashboards,
      },
      isEditing ? '目录已更新' : '目录已保存',
    )
    folderStates[`folder:${nextPath}`] = true
    if (isEditing && selectedFolderPath.value && isSameOrChildFolder(selectedFolderPath.value, editingPath)) {
      selectedFolderPath.value = remapFolderPath(selectedFolderPath.value, editingPath, nextPath)
    } else {
      selectedFolderPath.value = nextPath
    }
    expandFolderAncestors(nextPath)
    folderDialog.visible = false
  } catch {
    // validation message already shown
  }
}

function openDashboardDrawer(source = null) {
  const defaultFolder = normalizeFolderPath(source?.folder || selectedFolderPath.value || '')
  dashboardDrawer.mode = source?.type === 'dashboard' || source?.full_url ? 'edit' : 'create'
  dashboardDrawer.editingKey = dashboardDrawer.mode === 'edit' ? String(source.key || '').trim() : ''

  if (dashboardDrawer.mode === 'edit') {
    resetDashboardDraft(source)
  } else {
    resetDashboardDraft(createEmptyDashboard(defaultFolder))
  }
  dashboardDrawer.appendKioskParams = true
  dashboardDrawer.visible = true
}

async function submitDashboardDrawer() {
  const title = String(dashboardDraft.title || '').trim()
  const rawFullUrl = String(dashboardDraft.full_url || '').trim()
  const fullUrl = dashboardDrawer.appendKioskParams ? appendGrafanaDisplayParams(rawFullUrl) : rawFullUrl
  const folder = normalizeFolderPath(dashboardDraft.folder || '')
  const urlError = getDashboardUrlError(rawFullUrl)

  if (!title) {
    ElMessage.error('请填写看板名称')
    return
  }
  if (!rawFullUrl) {
    ElMessage.error('请填写完整 Grafana URL')
    return
  }
  if (urlError) {
    ElMessage.error(urlError)
    return
  }

  const existingKeys = new Set(grafanaConfig.dashboards.map((item) => item.key).filter(Boolean))
  if (dashboardDrawer.editingKey) {
    existingKeys.delete(dashboardDrawer.editingKey)
  }
  const resolvedKey = buildDashboardKey(
    {
      ...dashboardDraft,
      key: dashboardDrawer.editingKey || dashboardDraft.key,
      slug: dashboardDrawer.editingKey || dashboardDraft.slug,
      title,
    },
    existingKeys,
    dashboardDrawer.editingKey,
  )

  const nextDashboard = {
    ...normalizeDashboard(dashboardDraft),
    key: resolvedKey,
    slug: resolvedKey,
    title,
    folder,
    folder_collapsed: false,
    full_url: fullUrl,
  }

  const nextDashboards = [...grafanaConfig.dashboards]
  const currentIndex = nextDashboards.findIndex((item) => item.key === dashboardDrawer.editingKey)
  if (currentIndex >= 0) {
    nextDashboards.splice(currentIndex, 1, nextDashboard)
  } else {
    nextDashboards.push(nextDashboard)
  }

  try {
    await persistGrafanaConfig(
      {
        foldersSource: grafanaConfig.folders,
        dashboardsSource: nextDashboards,
      },
      dashboardDrawer.mode === 'edit' ? '看板已更新' : '看板已创建',
    )
    selectedKey.value = resolvedKey
    selectedFolderPath.value = folder || selectedFolderPath.value
    dashboardDrawer.visible = false
  } catch {
    // validation message already shown
  }
}

async function deleteDashboard(node) {
  try {
    await ElMessageBox.confirm(`确认删除看板“${node.title}”吗？`, '删除看板', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }

  const nextDashboards = grafanaConfig.dashboards.filter((item) => item.key !== node.key)
  try {
    await persistGrafanaConfig(
      {
        foldersSource: grafanaConfig.folders,
        dashboardsSource: nextDashboards,
      },
      '看板已删除',
    )
    if (selectedKey.value === node.key) {
      selectedKey.value = ''
    }
  } catch {
    // validation message already shown
  }
}

function isSameOrChildFolder(path, target) {
  return path === target || path.startsWith(`${target}/`)
}

async function deleteFolderNode(node) {
  try {
    await ElMessageBox.confirm(`确认删除目录“${node.fullPath}”以及其下看板吗？`, '删除目录', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }

  const nextFolders = grafanaConfig.folders.filter((item) => !isSameOrChildFolder(normalizeFolderPath(item.path), node.fullPath))
  const nextDashboards = grafanaConfig.dashboards.filter((item) => {
    return !isSameOrChildFolder(dashboardFolderInfo(item).fullPath, node.fullPath)
  })

  try {
    await persistGrafanaConfig(
      {
        foldersSource: nextFolders,
        dashboardsSource: nextDashboards,
      },
      '目录已删除',
    )
    if (selectedFolderPath.value === node.fullPath || isSameOrChildFolder(selectedFolderPath.value, node.fullPath)) {
      selectedFolderPath.value = ''
    }
  } catch {
    // validation message already shown
  }
}

function handleFolderCommand(command, node) {
  if (command === 'add-dashboard') {
    openDashboardDrawer({ folder: node.fullPath })
    return
  }
  if (command === 'add-subfolder') {
    openFolderDialog(node)
    return
  }
  if (command === 'edit') {
    openFolderEditDialog(node)
    return
  }
  if (command === 'delete') {
    deleteFolderNode(node)
  }
}

function handleDashboardCommand(command, node) {
  if (command === 'external') {
    openExternal(node?.url)
    return
  }
  if (command === 'edit') {
    openDashboardDrawer(node)
    return
  }
  if (command === 'delete') {
    deleteDashboard(node)
  }
}

function expandFolderAncestors(path = '', options = {}) {
  const includeSelf = options.includeSelf !== false
  const paths = collectFolderAncestors(path)
  const targets = includeSelf ? paths : paths.slice(0, -1)
  targets.forEach((folderPath) => {
    folderStates[`folder:${folderPath}`] = true
  })
}

function selectFolder(node) {
  const wasSelected = selectedFolderPath.value === node.fullPath
  const wasExpanded = isFolderExpanded(node.key)
  selectedFolderPath.value = node.fullPath
  expandFolderAncestors(node.fullPath, { includeSelf: false })
  if (!wasSelected) {
    folderStates[node.key] = true
    return
  }
  folderStates[node.key] = !wasExpanded
}

function selectDashboard(item) {
  if (!item?.key) {
    return
  }
  selectedKey.value = item.key
  selectedFolderPath.value = item.folderLabel || selectedFolderPath.value
}

function syncFromRoute() {
  filters.keyword = typeof route.query.keyword === 'string' ? route.query.keyword.trim() : ''
  filters.tag = typeof route.query.tag === 'string' ? route.query.tag.trim() : ''
  selectedKey.value = typeof route.query.dashboard === 'string' ? route.query.dashboard.trim() : ''
  selectedFolderPath.value = typeof route.query.folder === 'string' ? normalizeFolderPath(route.query.folder) : ''
  fullscreenVisible.value = String(route.query.fullscreen || '') === '1'
}

function syncRouteQuery() {
  const preservedQuery = Object.fromEntries(
    Object.entries(route.query).filter(([key]) => !['dashboard', 'folder', 'keyword', 'tag', 'fullscreen'].includes(key))
  )
  const currentQuery = {
    ...preservedQuery,
    dashboard: selectedKey.value || undefined,
    folder: selectedFolderPath.value || undefined,
    keyword: filters.keyword || undefined,
    tag: filters.tag || undefined,
    fullscreen: fullscreenVisible.value ? '1' : undefined,
  }
  const nextFingerprint = JSON.stringify(currentQuery)
  const currentFingerprint = JSON.stringify(route.query)
  if (nextFingerprint === currentFingerprint) {
    return
  }
  router.replace({
    path: route.path,
    query: currentQuery,
  })
}

function openExternal(url) {
  const normalizedUrl = normalizeGrafanaUrl(url)
  if (normalizedUrl) {
    window.open(normalizedUrl, '_blank', 'noopener,noreferrer')
  }
}

function appendGrafanaParams(url, rawParams = {}) {
  const value = String(url || '').trim()
  if (!value) return ''
  const params = new URLSearchParams()
  Object.entries(rawParams).forEach(([key, raw]) => {
    const values = Array.isArray(raw) ? raw : [raw]
    values.forEach((item) => {
      if (item !== undefined && item !== null && String(item).trim()) {
        params.append(key, String(item).trim())
      }
    })
  })
  const keys = [...new Set(params.keys())]
  try {
    const parsed = /^https?:\/\//i.test(value) ? new URL(value) : new URL(value, window.location.origin)
    keys.forEach((key) => parsed.searchParams.delete(key))
    params.forEach((item, key) => {
      parsed.searchParams.append(key, item)
    })
    return /^https?:\/\//i.test(value)
      ? parsed.toString()
      : `${parsed.pathname}${parsed.search}${parsed.hash}`
  } catch {
    const separator = value.includes('?') ? '&' : '?'
    return `${value}${separator}${params.toString()}`
  }
}

function groupSearchParams(params) {
  const grouped = {}
  params.forEach((value, key) => {
    if (!grouped[key]) grouped[key] = []
    grouped[key].push(value)
  })
  return grouped
}

function appendGrafanaContext(url) {
  const normalizedUrl = normalizeGrafanaUrl(url)
  const params = new URLSearchParams()
  params.set('kiosk', 'true')
  params.set('theme', 'light')
  Object.entries(route.query).forEach(([key, raw]) => {
    if (['dashboard', 'folder', 'keyword', 'tag', 'fullscreen'].includes(key)) return
    if (!['traceId', 'service', 'workload', 'namespace', 'provider', 'source', 'from', 'to'].includes(key) && !key.startsWith('var-')) return
    const values = Array.isArray(raw) ? raw : [raw]
    values.forEach((item) => {
      if (item !== undefined && item !== null && String(item).trim()) {
        params.append(key, String(item))
      }
    })
  })
  return appendGrafanaParams(normalizedUrl, groupSearchParams(params))
}

function applyDashboardContextValue(context, key, value) {
  if (value === undefined || value === null) return
  const normalizedValue = String(value).trim()
  if (!normalizedValue) return
  if (key.startsWith('var-') || ['traceId', 'trace_id', 'service', 'workload', 'namespace', 'from', 'to'].includes(key)) {
    context[key] = normalizedValue
  }
}

function dashboardContextFromRoute() {
  const context = {}
  Object.entries(route.query).forEach(([key, raw]) => {
    const values = Array.isArray(raw) ? raw : [raw]
    values.forEach((item) => applyDashboardContextValue(context, key, item))
  })
  return context
}

function dashboardContextFromUrl(url = '') {
  const context = {}
  const value = String(url || '').trim()
  if (!value) return context
  try {
    const parsed = new URL(value, window.location.origin)
    parsed.searchParams.forEach((item, key) => {
      applyDashboardContextValue(context, key, item)
    })
  } catch {
    return context
  }
  return context
}

function dashboardJumpPayload(node) {
  const url = appendGrafanaContext(node?.url || node?.full_url || selectedDashboard.value?.url || selectedDashboard.value?.full_url || '')
  const context = {
    ...dashboardContextFromUrl(url),
    ...dashboardContextFromRoute(),
  }
  return {
    dashboard_key: node?.key || selectedDashboard.value?.key || '',
    query: context,
    ...context,
  }
}

function firstResolvedTag(resolved, keys = []) {
  const tags = resolved?.tags || {}
  for (const key of keys) {
    const value = tags[key]
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  return ''
}

function jumpErrorMessage(error, fallback) {
  const detail = String(error?.response?.data?.detail || error?.response?.data?.error || '').trim()
  const statusCode = Number(error?.response?.status || 0)
  if (
    statusCode === 404
    || detail.includes('Grafana 看板到日志关联')
    || detail.includes('Grafana 看板到链路关联')
  ) {
    return '当前看板未配置关联跳转'
  }
  return detail || error?.message || fallback
}

async function openTraceFromDashboard(node) {
  try {
    const context = dashboardJumpPayload(node)
    const resolved = await resolveGrafanaToTrace(context, { skipErrorMessage: true })
    const service = String(resolved.service || firstResolvedTag(resolved, ['service.name', 'service', 'workload']) || context['var-workload'] || context.workload || context['var-service'] || context.service || '').trim()
    if (!service) {
      ElMessage.warning('当前看板缺少 workload / service，上下文不足，无法跳转链路。')
      return
    }
    openRouteInNewTab(router, {
      path: '/observability/tracing',
      query: {
        service: service || undefined,
        keyword: service || undefined,
        provider: resolved.tracing_datasource?.provider || undefined,
        datasourceId: resolved.tracing_datasource?.id ? String(resolved.tracing_datasource.id) : undefined,
        window: resolved.window_minutes ? String(resolved.window_minutes) : undefined,
        from: context.from || undefined,
        to: context.to || undefined,
      },
    })
  } catch (error) {
    const statusCode = Number(error?.response?.status || 0)
    const detail = String(error?.response?.data?.detail || error?.response?.data?.error || '').trim()
    if (statusCode === 404 || detail.includes('Grafana 看板到链路关联')) {
      ElMessage.closeAll()
      ElMessage.warning('当前看板未配置关联跳转')
      return
    }
    ElMessage.error(jumpErrorMessage(error, '看板跳链路失败，请检查数据源关联配置。'))
  }
}

async function openLogsFromDashboard(node) {
  try {
    const context = dashboardJumpPayload(node)
    const resolved = await resolveGrafanaToLogs(context, { skipErrorMessage: true })
    const query = String(resolved.query || '').trim()
    if (!query) {
      ElMessage.warning('当前看板缺少可用于日志查询的上下文标签。')
      return
    }
    openRouteInNewTab(router, {
      path: '/logs/query',
      query: {
        service: firstResolvedTag(resolved, ['service.name', 'service', 'workload']) || context['var-workload'] || context.workload || context['var-service'] || context.service || undefined,
        logProvider: resolved.log_datasource?.provider || undefined,
        logDatasourceId: resolved.log_datasource?.id ? String(resolved.log_datasource.id) : undefined,
        lokiQuery: query,
        window: resolved.window_minutes ? String(resolved.window_minutes) : '60',
        from: context.from || undefined,
        to: context.to || undefined,
        autoRun: '1',
      },
    })
  } catch (error) {
    const statusCode = Number(error?.response?.status || 0)
    const detail = String(error?.response?.data?.detail || error?.response?.data?.error || '').trim()
    if (statusCode === 404 || detail.includes('Grafana 看板到日志关联')) {
      ElMessage.closeAll()
      ElMessage.warning('当前看板未配置关联跳转')
      return
    }
    ElMessage.error(jumpErrorMessage(error, '看板跳日志失败，请检查数据源关联配置。'))
  }
}

function isFolderExpanded(key) {
  return folderStates[key] !== false
}

function toggleFolder(key) {
  folderStates[key] = !isFolderExpanded(key)
}

function collapseAllFolders() {
  dashboardTree.value.folderKeys.forEach((folder) => {
    folderStates[folder.key] = false
  })
}

function fallbackGrafanaFrameHeight() {
  if (typeof window === 'undefined') return 2600
  const isMobile = window.innerWidth <= 760
  const ratio = isMobile ? 3.6 : 3.4
  return Math.max(isMobile ? 2200 : 2600, Math.round(window.innerHeight * ratio))
}

function clearGrafanaFrameMeasure() {
  if (grafanaFrameMeasureTimer) {
    window.clearTimeout(grafanaFrameMeasureTimer)
    grafanaFrameMeasureTimer = null
  }
  if (grafanaFrameMeasureInterval) {
    window.clearInterval(grafanaFrameMeasureInterval)
    grafanaFrameMeasureInterval = null
  }
  if (grafanaFrameResizeObserver) {
    grafanaFrameResizeObserver.disconnect()
    grafanaFrameResizeObserver = null
  }
}

function measureGrafanaFrameHeight() {
  const frame = immersiveFrameRef.value
  if (!frame) return false
  try {
    const doc = frame.contentDocument || frame.contentWindow?.document
    if (!doc) return false
    const body = doc.body
    const root = doc.documentElement
    const measuredHeight = Math.max(
      body?.scrollHeight || 0,
      body?.offsetHeight || 0,
      root?.clientHeight || 0,
      root?.scrollHeight || 0,
      root?.offsetHeight || 0
    )
    if (measuredHeight > 0) {
      immersiveFrameHeight.value = Math.max(measuredHeight + 24, fallbackGrafanaFrameHeight())
    }
    return true
  } catch {
    immersiveFrameHeight.value = fallbackGrafanaFrameHeight()
    return false
  }
}

function scheduleGrafanaFrameMeasure() {
  clearGrafanaFrameMeasure()
  immersiveFrameHeight.value = fallbackGrafanaFrameHeight()
  if (!fullscreenVisible.value || !selectedDashboardUrl.value) return
  grafanaFrameMeasureTimer = window.setTimeout(() => {
    const canReadFrame = measureGrafanaFrameHeight()
    if (!canReadFrame) return
    const frame = immersiveFrameRef.value
    const doc = frame?.contentDocument || frame?.contentWindow?.document
    const resizeTarget = doc?.body || doc?.documentElement
    if (resizeTarget && typeof ResizeObserver !== 'undefined') {
      grafanaFrameResizeObserver = new ResizeObserver(() => measureGrafanaFrameHeight())
      grafanaFrameResizeObserver.observe(resizeTarget)
    }
    grafanaFrameMeasureInterval = window.setInterval(measureGrafanaFrameHeight, 1000)
    window.setTimeout(() => {
      if (grafanaFrameMeasureInterval) {
        window.clearInterval(grafanaFrameMeasureInterval)
        grafanaFrameMeasureInterval = null
      }
    }, 12000)
  }, 300)
}

function handleGrafanaFrameLoad() {
  scheduleGrafanaFrameMeasure()
}

function openFullscreen(item) {
  if (item?.key) {
    selectedKey.value = item.key
  }
  if (!item?.url) {
    return
  }
  fullscreenVisible.value = true
  nextTick(scheduleGrafanaFrameMeasure)
}

function closeFullscreen() {
  fullscreenVisible.value = false
  clearGrafanaFrameMeasure()
}

function handleKeydown(event) {
  if (event.key === 'Escape' && fullscreenVisible.value) {
    closeFullscreen()
  }
}

watch(
  () => filteredDashboards.value,
  (items) => {
    if (!items.length) {
      if (!overviewLoaded.value || loading.value) {
        return
      }
      selectedKey.value = ''
      fullscreenVisible.value = false
      return
    }
    if (!items.some((item) => item.key === selectedKey.value) && !findDashboardByIdentity(selectedKey.value)) {
      selectedKey.value = items[0].key
    }
  },
  { immediate: true }
)

watch(
  () => dashboardTree.value.folderKeys.map((folder) => `${folder.key}:${folder.collapsedByDefault ? '1' : '0'}`).join('|'),
  () => {
    const activeKeys = new Set(dashboardTree.value.folderKeys.map((folder) => folder.key))
    dashboardTree.value.folderKeys.forEach((folder) => {
      if (!(folder.key in folderStates)) {
        folderStates[folder.key] = !folder.collapsedByDefault
      }
    })
    Object.keys(folderStates).forEach((key) => {
      if (!activeKeys.has(key)) {
        delete folderStates[key]
      }
    })
  },
  { immediate: true }
)

watch(
  () => dashboardTree.value.folderMap,
  (folderMap) => {
    if (selectedFolderPath.value && !folderMap.has(selectedFolderPath.value)) {
      selectedFolderPath.value = ''
    }
  },
  { immediate: true }
)

watch(
  () => selectedFolderPath.value,
  (path) => {
    if (path) {
      expandFolderAncestors(path)
    }
  },
  { immediate: true }
)

watch(
  () => [route.query.dashboard || '', route.query.folder || '', route.query.keyword || '', route.query.tag || '', route.query.fullscreen || ''].join('|'),
  syncFromRoute,
  { immediate: true }
)

watch(
  () => [selectedKey.value, selectedFolderPath.value, filters.keyword, filters.tag, fullscreenVisible.value ? '1' : '0'].join('|'),
  syncRouteQuery
)

watch(
  () => [fullscreenVisible.value ? '1' : '0', selectedDashboardUrl.value].join('|'),
  () => nextTick(scheduleGrafanaFrameMeasure)
)

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
  window.addEventListener('resize', scheduleGrafanaFrameMeasure)
  loadOverview()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeydown)
  window.removeEventListener('resize', scheduleGrafanaFrameMeasure)
  clearGrafanaFrameMeasure()
})
</script>

<style scoped>
.observability-page {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.observability-page.is-immersive {
  gap: 0;
  min-height: auto;
}

.panel {
  background: linear-gradient(180deg, #ffffff 0%, #fffdf8 100%);
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  box-shadow: 0 6px 16px rgba(15, 23, 42, 0.04);
  padding: 12px 14px;
}

.hero,
.hero-copy,
.hero-title-row,
.hero-actions,
.section-head,
.dashboard-top,
.dashboard-tags,
.dashboard-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.hero-copy {
  gap: 4px;
}

.hero {
  align-items: center;
  justify-content: space-between;
}

.hero-actions {
  align-items: center;
}

.hero-actions :deep(.el-button) {
  border-radius: 10px;
  font-weight: 500;
  min-height: 32px;
  padding: 0 14px;
}

.hero-title-row {
  align-items: center;
  gap: 12px;
}

.hero-title-row h2 {
  font-size: 23px;
  line-height: 1.1;
  margin: 0;
}

.page-inline-desc {
  color: #64748b;
  font-size: 13px;
  line-height: 1.45;
  margin: 0;
  flex: 0 1 auto;
  transform: translateY(1px);
}

.hero-icon {
  align-items: center;
  background: linear-gradient(135deg, #f59e0b, #ea580c);
  border-radius: 16px;
  color: #fff;
  display: inline-flex;
  height: 42px;
  justify-content: center;
  width: 42px;
}

.section-title-main {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.section-head {
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.section-head h3 {
  font-size: 14px;
  line-height: 1.3;
  margin: 0;
}

.section-head--list {
  align-items: flex-start;
  gap: 12px;
}

.section-title-block {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.section-title-main {
  gap: 10px;
}

.section-title-block span {
  color: #64748b;
  font-size: 12px;
  line-height: 1.5;
}

.section-title-summary {
  color: #94a3b8;
  font-size: 11px;
}

.list-head-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  opacity: 0.92;
}

.list-toolbar {
  display: grid;
  gap: 8px;
  grid-template-columns: minmax(0, 1fr) auto;
  margin-bottom: 8px;
}

.list-toolbar__filters {
  display: grid;
  gap: 8px;
  grid-template-columns: minmax(0, 1.4fr) 180px;
}

.list-toolbar__summary {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
  color: #94a3b8;
  font-size: 12px;
  padding: 0 2px;
}

.dashboard-groups {
  --dashboard-action-inset: clamp(18px, 3vw, 56px);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.dashboard-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
  position: relative;
}

.group-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 7px 10px;
  border-radius: 9px;
  background: rgba(249, 250, 252, 0.96);
  border: 1px solid rgba(226, 232, 240, 0.92);
  cursor: pointer;
  position: relative;
  overflow: hidden;
  transition: 0.2s ease;
}

.group-head::after {
  content: '';
  position: absolute;
  right: 12px;
  top: 50%;
  width: 34px;
  height: 24px;
  transform: translateY(-50%);
  background:
    radial-gradient(circle at 6px 7px, rgba(245, 158, 11, 0.22) 0 2px, transparent 2.4px),
    radial-gradient(circle at 18px 7px, rgba(148, 163, 184, 0.16) 0 2px, transparent 2.4px),
    radial-gradient(circle at 30px 7px, rgba(148, 163, 184, 0.11) 0 2px, transparent 2.4px),
    linear-gradient(90deg, transparent 0, rgba(148, 163, 184, 0.16) 38%, rgba(148, 163, 184, 0.04) 100%);
  mask-image: linear-gradient(90deg, transparent 0, #000 28%, #000 100%);
  opacity: 0.58;
  pointer-events: none;
}

.group-head.is-selected {
  border-color: rgba(229, 231, 235, 0.98);
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.035);
  background: rgba(251, 250, 246, 0.98);
}

.group-head--nested {
  margin-left: calc(var(--tree-depth) * 18px);
}

.group-head--nested::before {
  content: '';
  position: absolute;
  left: -11px;
  top: 6px;
  bottom: 6px;
  width: 1px;
  background: rgba(226, 232, 240, 0.82);
}

.group-head:hover {
  border-color: rgba(226, 232, 240, 0.98);
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.03);
}

.group-head__main {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
  position: relative;
  z-index: 1;
}

.group-head__toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  padding: 0;
  border: 1px solid rgba(229, 231, 235, 0.92);
  border-radius: 5px;
  color: #94a3b8;
  background: rgba(255, 255, 255, 0.92);
  cursor: pointer;
}

.group-head__folder-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 6px;
  color: #a16207;
  background: rgba(250, 247, 240, 0.98);
  border: 1px solid rgba(243, 234, 214, 0.96);
}

.group-head__meta {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 3px;
  min-width: 0;
  flex-wrap: wrap;
}

.group-head__meta strong {
  color: #1f2937;
  font-size: 12.5px;
  font-weight: 600;
}

.group-head__meta span {
  color: #a8b2c3;
  font-size: 11px;
  line-height: 1.4;
}

.group-head__stats {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: flex-end;
  margin-right: var(--dashboard-action-inset);
  position: relative;
  z-index: 1;
}

.group-head__count {
  min-width: 60px;
  height: 20px;
  padding: 0 7px;
  border-radius: 999px;
  border: 1px solid rgba(229, 231, 235, 0.96);
  background: rgba(255, 255, 255, 0.92);
  color: #94a3b8;
  font-size: 10px;
  font-weight: 500;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.group-head__actions {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-wrap: wrap;
  opacity: 0.78;
  transition: opacity 0.18s ease;
}

.dashboard-card {
  background: rgba(255, 255, 255, 0.98);
  border: 1px solid rgba(226, 232, 240, 0.94);
  border-radius: 9px;
  padding: 0;
  cursor: pointer;
  transition: 0.18s ease;
}

.dashboard-card--tree {
  margin-left: calc(var(--tree-depth) * 18px);
  position: relative;
  overflow: hidden;
}

.dashboard-card--tree::before {
  content: '';
  position: absolute;
  left: -11px;
  top: 4px;
  bottom: 4px;
  width: 1px;
  border-radius: 999px;
  background: rgba(226, 232, 240, 0.82);
}

.dashboard-card--tree::after {
  content: '';
  position: absolute;
  right: 13px;
  top: 50%;
  width: 38px;
  height: 28px;
  transform: translateY(-50%);
  background:
    linear-gradient(90deg, transparent 0 8px, rgba(79, 107, 149, 0.14) 8px 10px, transparent 10px 16px, rgba(148, 163, 184, 0.12) 16px 18px, transparent 18px 24px, rgba(148, 163, 184, 0.08) 24px 26px, transparent 26px),
    radial-gradient(circle at 10px 7px, rgba(79, 107, 149, 0.12) 0 1.8px, transparent 2.2px),
    radial-gradient(circle at 22px 15px, rgba(148, 163, 184, 0.13) 0 1.8px, transparent 2.2px),
    radial-gradient(circle at 34px 9px, rgba(148, 163, 184, 0.09) 0 1.8px, transparent 2.2px);
  mask-image: linear-gradient(90deg, transparent 0, #000 30%, #000 100%);
  opacity: 0.56;
  pointer-events: none;
}

.dashboard-card.active {
  border-color: rgba(226, 232, 240, 0.98);
  box-shadow: inset 2px 0 0 rgba(148, 163, 184, 0.62), 0 4px 12px rgba(15, 23, 42, 0.03);
  background: rgba(250, 251, 253, 0.98);
}

.dashboard-card:hover {
  border-color: rgba(226, 232, 240, 0.98);
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.028);
}

.dashboard-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  padding: 9px 11px 9px 13px;
}

.dashboard-row__meta {
  min-width: 0;
  position: relative;
  z-index: 1;
}

.dashboard-row__mainline {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: flex-start;
  min-width: 0;
  flex-wrap: wrap;
}

.dashboard-tags--inline {
  gap: 5px;
}

.dashboard-row__aside {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
  margin-right: var(--dashboard-action-inset);
  opacity: 0.78;
  position: relative;
  z-index: 1;
  transition: opacity 0.18s ease;
}

.dashboard-row__meta strong {
  display: block;
  font-size: 13px;
  margin-bottom: 0;
  color: #1f2937;
  font-weight: 600;
}

.dashboard-row__kind {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border-radius: 5px;
  background: rgba(243, 246, 250, 0.98);
  border: 1px solid rgba(226, 232, 240, 0.96);
}

.dashboard-row__kind-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 2px;
  width: 8px;
  height: 8px;
}

.dashboard-row__kind-grid i {
  display: block;
  width: 3px;
  height: 3px;
  border-radius: 1px;
  background: #94a3b8;
}

.dashboard-chip {
  background: rgba(248, 250, 252, 0.96);
  border: 1px solid rgba(226, 232, 240, 0.92);
  border-radius: 999px;
  color: #94a3b8;
  font-size: 10px;
  padding: 1px 6px;
}

.row-more-btn {
  color: #64748b;
  min-width: 24px;
  min-height: 24px;
  padding: 3px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid rgba(229, 231, 235, 0.92);
  transition: 0.18s ease;
}

.row-more-btn:hover,
.row-more-btn:focus-visible {
  color: #64748b;
  background: rgba(249, 250, 251, 0.98);
  border-color: rgba(226, 232, 240, 0.98);
}

.row-more-btn--folder {
  background: rgba(250, 250, 252, 0.96);
}

.row-more-btn :deep(.el-icon) {
  margin-left: 0;
}

.dashboard-actions :deep(.el-button--primary.is-link) {
  color: #4f6b95;
  font-weight: 500;
}

.dashboard-actions :deep(.el-button--primary.is-link:hover),
.dashboard-actions :deep(.el-button--primary.is-link:focus-visible) {
  color: #3b5b8c;
}

.dropdown-item-label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.dropdown-item-label--danger {
  color: #dc2626;
}

.help-dialog {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.help-section h4 {
  margin: 0 0 6px;
  font-size: 14px;
  color: #1f2937;
}

.help-section p {
  margin: 0;
  color: #64748b;
  line-height: 1.7;
}

.help-note {
  margin-top: 8px !important;
  font-size: 12px;
  color: #94a3b8 !important;
}

.help-code {
  margin: 10px 0 0;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid rgba(226, 232, 240, 0.96);
  background: rgba(248, 250, 252, 0.98);
  color: #334155;
  font-size: 12px;
  line-height: 1.7;
  white-space: pre-wrap;
}

.help-list {
  margin: 8px 0 0;
  padding-left: 18px;
  color: #64748b;
}

.help-list li {
  line-height: 1.8;
}

.group-head:hover .group-head__actions,
.group-head.is-selected .group-head__actions,
.dashboard-card:hover .dashboard-row__aside,
.dashboard-card.active .dashboard-row__aside {
  opacity: 1;
}

.config-folder-field,
.config-url-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.config-folder-preview {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  min-height: 22px;
}

.config-folder-level {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(241, 245, 249, 0.92);
  border: 1px solid rgba(226, 232, 240, 0.92);
  color: #475569;
  font-size: 12px;
}

.config-folder-level:not(:last-child)::after {
  content: '/';
  margin-left: 6px;
  color: #94a3b8;
}

.config-folder-preview__empty,
.config-url-hint,
.drawer-field__hint {
  color: #94a3b8;
  font-size: 12px;
  line-height: 1.5;
}

.config-url-error {
  color: #dc2626;
  font-size: 12px;
  line-height: 1.4;
}

.config-url-field :deep(.is-invalid .el-input__wrapper) {
  box-shadow: 0 0 0 1px rgba(220, 38, 38, 0.45) inset;
}

.dialog-form,
.drawer-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.dialog-field,
.drawer-field {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.dialog-field label,
.drawer-field label {
  color: #334155;
  font-size: 13px;
  font-weight: 600;
}

.dialog-field-label {
  align-items: baseline;
  display: inline-flex;
  gap: 8px;
}

.dialog-field-label small {
  color: #94a3b8;
  font-size: 12px;
  font-weight: 500;
}

.dialog-field__content {
  padding: 10px 12px;
  border-radius: 10px;
  background: rgba(248, 250, 252, 0.95);
  border: 1px solid rgba(226, 232, 240, 0.95);
  color: #0f172a;
  font-size: 13px;
  line-height: 1.5;
  word-break: break-all;
}

.dialog-field--inline {
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
}

.drawer-field--inline {
  align-items: flex-start;
  display: grid;
  grid-template-columns: 86px minmax(0, 1fr);
}

.drawer-inline-control {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.drawer-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.immersive-shell {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-height: auto;
  padding: 2px;
  border: 0;
  box-shadow: none;
  background:
    radial-gradient(circle at top right, rgba(249, 115, 22, 0.14), transparent 28%),
    linear-gradient(180deg, #fffdf8 0%, #ffffff 100%);
}

.immersive-toolbar {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 8px;
  flex-wrap: wrap;
  padding: 6px 8px;
  border: 1px solid rgba(251, 146, 60, 0.18);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(10px);
}

.immersive-toolbar__meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.immersive-toolbar__title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  min-width: 0;
}

.immersive-toolbar__meta strong {
  color: #0f172a;
  font-size: 16px;
}

.immersive-toolbar__meta span {
  color: #64748b;
  font-size: 12px;
}

.immersive-toolbar__hint {
  display: inline-flex;
  align-items: center;
  height: 20px;
  padding: 0 8px;
  margin-left: 10px;
  border-radius: 999px;
  border: 1px solid rgba(251, 191, 36, 0.28);
  background: rgba(255, 247, 219, 0.92);
  color: #a16207 !important;
  font-size: 10px !important;
  line-height: 1;
  white-space: nowrap;
}

.immersive-toolbar__tags {
  gap: 5px;
}

.immersive-toolbar__actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-left: auto;
}

.immersive-stage {
  flex: 0 0 auto;
  min-height: auto;
  overflow: visible;
  border-radius: 8px;
  border: 0;
  background: linear-gradient(180deg, #fff 0%, #f8fafc 100%);
}

.immersive-frame {
  width: 100%;
  height: max(1800px, 220vh);
  min-height: calc(100vh - 148px);
  display: block;
  border: 0;
  border-radius: 8px;
  background: #fff;
}

@media (max-width: 1200px) {
  .list-toolbar,
  .list-toolbar__filters {
    grid-template-columns: 1fr;
  }

  .list-toolbar__summary {
    justify-content: flex-start;
  }
}

@media (max-width: 760px) {
  .dashboard-groups {
    --dashboard-action-inset: 0px;
  }

  .hero,
  .section-head,
  .immersive-toolbar,
  .dialog-field--inline,
  .drawer-field--inline {
    align-items: stretch;
    flex-direction: column;
    grid-template-columns: 1fr;
  }

  .dashboard-row {
    grid-template-columns: 1fr;
  }

  .dashboard-row__mainline,
  .dashboard-row__aside {
    justify-content: flex-start;
  }

  .dashboard-row__mainline {
    align-items: flex-start;
    flex-direction: column;
    gap: 4px;
  }

  .dashboard-row__desc {
    text-align: left;
    white-space: normal;
  }

  .group-head,
  .group-head__stats {
    align-items: flex-start;
    justify-content: flex-start;
  }

  .immersive-frame {
    height: max(1400px, 240vh);
    min-height: calc(100vh - 204px);
  }
}

.hero.panel {
  border-radius: 20px;
}
</style>
