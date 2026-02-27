<template>
  <div class="fade-in">
    <div class="page-header">
      <h2>告警中心</h2>
    </div>

    <div class="table-card">
      <div class="filter-bar">
        <el-input v-model="search" placeholder="搜索告警标题 / 来源" clearable style="width: 300px"
          :prefix-icon="Search" @input="fetchData" />
        <el-select v-model="levelFilter" placeholder="级别" clearable style="width: 120px" @change="fetchData">
          <el-option label="严重" value="critical" />
          <el-option label="警告" value="warning" />
          <el-option label="信息" value="info" />
        </el-select>
        <el-select v-model="ackFilter" placeholder="状态" clearable style="width: 120px" @change="fetchData">
          <el-option label="未确认" :value="false" />
          <el-option label="已确认" :value="true" />
        </el-select>
      </div>

      <el-table :data="alerts" stripe v-loading="loading" style="width: 100%">
        <el-table-column prop="title" label="告警标题" min-width="200" />
        <el-table-column prop="level" label="级别" width="90">
          <template #default="{ row }">
            <el-tag :type="levelType(row.level)" size="small">{{ row.level_display }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="source" label="来源" width="130" />
        <el-table-column prop="host_name" label="主机" width="140" />
        <el-table-column prop="is_acknowledged" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.is_acknowledged ? 'success' : 'danger'" size="small">
              {{ row.is_acknowledged ? '已确认' : '未确认' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button v-if="!row.is_acknowledged" link type="primary" size="small"
              @click="handleAck(row)">确认</el-button>
            <el-popconfirm title="确定删除？" @confirm="handleDelete(row.id)">
              <template #reference>
                <el-button link type="danger" size="small">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>

      <div style="display:flex; justify-content:flex-end; margin-top:16px;">
        <el-pagination v-model:current-page="page" :page-size="20" :total="total"
          layout="total, prev, pager, next" @current-change="fetchData" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { getAlerts, updateAlert, deleteAlert } from '@/api/modules/ops'

const alerts = ref([])
const loading = ref(false)
const search = ref('')
const levelFilter = ref('')
const ackFilter = ref('')
const page = ref(1)
const total = ref(0)

const levelType = (level) => {
  const map = { critical: 'danger', warning: 'warning', info: 'info' }
  return map[level] || 'info'
}
const formatTime = (t) => t ? new Date(t).toLocaleString('zh-CN') : ''

const fetchData = async () => {
  loading.value = true
  try {
    const params = { page: page.value }
    if (search.value) params.search = search.value
    if (levelFilter.value) params.level = levelFilter.value
    if (ackFilter.value !== '') params.is_acknowledged = ackFilter.value
    const res = await getAlerts(params)
    alerts.value = res.results || res
    total.value = res.count || alerts.value.length
  } catch (e) { console.error(e) }
  finally { loading.value = false }
}

const handleAck = async (row) => {
  try {
    await updateAlert(row.id, { is_acknowledged: true })
    ElMessage.success('已确认')
    fetchData()
  } catch (e) { console.error(e) }
}

const handleDelete = async (id) => {
  try { await deleteAlert(id); ElMessage.success('删除成功'); fetchData() }
  catch (e) { console.error(e) }
}

onMounted(fetchData)
</script>
