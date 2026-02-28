<template>
  <div class="fade-in">
    <div class="page-header">
      <h2>SQL 工单</h2>
      <el-button type="primary" @click="openSubmitDialog">
        <el-icon><Plus /></el-icon> 提交工单
      </el-button>
    </div>

    <div class="table-card">
      <div class="filter-bar">
        <el-input v-model="search" placeholder="搜索标题 / 提交人" clearable style="width: 260px"
          :prefix-icon="Search" @input="fetchData" />
        <el-select v-model="statusFilter" placeholder="状态" clearable style="width: 130px" @change="fetchData">
          <el-option label="待审核" value="pending" />
          <el-option label="已通过" value="approved" />
          <el-option label="已驳回" value="rejected" />
          <el-option label="已执行" value="executed" />
          <el-option label="执行失败" value="failed" />
        </el-select>
      </div>

      <el-table :data="items" stripe v-loading="loading" style="width: 100%">
        <el-table-column prop="title" label="标题" min-width="180" show-overflow-tooltip />
        <el-table-column prop="datasource_name" label="数据源" width="130" />
        <el-table-column prop="database" label="数据库" width="120" />
        <el-table-column prop="sql_type" label="类型" width="80">
          <template #default="{ row }">
            <el-tag :type="row.sql_type === 'DDL' ? 'warning' : ''" size="small">{{ row.sql_type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" size="small">{{ row.status_display }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="submitter" label="提交人" width="90" />
        <el-table-column prop="reviewer" label="审核人" width="90" />
        <el-table-column prop="created_at" label="提交时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openDetail(row)">详情</el-button>
            <el-button v-if="row.status === 'pending'" link type="success" size="small"
              @click="handleApprove(row)">通过</el-button>
            <el-button v-if="row.status === 'pending'" link type="warning" size="small"
              @click="handleReject(row)">驳回</el-button>
            <el-button v-if="row.status === 'approved'" link type="danger" size="small"
              @click="handleExecute(row)" :loading="executingId === row.id">执行</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div style="display:flex; justify-content:flex-end; margin-top:16px;">
        <el-pagination v-model:current-page="page" :page-size="20" :total="total"
          layout="total, prev, pager, next" @current-change="fetchData" />
      </div>
    </div>

    <!-- 提交工单对话框 -->
    <el-dialog v-model="submitVisible" title="提交 SQL 工单" width="90%" style="max-width:700px;" top="5vh" append-to-body destroy-on-close>
      <el-form :model="form" label-width="100px">
        <el-form-item label="工单标题">
          <el-input v-model="form.title" placeholder="简要说明变更目的" />
        </el-form-item>
        <el-form-item label="数据源">
          <el-select v-model="form.datasource" placeholder="选择数据源" style="width:100%"
            @change="onDatasourceChange">
            <el-option v-for="ds in datasources" :key="ds.id" :label="ds.name" :value="ds.id">
              <span>{{ ds.name }}</span>
              <span style="color:var(--text-secondary); margin-left:8px; font-size:12px;">
                {{ ds.host }}:{{ ds.port }}
              </span>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="目标数据库">
          <el-select v-model="form.database" placeholder="选择数据库" style="width:100%"
            :loading="dbLoading" filterable>
            <el-option v-for="db in databases" :key="db" :label="db" :value="db" />
          </el-select>
        </el-form-item>
        <el-form-item label="SQL 类型">
          <el-radio-group v-model="form.sql_type">
            <el-radio value="DML">DML (INSERT/UPDATE/DELETE)</el-radio>
            <el-radio value="DDL">DDL (CREATE/ALTER/DROP)</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="SQL 内容">
          <div class="sql-editor-wrapper">
            <textarea v-model="form.sql_content" class="sql-editor"
              placeholder="输入 SQL 语句，多条语句以分号分隔..." rows="10"></textarea>
          </div>
        </el-form-item>
        <el-form-item label="提交人">
          <el-input v-model="form.submitter" style="width:200px" />
        </el-form-item>

        <!-- 预检查结果 -->
        <el-form-item label="预检查" v-if="checkResults.length">
          <div class="check-results">
            <div v-for="(r, i) in checkResults" :key="i"
              class="check-item" :class="r.level">
              <el-tag :type="checkTagType(r.level)" size="small" style="margin-right:8px;">
                {{ r.level === 'error' ? '错误' : r.level === 'warning' ? '警告' : '建议' }}
              </el-tag>
              <span class="check-rule">{{ r.rule_name }}</span>
              <span class="check-msg">{{ r.message }}</span>
            </div>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="handlePreCheck" :loading="checking">
          <el-icon><Select /></el-icon> 语法检查
        </el-button>
        <el-button @click="submitVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSubmit" :loading="submitting"
          :disabled="hasErrors">提交工单</el-button>
      </template>
    </el-dialog>

    <!-- 工单详情对话框 -->
    <el-dialog v-model="detailVisible" title="工单详情" width="90%" style="max-width:700px;" top="5vh" append-to-body destroy-on-close>
      <template v-if="detailOrder">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="标题" :span="2">{{ detailOrder.title }}</el-descriptions-item>
          <el-descriptions-item label="数据源">{{ detailOrder.datasource_name }}</el-descriptions-item>
          <el-descriptions-item label="数据库">{{ detailOrder.database }}</el-descriptions-item>
          <el-descriptions-item label="SQL 类型">{{ detailOrder.sql_type }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="statusTagType(detailOrder.status)" size="small">{{ detailOrder.status_display }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="提交人">{{ detailOrder.submitter }}</el-descriptions-item>
          <el-descriptions-item label="提交时间">{{ formatTime(detailOrder.created_at) }}</el-descriptions-item>
          <el-descriptions-item v-if="detailOrder.reviewer" label="审核人">{{ detailOrder.reviewer }}</el-descriptions-item>
          <el-descriptions-item v-if="detailOrder.reviewed_at" label="审核时间">{{ formatTime(detailOrder.reviewed_at) }}</el-descriptions-item>
          <el-descriptions-item v-if="detailOrder.review_comment" label="审核备注" :span="2">
            {{ detailOrder.review_comment }}
          </el-descriptions-item>
          <el-descriptions-item v-if="detailOrder.affected_rows !== null" label="影响行数">
            {{ detailOrder.affected_rows }}
          </el-descriptions-item>
          <el-descriptions-item v-if="detailOrder.duration_ms !== null" label="耗时">
            {{ detailOrder.duration_ms }}ms
          </el-descriptions-item>
        </el-descriptions>

        <div class="detail-section">
          <h4>SQL 内容</h4>
          <pre class="sql-display">{{ detailOrder.sql_content }}</pre>
        </div>

        <div class="detail-section" v-if="detailOrder.check_results && detailOrder.check_results.length">
          <h4>检查结果</h4>
          <div class="check-results">
            <div v-for="(r, i) in detailOrder.check_results" :key="i"
              class="check-item" :class="r.level">
              <el-tag :type="checkTagType(r.level)" size="small" style="margin-right:8px;">
                {{ r.level_display }}
              </el-tag>
              <span class="check-rule">{{ r.rule_name }}</span>
              <span class="check-msg">{{ r.message }}</span>
            </div>
          </div>
        </div>

        <div class="detail-section" v-if="detailOrder.execute_log">
          <h4>执行日志</h4>
          <pre class="sql-display execute-log">{{ detailOrder.execute_log }}</pre>
        </div>
      </template>
    </el-dialog>

    <!-- 审核备注对话框 -->
    <el-dialog v-model="reviewVisible" :title="reviewAction === 'approve' ? '审核通过' : '审核驳回'"
      width="90%" style="max-width:480px;" append-to-body destroy-on-close>
      <el-form label-width="80px">
        <el-form-item label="审核人">
          <el-input v-model="reviewForm.reviewer" style="width:200px" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="reviewForm.comment" type="textarea" :rows="3"
            :placeholder="reviewAction === 'approve' ? '审核通过备注（可选）' : '请填写驳回原因'" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="reviewVisible = false">取消</el-button>
        <el-button :type="reviewAction === 'approve' ? 'success' : 'warning'"
          @click="submitReview" :loading="reviewing">确认</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Search, Select } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getSqlOrders, createSqlOrder, approveSqlOrder,
  rejectSqlOrder, executeSqlOrder, checkSql, getSqlOrderDetail,
} from '@/api/modules/sqlaudit'
import { getDataSources, getDataSourceDatabases } from '@/api/modules/sqlaudit'

const items = ref([])
const loading = ref(false)
const search = ref('')
const statusFilter = ref('')
const page = ref(1)
const total = ref(0)
const executingId = ref(null)

// 数据源列表
const datasources = ref([])
const databases = ref([])
const dbLoading = ref(false)

// 提交对话框
const submitVisible = ref(false)
const submitting = ref(false)
const checking = ref(false)
const checkResults = ref([])
const form = ref({
  title: '', datasource: null, database: '', sql_type: 'DML',
  sql_content: '', submitter: 'admin',
})

// 详情对话框
const detailVisible = ref(false)
const detailOrder = ref(null)

// 审核对话框
const reviewVisible = ref(false)
const reviewAction = ref('')
const reviewOrderId = ref(null)
const reviewing = ref(false)
const reviewForm = ref({ reviewer: 'admin', comment: '' })

const hasErrors = computed(() =>
  checkResults.value.some(r => r.level === 'error')
)

const statusTagType = (s) => {
  const m = { pending: 'warning', approved: 'success', rejected: 'danger', executing: 'info', executed: 'success', failed: 'danger' }
  return m[s] || ''
}

const checkTagType = (l) => {
  const m = { error: 'danger', warning: 'warning', info: 'info' }
  return m[l] || 'info'
}

const formatTime = (t) => t ? new Date(t).toLocaleString('zh-CN') : ''

const fetchData = async () => {
  loading.value = true
  try {
    const params = { page: page.value }
    if (search.value) params.search = search.value
    if (statusFilter.value) params.status = statusFilter.value
    const res = await getSqlOrders(params)
    items.value = res.results || res
    total.value = res.count || items.value.length
  } catch (e) { console.error(e) }
  finally { loading.value = false }
}

const loadDatasources = async () => {
  try {
    const res = await getDataSources({ page_size: 100 })
    datasources.value = (res.results || res).filter(ds => ds.is_active)
  } catch (e) { console.error(e) }
}

const onDatasourceChange = async (dsId) => {
  if (!dsId) { databases.value = []; return }
  dbLoading.value = true
  try {
    const res = await getDataSourceDatabases(dsId)
    databases.value = res.databases || []
  } catch (e) {
    databases.value = []
    ElMessage.warning('获取数据库列表失败，请确认数据源可连通')
  } finally { dbLoading.value = false }
}

const openSubmitDialog = () => {
  form.value = {
    title: '', datasource: null, database: '', sql_type: 'DML',
    sql_content: '', submitter: 'admin',
  }
  checkResults.value = []
  loadDatasources()
  submitVisible.value = true
}

const handlePreCheck = async () => {
  if (!form.value.sql_content.trim()) {
    ElMessage.warning('请输入 SQL 内容')
    return
  }
  checking.value = true
  try {
    const res = await checkSql({
      sql_content: form.value.sql_content,
      sql_type: form.value.sql_type,
    })
    checkResults.value = res.results || []
  } catch (e) { console.error(e) }
  finally { checking.value = false }
}

const handleSubmit = async () => {
  if (!form.value.title || !form.value.datasource || !form.value.database || !form.value.sql_content.trim()) {
    ElMessage.warning('请填写完整工单信息')
    return
  }
  submitting.value = true
  try {
    await createSqlOrder(form.value)
    ElMessage.success('工单提交成功')
    submitVisible.value = false
    fetchData()
  } catch (e) { console.error(e) }
  finally { submitting.value = false }
}

const openDetail = async (row) => {
  try {
    detailOrder.value = await getSqlOrderDetail(row.id)
    detailVisible.value = true
  } catch (e) { console.error(e) }
}

const handleApprove = (row) => {
  reviewAction.value = 'approve'
  reviewOrderId.value = row.id
  reviewForm.value = { reviewer: 'admin', comment: '' }
  reviewVisible.value = true
}

const handleReject = (row) => {
  reviewAction.value = 'reject'
  reviewOrderId.value = row.id
  reviewForm.value = { reviewer: 'admin', comment: '' }
  reviewVisible.value = true
}

const submitReview = async () => {
  reviewing.value = true
  try {
    const fn = reviewAction.value === 'approve' ? approveSqlOrder : rejectSqlOrder
    await fn(reviewOrderId.value, reviewForm.value)
    ElMessage.success(reviewAction.value === 'approve' ? '审核通过' : '已驳回')
    reviewVisible.value = false
    fetchData()
  } catch (e) { console.error(e) }
  finally { reviewing.value = false }
}

const handleExecute = async (row) => {
  try {
    await ElMessageBox.confirm(
      `确定要执行工单「${row.title}」中的 SQL 吗？此操作不可撤销。`,
      '确认执行',
      { confirmButtonText: '执行', cancelButtonText: '取消', type: 'warning' },
    )
  } catch { return }

  executingId.value = row.id
  try {
    const res = await executeSqlOrder(row.id)
    if (res.status === 'executed') {
      ElMessage.success(`执行完成，影响 ${res.affected_rows} 行，耗时 ${res.duration_ms}ms`)
    } else {
      ElMessage.error(`执行失败: ${res.execute_log}`)
    }
    fetchData()
  } catch (e) { console.error(e) }
  finally { executingId.value = null }
}

onMounted(fetchData)
</script>
