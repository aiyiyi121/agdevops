<template>
  <div class="fade-in">
    <div class="page-header">
      <h2>部署管理</h2>
      <el-button type="primary" @click="openDialog()">
        <el-icon><Plus /></el-icon> 新建部署
      </el-button>
    </div>

    <div class="table-card">
      <div class="filter-bar">
        <el-input v-model="search" placeholder="搜索应用名 / 版本" clearable style="width: 260px"
          :prefix-icon="Search" @input="fetchData" />
        <el-select v-model="envFilter" placeholder="环境" clearable style="width: 120px" @change="fetchData">
          <el-option label="生产" value="production" />
          <el-option label="预发布" value="staging" />
          <el-option label="测试" value="testing" />
          <el-option label="开发" value="development" />
        </el-select>
        <el-select v-model="statusFilter" placeholder="状态" clearable style="width: 120px" @change="fetchData">
          <el-option label="成功" value="success" />
          <el-option label="失败" value="failed" />
          <el-option label="部署中" value="running" />
          <el-option label="待部署" value="pending" />
        </el-select>
      </div>

      <el-table :data="items" stripe v-loading="loading" style="width: 100%">
        <el-table-column prop="app_name" label="应用名称" min-width="140" />
        <el-table-column prop="version" label="版本" width="110" />
        <el-table-column prop="environment_display" label="环境" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="envTagType(row.environment)">{{ row.environment_display }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <span><span class="status-dot" :class="row.status"></span>{{ row.status_display }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="deployer" label="部署人" width="100" />
        <el-table-column prop="host_name" label="目标主机" width="140" />
        <el-table-column prop="deployed_at" label="部署时间" width="170">
          <template #default="{ row }">{{ formatTime(row.deployed_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openDialog(row)">编辑</el-button>
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

    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑部署' : '新建部署'" width="520px" destroy-on-close>
      <el-form :model="form" label-width="90px">
        <el-form-item label="应用名称">
          <el-input v-model="form.app_name" />
        </el-form-item>
        <el-form-item label="版本号">
          <el-input v-model="form.version" />
        </el-form-item>
        <el-form-item label="环境">
          <el-select v-model="form.environment" style="width:100%">
            <el-option label="生产" value="production" />
            <el-option label="预发布" value="staging" />
            <el-option label="测试" value="testing" />
            <el-option label="开发" value="development" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.status" style="width:100%">
            <el-option label="待部署" value="pending" />
            <el-option label="部署中" value="running" />
            <el-option label="成功" value="success" />
            <el-option label="失败" value="failed" />
            <el-option label="已回滚" value="rollback" />
          </el-select>
        </el-form-item>
        <el-form-item label="部署人">
          <el-input v-model="form.deployer" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSave" :loading="saving">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { getDeployments, createDeployment, updateDeployment, deleteDeployment } from '@/api/modules/ops'

const items = ref([])
const loading = ref(false)
const search = ref('')
const envFilter = ref('')
const statusFilter = ref('')
const page = ref(1)
const total = ref(0)

const dialogVisible = ref(false)
const editingId = ref(null)
const saving = ref(false)
const form = ref({
  app_name: '', version: '', environment: 'testing',
  status: 'pending', deployer: 'admin', description: '',
})

const envTagType = (env) => {
  const map = { production: 'danger', staging: 'warning', testing: '', development: 'info' }
  return map[env] || ''
}

const formatTime = (t) => t ? new Date(t).toLocaleString('zh-CN') : ''

const fetchData = async () => {
  loading.value = true
  try {
    const params = { page: page.value }
    if (search.value) params.search = search.value
    if (envFilter.value) params.environment = envFilter.value
    if (statusFilter.value) params.status = statusFilter.value
    const res = await getDeployments(params)
    items.value = res.results || res
    total.value = res.count || items.value.length
  } catch (e) { console.error(e) }
  finally { loading.value = false }
}

const openDialog = (row) => {
  if (row) {
    editingId.value = row.id
    form.value = { ...row }
  } else {
    editingId.value = null
    form.value = { app_name: '', version: '', environment: 'testing', status: 'pending', deployer: 'admin', description: '' }
  }
  dialogVisible.value = true
}

const handleSave = async () => {
  saving.value = true
  try {
    if (editingId.value) {
      await updateDeployment(editingId.value, form.value)
      ElMessage.success('更新成功')
    } else {
      await createDeployment(form.value)
      ElMessage.success('创建成功')
    }
    dialogVisible.value = false
    fetchData()
  } catch (e) { console.error(e) }
  finally { saving.value = false }
}

const handleDelete = async (id) => {
  try { await deleteDeployment(id); ElMessage.success('删除成功'); fetchData() }
  catch (e) { console.error(e) }
}

onMounted(fetchData)
</script>
