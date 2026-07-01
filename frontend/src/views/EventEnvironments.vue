<template>
  <div class="fade-in event-env-page workbench-page-shell">
    <section class="hero panel">
      <div class="release-hero-copy">
        <div class="release-hero-title-row">
          <span class="event-env-header-icon">
            <el-icon><CollectionTag /></el-icon>
          </span>
          <h2>事件环境</h2>
          <p class="page-inline-desc">维护事件中心认可的环境标识、显示名称和环境别名，外部事件按配置校验并统一归集。</p>
        </div>
      </div>
    </section>

    <EventWallTabs />

    <section class="workbench-card event-env-card" v-loading="loading">
      <div class="section-toolbar">
        <div class="toolbar-head">
          <span class="toolbar-title">环境字典</span>
          <span class="toolbar-desc">共 {{ environments.length }} 个环境，当前显示 {{ filteredEnvironments.length }} 个</span>
        </div>
        <div class="workbench-card-actions">
          <el-button class="filter-refresh-btn" :loading="loading" @click="loadAll">
            <el-icon><RefreshRight /></el-icon>
            刷新
          </el-button>
          <el-button v-if="canManage" type="primary" @click="openCreate">
            <el-icon><Plus /></el-icon>
            新建环境
          </el-button>
        </div>
      </div>

      <div class="workbench-toolbar workbench-toolbar--history event-env-toolbar">
        <div class="workbench-toolbar-left">
          <el-input
            v-model="searchText"
            clearable
            placeholder="搜索标识 / 名称 / 别名"
            style="width: 260px"
          >
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <el-select v-model="statusFilter" clearable placeholder="状态" style="width: 112px">
            <el-option label="启用" value="enabled" />
            <el-option label="停用" value="disabled" />
          </el-select>
        </div>
      </div>

      <div v-if="unmatched.length" class="unmatched-strip">
        <div class="unmatched-title">
          <el-icon><Warning /></el-icon>
          <span>未映射环境</span>
        </div>
        <span class="unmatched-desc">建议点击后保存未映射环境，或调整事件源的环境标识。</span>
        <button
          v-for="item in unmatched.slice(0, 8)"
          :key="item.environment"
          type="button"
          class="unmatched-chip"
          @click="openFromUnmatched(item)"
        >
          <span>{{ item.environment }}</span>
          <strong>{{ item.count }}</strong>
        </button>
      </div>

      <el-table
        :data="filteredEnvironments"
        size="small"
        row-key="code"
        class="event-env-table"
        :empty-text="loading ? '加载中' : '暂无事件环境'"
      >
        <el-table-column label="环境标识" min-width="170" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="code-cell">
              <span>{{ row.code }}</span>
              <el-tag v-if="row.enabled" size="small" effect="plain" type="success">启用</el-tag>
              <el-tag v-else size="small" effect="plain" type="info">停用</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="显示名称" min-width="150" show-overflow-tooltip />
        <el-table-column label="环境别名" min-width="220">
          <template #default="{ row }">
            <div class="alias-wrap">
              <el-tag v-for="item in row.aliases || []" :key="item" size="small" effect="plain">{{ item }}</el-tag>
              <span v-if="!(row.aliases || []).length" class="muted">-</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="事件数" width="104" align="right" header-align="right">
          <template #default="{ row }">{{ row.event_count || 0 }}</template>
        </el-table-column>
        <el-table-column label="最近事件" width="156">
          <template #default="{ row }">{{ formatShortTime(row.last_seen_at) }}</template>
        </el-table-column>
        <el-table-column prop="description" label="说明" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ row.description || '-' }}</template>
        </el-table-column>
        <el-table-column v-if="canManage" label="操作" width="168" fixed="right" align="left" header-align="left">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openEdit(row)">
              <el-icon><Edit /></el-icon>
              编辑
            </el-button>
            <el-button link size="small" @click="toggleEnabled(row)">
              {{ row.enabled ? '停用' : '启用' }}
            </el-button>
            <el-button link type="danger" size="small" @click="removeEnvironment(row)">
              <el-icon><Delete /></el-icon>
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog
      v-model="dialogVisible"
      :title="editingCode ? '编辑事件环境' : '新建事件环境'"
      width="560px"
      append-to-body
      destroy-on-close
      class="event-env-dialog"
    >
      <el-form label-position="top" :model="form" class="env-form">
        <el-form-item label="环境标识">
          <el-input v-model="form.code" :disabled="Boolean(editingCode)" placeholder="例如：ecommerce-prod" />
          <div class="field-help">外部事件 payload 的 environment 建议填写这个标识，创建后不建议修改。</div>
        </el-form-item>
        <el-form-item label="显示名称">
          <el-input v-model="form.name" placeholder="例如：电商生产环境" />
        </el-form-item>
        <el-form-item label="环境别名">
          <el-input v-model="aliasText" type="textarea" :rows="3" placeholder="例如：支付生产、订单测试环境-k3s" />
        </el-form-item>
        <el-form-item label="排序">
          <div class="sort-control-row">
            <el-input-number v-model="form.sort_order" :min="0" :step="10" />
            <span>越小越靠前</span>
          </div>
        </el-form-item>
        <el-form-item label="启用状态">
          <el-switch v-model="form.enabled" active-text="启用" inactive-text="停用" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="form.description" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveEnvironment">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CollectionTag, Delete, Edit, Plus, RefreshRight, Search, Warning } from '@element-plus/icons-vue'
import {
  createEventEnvironment,
  deleteEventEnvironment,
  getEventEnvironments,
  getUnmatchedEventEnvironments,
  updateEventEnvironment,
} from '@/api/modules/eventwall'
import EventWallTabs from '@/components/eventwall/EventWallTabs.vue'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
const loading = ref(false)
const saving = ref(false)
const dialogVisible = ref(false)
const editingCode = ref('')
const environments = ref([])
const unmatched = ref([])
const aliasText = ref('')
const searchText = ref('')
const statusFilter = ref('')
const form = reactive({
  code: '',
  name: '',
  aliases: [],
  description: '',
  enabled: true,
  sort_order: 100,
})

const canManage = computed(() => authStore.hasPermission('eventwall.environment.manage'))
const filteredEnvironments = computed(() => {
  const keyword = searchText.value.trim().toLowerCase()
  return environments.value.filter((item) => {
    if (statusFilter.value === 'enabled' && !item.enabled) return false
    if (statusFilter.value === 'disabled' && item.enabled) return false
    if (!keyword) return true
    const haystack = [
      item.code,
      item.name,
      item.description,
      ...(item.aliases || []),
    ].join(' ').toLowerCase()
    return haystack.includes(keyword)
  })
})

function resetForm() {
  editingCode.value = ''
  aliasText.value = ''
  Object.assign(form, { code: '', name: '', aliases: [], description: '', enabled: true, sort_order: 100 })
}

function parseAliases() {
  return aliasText.value
    .split(/[\n,，]/)
    .map(item => item.trim())
    .filter(Boolean)
    .filter((item, index, list) => list.findIndex(other => other.toLowerCase() === item.toLowerCase()) === index)
}

function openCreate() {
  resetForm()
  dialogVisible.value = true
}

function openEdit(row) {
  editingCode.value = row.code
  Object.assign(form, {
    code: row.code,
    name: row.name,
    aliases: row.aliases || [],
    description: row.description || '',
    enabled: Boolean(row.enabled),
    sort_order: row.sort_order ?? 100,
  })
  aliasText.value = (row.aliases || []).join(', ')
  dialogVisible.value = true
}

function openFromUnmatched(item) {
  if (!canManage.value) return
  resetForm()
  form.code = item.environment
  form.name = item.environment
  dialogVisible.value = true
}

async function loadAll() {
  loading.value = true
  try {
    const [envResponse, unmatchedResponse] = await Promise.all([
      getEventEnvironments({ page_size: 200 }),
      getUnmatchedEventEnvironments(),
    ])
    environments.value = envResponse.results || envResponse || []
    unmatched.value = unmatchedResponse || []
  } finally {
    loading.value = false
  }
}

async function saveEnvironment() {
  if (!form.code.trim() || !form.name.trim()) {
    ElMessage.warning('请填写环境标识和显示名称')
    return
  }
  saving.value = true
  try {
    const payload = {
      ...form,
      code: form.code.trim(),
      name: form.name.trim(),
      aliases: parseAliases(),
    }
    if (editingCode.value) {
      await updateEventEnvironment(editingCode.value, payload)
      ElMessage.success('事件环境已更新')
    } else {
      await createEventEnvironment(payload)
      ElMessage.success('事件环境已创建')
    }
    dialogVisible.value = false
    await loadAll()
  } finally {
    saving.value = false
  }
}

async function toggleEnabled(row) {
  await updateEventEnvironment(row.code, { enabled: !row.enabled })
  ElMessage.success(row.enabled ? '事件环境已停用' : '事件环境已启用')
  await loadAll()
}

async function removeEnvironment(row) {
  try {
    await ElMessageBox.confirm(`确认删除事件环境「${row.name || row.code}」吗？历史事件不会删除。`, '删除事件环境', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch (error) {
    return
  }
  await deleteEventEnvironment(row.code)
  ElMessage.success('事件环境已删除')
  await loadAll()
}

function formatShortTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
}

onMounted(loadAll)
</script>

<style scoped>
.event-env-page {
  display: flex;
  flex-direction: column;
  gap: 0;
  color: #1f2329;
}

.panel {
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.98) 0%, rgba(250, 252, 255, 0.96) 100%);
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 18px;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.04);
  padding: 14px 16px;
}

.hero {
  min-height: 68px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 0;
  background: linear-gradient(135deg, #fbfdff 0%, #f7faff 52%, #f9fbfd 100%);
  border-color: rgba(36, 91, 219, 0.09);
}

.release-hero-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.hero h2 {
  margin: 0;
  color: #0f172a;
  font-size: 23px;
  font-weight: 700;
  line-height: 1.1;
}

.page-inline-desc {
  color: #475569;
  font-size: 13px;
  line-height: 1.45;
  margin: 0;
  flex: 0 1 auto;
  transform: translateY(1px);
}

.event-env-header-icon {
  width: 42px;
  height: 42px;
  border-radius: 14px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  color: #245bdb;
  background: linear-gradient(180deg, #f3f7ff 0%, #ebf2ff 100%);
  border: 1px solid rgba(36, 91, 219, 0.12);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.8);
}

.hero.panel {
  border-radius: 20px;
}

.event-env-card {
  padding: 12px;
}

.event-env-page .hero + :deep(.event-tabs-shell) {
  margin-top: 6px;
}

.event-env-page :deep(.event-tabs-shell) + .event-env-card {
  margin-top: 3px;
}

.event-env-page :deep(.event-tabs-shell) {
  padding: 3px;
}

.event-env-page :deep(.event-tab) {
  padding: 0 18px;
}

.section-toolbar,
.toolbar-head,
.workbench-card-actions,
.workbench-toolbar,
.workbench-toolbar-left,
.unmatched-strip,
.unmatched-title,
.code-cell,
.alias-wrap {
  display: flex;
  align-items: center;
}

.section-toolbar {
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 6px;
}

.toolbar-head {
  gap: 8px;
  min-width: 0;
  flex-wrap: wrap;
}

.toolbar-title {
  color: #0f172a;
  font-size: 15px;
  font-weight: 700;
}

.toolbar-desc {
  color: #64748b;
  font-size: 12px;
}

.workbench-card-actions {
  gap: 8px;
  flex-shrink: 0;
}

.workbench-card-actions :deep(.el-button),
.event-env-dialog :deep(.el-button) {
  min-height: 30px;
  border-radius: 9px;
}

.filter-refresh-btn {
  border-color: rgba(148, 163, 184, 0.16);
  background: rgba(255, 255, 255, 0.9);
  color: #475569;
  box-shadow: none;
}

.filter-refresh-btn:hover {
  border-color: rgba(59, 130, 246, 0.18);
  color: #1d4ed8;
  background: #f8fbff;
}

.workbench-toolbar {
  justify-content: space-between;
  gap: 10px;
  padding: 7px 8px;
  border: 1px solid rgba(148, 163, 184, 0.14);
  border-radius: 12px;
  background: #f8fafc;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.75);
  margin-bottom: 6px;
}

.workbench-toolbar-left {
  gap: 8px;
  min-width: 0;
  flex-wrap: nowrap;
  overflow-x: auto;
}

.workbench-toolbar :deep(.el-input__wrapper),
.workbench-toolbar :deep(.el-select__wrapper) {
  min-height: 30px;
  border-radius: 9px;
  box-shadow: 0 0 0 1px rgba(148, 163, 184, 0.16) inset;
  background: #ffffff;
}

.unmatched-strip {
  gap: 6px;
  min-height: 34px;
  padding: 6px 8px;
  margin-bottom: 6px;
  border: 1px solid rgba(245, 158, 11, 0.16);
  border-radius: 12px;
  background: #fffbeb;
  overflow-x: auto;
}

.unmatched-title {
  gap: 5px;
  flex: 0 0 auto;
  color: #92400e;
  font-size: 12px;
  font-weight: 700;
}

.unmatched-desc {
  flex: 0 0 auto;
  color: #a16207;
  font-size: 12px;
  white-space: nowrap;
}

.unmatched-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-height: 24px;
  padding: 0 8px;
  border: 1px solid rgba(245, 158, 11, 0.14);
  border-radius: 8px;
  background: #ffffff;
  color: #92400e;
  cursor: pointer;
  font: inherit;
  font-size: 12px;
}

.unmatched-chip strong {
  color: #b45309;
}

.event-env-table {
  width: 100%;
}

.event-env-table :deep(.el-table__cell) {
  padding: 6px 0;
}

.event-env-table :deep(th.el-table__cell) {
  color: #475569;
  font-weight: 600;
  background: #f8fafc;
}

.code-cell {
  gap: 6px;
  min-width: 0;
}

.code-cell span {
  min-width: 0;
  overflow: hidden;
  color: #0f172a;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.alias-wrap {
  gap: 4px;
  flex-wrap: wrap;
}

.muted {
  color: #8f959e;
  font-size: 12px;
}

.field-help {
  margin-top: 5px;
  color: #8f959e;
  font-size: 12px;
  line-height: 1.5;
}

.sort-control-row {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.sort-control-row span {
  color: #8f959e;
  font-size: 12px;
  white-space: nowrap;
}

.env-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 12px;
}

.env-form :deep(.el-form-item:nth-child(3)),
.env-form :deep(.el-form-item:nth-child(6)) {
  grid-column: 1 / -1;
}

.env-form :deep(.el-form-item) {
  margin-bottom: 14px;
}

.env-form :deep(.el-input__wrapper),
.env-form :deep(.el-textarea__inner),
.env-form :deep(.el-input-number),
.env-form :deep(.el-input-number .el-input__wrapper) {
  border-radius: 10px;
}

.event-env-dialog :deep(.el-dialog__header) {
  margin-right: 0;
  padding: 16px 18px 10px;
}

.event-env-dialog :deep(.el-dialog__body) {
  padding: 10px 18px 14px;
}

.event-env-dialog :deep(.el-dialog__footer) {
  padding: 10px 18px 16px;
}

@media (max-width: 900px) {
  .section-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .workbench-card-actions {
    justify-content: flex-end;
  }
}

@media (max-width: 760px) {
  .hero {
    align-items: flex-start;
    flex-direction: column;
  }

  .env-form {
    grid-template-columns: 1fr;
  }

  .env-form :deep(.el-form-item) {
    grid-column: 1 / -1;
  }
}
</style>
