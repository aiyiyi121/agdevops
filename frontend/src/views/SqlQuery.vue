<template>
  <div class="fade-in">
    <div class="page-header">
      <h2>SQL 查询</h2>
    </div>

    <!-- 查询面板 -->
    <div class="table-card" style="margin-bottom: 20px;">
      <div class="query-controls">
        <div class="query-selects">
          <el-select v-model="selectedDs" placeholder="选择数据源" style="width: 220px"
            @change="onDsChange" filterable>
            <el-option v-for="ds in datasources" :key="ds.id" :label="ds.name" :value="ds.id">
              <span>{{ ds.name }}</span>
              <span style="color:var(--text-secondary); margin-left:8px; font-size:12px;">
                {{ ds.host }}:{{ ds.port }}
              </span>
            </el-option>
          </el-select>
          <el-select v-model="selectedDb" placeholder="选择数据库" style="width: 200px"
            :loading="dbLoading" filterable>
            <el-option v-for="db in databases" :key="db" :label="db" :value="db" />
          </el-select>
          <el-input v-model="submitter" placeholder="操作人" style="width: 130px" />
        </div>
        <el-button type="primary" @click="handleQuery" :loading="querying"
          :disabled="!selectedDs || !selectedDb || !sqlContent.trim()">
          <el-icon><CaretRight /></el-icon> 执行查询
        </el-button>
      </div>

      <div class="sql-editor-wrapper" style="margin-top:12px;">
        <textarea v-model="sqlContent" class="sql-editor"
          placeholder="输入 SELECT / SHOW / DESC 查询语句..." rows="6"
          @keydown.ctrl.enter="handleQuery"></textarea>
      </div>
    </div>

    <!-- 查询结果 -->
    <div class="table-card" v-if="queryResult" style="margin-bottom:20px;">
      <div class="query-result-header">
        <h3 style="margin:0;">查询结果</h3>
        <div class="result-meta" v-if="queryResult">
          <el-tag type="info" size="small">{{ queryResult.count }} 行</el-tag>
          <el-tag type="success" size="small">{{ queryResult.duration_ms }}ms</el-tag>
        </div>
      </div>

      <div v-if="queryError" style="margin-top:12px;">
        <el-alert :title="queryError" type="error" show-icon :closable="false" />
      </div>

      <el-table v-else :data="queryResult.rows" stripe style="width: 100%; margin-top:12px;"
        max-height="400" size="small">
        <el-table-column v-for="col in queryResult.columns" :key="col"
          :prop="col" :label="col" min-width="120" show-overflow-tooltip />
      </el-table>
    </div>

    <!-- 查询历史 -->
    <div class="table-card">
      <div class="page-header" style="margin-bottom:0; padding:0;">
        <h3 style="margin:0;">查询历史</h3>
      </div>

      <el-table :data="history" stripe v-loading="historyLoading" style="width: 100%; margin-top:12px;" size="small">
        <el-table-column prop="datasource_name" label="数据源" width="130" />
        <el-table-column prop="database" label="数据库" width="120" />
        <el-table-column prop="sql_content" label="SQL" min-width="250" show-overflow-tooltip />
        <el-table-column prop="submitter" label="操作人" width="90" />
        <el-table-column prop="result_count" label="结果行数" width="100" />
        <el-table-column prop="duration_ms" label="耗时" width="90">
          <template #default="{ row }">{{ row.duration_ms }}ms</template>
        </el-table-column>
        <el-table-column prop="created_at" label="时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
      </el-table>

      <div style="display:flex; justify-content:flex-end; margin-top:16px;">
        <el-pagination v-model:current-page="historyPage" :page-size="20" :total="historyTotal"
          layout="total, prev, pager, next" @current-change="fetchHistory" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getDataSources, getDataSourceDatabases, submitQuery, getQueryOrders } from '@/api/modules/sqlaudit'

const datasources = ref([])
const databases = ref([])
const dbLoading = ref(false)

const selectedDs = ref(null)
const selectedDb = ref('')
const sqlContent = ref('')
const submitter = ref('admin')
const querying = ref(false)
const queryResult = ref(null)
const queryError = ref('')

const history = ref([])
const historyLoading = ref(false)
const historyPage = ref(1)
const historyTotal = ref(0)

const formatTime = (t) => t ? new Date(t).toLocaleString('zh-CN') : ''

const loadDatasources = async () => {
  try {
    const res = await getDataSources({ page_size: 100 })
    datasources.value = (res.results || res).filter(ds => ds.is_active)
  } catch (e) { console.error(e) }
}

const onDsChange = async (dsId) => {
  selectedDb.value = ''
  if (!dsId) { databases.value = []; return }
  dbLoading.value = true
  try {
    const res = await getDataSourceDatabases(dsId)
    databases.value = res.databases || []
  } catch (e) {
    databases.value = []
    ElMessage.warning('获取数据库列表失败')
  } finally { dbLoading.value = false }
}

const handleQuery = async () => {
  if (!sqlContent.value.trim()) return
  querying.value = true
  queryError.value = ''
  queryResult.value = null
  try {
    const res = await submitQuery({
      datasource: selectedDs.value,
      database: selectedDb.value,
      sql_content: sqlContent.value,
      submitter: submitter.value,
    })
    queryResult.value = {
      columns: res.columns,
      rows: res.rows,
      count: res.count,
      duration_ms: res.duration_ms,
    }
    fetchHistory()
  } catch (e) {
    queryError.value = e.response?.data?.error || '查询失败'
    // 即使失败也可能有 order 记录
    fetchHistory()
  } finally { querying.value = false }
}

const fetchHistory = async () => {
  historyLoading.value = true
  try {
    const res = await getQueryOrders({ page: historyPage.value })
    history.value = res.results || res
    historyTotal.value = res.count || history.value.length
  } catch (e) { console.error(e) }
  finally { historyLoading.value = false }
}

onMounted(() => {
  loadDatasources()
  fetchHistory()
})
</script>
