<template>
  <div class="fade-in">
    <!-- 标签页切换 -->
    <div class="page-header">
      <h2>服务市场</h2>
      <div class="market-tabs">
        <button class="tab-btn" :class="{ active: activeTab === 'market' }" @click="activeTab = 'market'">
          <el-icon><Shop /></el-icon> 服务市场
        </button>
        <button class="tab-btn" :class="{ active: activeTab === 'deploy' }" @click="activeTab = 'deploy'; fetchDeployments()">
          <el-icon><Setting /></el-icon> 部署管理
          <span v-if="deployments.length" class="tab-badge">{{ deployments.length }}</span>
        </button>
      </div>
    </div>

    <!-- ============ 服务市场 Tab ============ -->
    <div v-show="activeTab === 'market'" class="market-content">
      <!-- 分类筛选 -->
      <div class="category-bar">
        <button
          v-for="cat in categories"
          :key="cat.value"
          class="cat-btn"
          :class="{ active: activeCategory === cat.value }"
          @click="activeCategory = cat.value"
        >{{ cat.label }}</button>
      </div>

      <!-- 服务卡片网格 -->
      <div class="service-grid">
        <div
          v-for="tpl in filteredTemplates"
          :key="tpl.id"
          class="service-card"
          @click="openDeployDialog(tpl)"
        >
          <div class="card-icon" :class="'icon-' + tpl.icon">
            <span class="icon-text">{{ getIconEmoji(tpl.icon) }}</span>
          </div>
          <div class="card-name">{{ tpl.name }}</div>
          <div class="card-desc">{{ tpl.description }}</div>
          <div class="card-versions">
            <el-tag
              v-for="ver in tpl.versions"
              :key="ver"
              type="primary"
              size="small"
              effect="plain"
              round
            >{{ ver }}</el-tag>
          </div>
          <!-- 已部署标记 -->
          <div v-if="isDeployed(tpl.id)" class="deployed-badge">
            <el-icon><CircleCheckFilled /></el-icon> 已部署
          </div>
        </div>
      </div>
    </div>

    <!-- ============ 部署管理 Tab ============ -->
    <div v-show="activeTab === 'deploy'" class="deploy-content">
      <div class="table-card">
        <el-table :data="deployments" stripe v-loading="depLoading" style="width:100%">
          <el-table-column label="服务" min-width="140">
            <template #default="{ row }">
              <div style="display:flex; align-items:center; gap:8px;">
                <span class="mini-icon" :class="'icon-' + row.template_icon">{{ getIconEmoji(row.template_icon) }}</span>
                <span style="font-weight:600;">{{ row.template_name }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="version" label="版本" width="100" />
          <el-table-column label="目标主机" min-width="160">
            <template #default="{ row }">{{ row.host_name }} ({{ row.host_ip }})</template>
          </el-table-column>
          <el-table-column prop="status" label="状态" width="110">
            <template #default="{ row }">
              <el-tag :type="depStatusType(row.status)" size="small">{{ row.status_display }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="deployer" label="部署人" width="90" />
          <el-table-column prop="created_at" label="部署时间" width="170">
            <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="230" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="viewLogs(row)">日志</el-button>
              <el-button v-if="row.status === 'running'" link type="warning" size="small" @click="handleStop(row)">停止</el-button>
              <el-button v-if="row.status === 'stopped'" link type="success" size="small" @click="handleStart(row)">启动</el-button>
              <el-popconfirm title="确定卸载该服务? 数据将被清除!" @confirm="handleRemove(row)">
                <template #reference>
                  <el-button link type="danger" size="small">卸载</el-button>
                </template>
              </el-popconfirm>
              <el-button link type="info" size="small" @click="viewDeployLog(row)">详情</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <!-- ============ 部署对话框 ============ -->
    <el-dialog v-model="deployVisible" :title="'部署 ' + (deployTemplate?.name || '')" width="90%" style="max-width:560px;" top="5vh" append-to-body destroy-on-close>
      <el-form :model="deployForm" label-width="100px">
        <el-form-item label="目标主机">
          <el-select v-model="deployForm.host_id" placeholder="选择主机" style="width:100%">
            <el-option v-for="h in hosts" :key="h.id" :label="`${h.hostname} (${h.ip_address})`" :value="h.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="版本">
          <el-select v-model="deployForm.version" placeholder="选择版本" style="width:100%">
            <el-option v-for="v in (deployTemplate?.versions || [])" :key="v" :label="v" :value="v" />
          </el-select>
        </el-form-item>

        <!-- 动态配置项 -->
        <template v-if="deployTemplate?.env_schema">
          <el-divider content-position="left">配置参数</el-divider>
          <el-form-item v-for="field in deployTemplate.env_schema" :key="field.key" :label="field.label">
            <el-input v-model="deployForm.env_config[field.key]" :placeholder="field.default" />
          </el-form-item>
        </template>

        <el-form-item label="部署人">
          <el-input v-model="deployForm.deployer" style="width:200px" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="deployVisible = false">取消</el-button>
        <el-button type="primary" :loading="deploying" @click="handleDeploy">
          <el-icon><Promotion /></el-icon> 开始部署
        </el-button>
      </template>
    </el-dialog>

    <!-- ============ 日志对话框 ============ -->
    <el-dialog v-model="logVisible" title="容器日志" width="90%" style="max-width:800px;" top="5vh" append-to-body destroy-on-close>
      <pre class="log-output">{{ logContent || '加载中...' }}</pre>
    </el-dialog>

    <!-- ============ 部署详情对话框 ============ -->
    <el-dialog v-model="detailVisible" title="部署详情" width="90%" style="max-width:700px;" top="5vh" append-to-body destroy-on-close>
      <template v-if="detailDep">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="服务">{{ detailDep.template_name }}</el-descriptions-item>
          <el-descriptions-item label="版本">{{ detailDep.version }}</el-descriptions-item>
          <el-descriptions-item label="目标主机">{{ detailDep.host_name }} ({{ detailDep.host_ip }})</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="depStatusType(detailDep.status)" size="small">{{ detailDep.status_display }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="部署人">{{ detailDep.deployer }}</el-descriptions-item>
          <el-descriptions-item label="部署目录">{{ detailDep.deploy_dir }}</el-descriptions-item>
          <el-descriptions-item label="创建时间" :span="2">{{ formatTime(detailDep.created_at) }}</el-descriptions-item>
        </el-descriptions>
        <el-divider content-position="left">部署日志</el-divider>
        <pre class="log-output">{{ detailDep.deploy_log || '暂无日志' }}</pre>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  getTemplates, getDeployments, deployService,
  stopService, startService, removeService, getServiceLogs,
} from '@/api/modules/marketplace'
import { getHosts } from '@/api/modules/ops'

// ====== 数据 ======
const templates = ref([])
const deployments = ref([])
const hosts = ref([])
const activeTab = ref('market')
const activeCategory = ref('all')
const depLoading = ref(false)

const categories = [
  { label: '全部', value: 'all' },
  { label: '数据库', value: 'database' },
  { label: '缓存', value: 'cache' },
  { label: 'CI/CD', value: 'cicd' },
  { label: '监控与日志', value: 'monitoring' },
  { label: '安全运维', value: 'security' },
  { label: '中间件', value: 'middleware' },
  { label: '开发环境', value: 'devenv' },
]

const ICON_MAP = {
  mysql: '🐬', redis: '🔴', postgresql: '🐘', nginx: '🟢',
  jenkins: '🔧', gitlab: '🦊', grafana: '📊', elasticsearch: '🔍',
  loki: '📋', jumpserver: '🛡️', nacos: '🌐', xxljob: '⏰',
}

// ====== 计算 ======
const filteredTemplates = computed(() => {
  if (activeCategory.value === 'all') return templates.value
  return templates.value.filter(t => t.category === activeCategory.value)
})

// ====== 方法 ======
function getIconEmoji(icon) { return ICON_MAP[icon] || '📦' }

function isDeployed(tplId) {
  return deployments.value.some(d => d.template === tplId)
}

function formatTime(iso) {
  if (!iso) return '-'
  const d = new Date(iso)
  return d.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function depStatusType(s) {
  const m = { running: 'success', stopped: 'info', deploying: 'warning', pending: '', failed: 'danger', removing: 'warning' }
  return m[s] || ''
}

// ====== 加载数据 ======
async function fetchTemplates() {
  try { templates.value = await getTemplates() } catch (e) { /* handled by interceptor */ }
}
async function fetchDeployments() {
  depLoading.value = true
  try {
    const res = await getDeployments()
    deployments.value = res.results || res
  } catch (e) { /* */ }
  depLoading.value = false
}
async function fetchHosts() {
  try {
    const res = await getHosts()
    hosts.value = res.results || res
  } catch (e) { /* */ }
}

onMounted(() => {
  fetchTemplates()
  fetchDeployments()
  fetchHosts()
})

// ====== 部署逻辑 ======
const deployVisible = ref(false)
const deployTemplate = ref(null)
const deployForm = ref({ host_id: null, version: '', env_config: {}, deployer: 'admin' })
const deploying = ref(false)

function openDeployDialog(tpl) {
  deployTemplate.value = tpl
  const config = {}
  ;(tpl.env_schema || []).forEach(f => { config[f.key] = f.default || '' })
  deployForm.value = {
    host_id: null,
    version: tpl.versions?.[0] || '',
    env_config: config,
    deployer: 'admin',
  }
  deployVisible.value = true
}

async function handleDeploy() {
  if (!deployForm.value.host_id) return ElMessage.warning('请选择目标主机')
  if (!deployForm.value.version) return ElMessage.warning('请选择版本')

  deploying.value = true
  try {
    await deployService({
      template_id: deployTemplate.value.id,
      host_id: deployForm.value.host_id,
      version: deployForm.value.version,
      env_config: deployForm.value.env_config,
      deployer: deployForm.value.deployer,
    })
    ElMessage.success('部署任务已发起，请在"部署管理"中查看进度')
    deployVisible.value = false
    fetchDeployments()
  } catch (e) { /* */ }
  deploying.value = false
}

// ====== 操作 ======
async function handleStop(dep) {
  try { await stopService(dep.id); ElMessage.success('服务已停止'); fetchDeployments() } catch (e) { /* */ }
}
async function handleStart(dep) {
  try { await startService(dep.id); ElMessage.success('服务已启动'); fetchDeployments() } catch (e) { /* */ }
}
async function handleRemove(dep) {
  try { await removeService(dep.id); ElMessage.success('服务已卸载'); fetchDeployments() } catch (e) { /* */ }
}

// ====== 日志 ======
const logVisible = ref(false)
const logContent = ref('')
async function viewLogs(dep) {
  logContent.value = ''
  logVisible.value = true
  try {
    const res = await getServiceLogs(dep.id)
    logContent.value = res.logs
  } catch (e) {
    logContent.value = '获取日志失败'
  }
}

// ====== 部署详情 ======
const detailVisible = ref(false)
const detailDep = ref(null)
function viewDeployLog(dep) {
  detailDep.value = dep
  detailVisible.value = true
}
</script>
