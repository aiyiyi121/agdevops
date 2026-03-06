<template>
  <div class="fade-in">
    <div class="page-header">
      <h2>主机管理</h2>
      <el-button type="primary" @click="openDialog()">
        <el-icon><Plus /></el-icon> 新增主机
      </el-button>
    </div>

    <div class="table-card">
      <div class="filter-bar">
        <el-input v-model="search" placeholder="搜索主机名 / IP" clearable style="width: 260px"
          :prefix-icon="Search" @input="fetchData" />
        <el-select v-model="statusFilter" placeholder="状态" clearable style="width: 120px" @change="fetchData">
          <el-option label="在线" value="online" />
          <el-option label="离线" value="offline" />
          <el-option label="告警" value="warning" />
        </el-select>
      </div>

      <el-table :data="hosts" stripe v-loading="loading" style="width: 100%">
        <el-table-column prop="hostname" label="主机名" min-width="140" />
        <el-table-column prop="ip_address" label="IP 地址" width="140" />
        <el-table-column prop="os_type" label="操作系统" width="120" />
        <el-table-column label="SSH" width="120">
          <template #default="{ row }">
            <span style="font-size:12px; color:var(--text-secondary);">{{ row.ssh_user }}@:{{ row.ssh_port }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="90">
          <template #default="{ row }">
            <span><span class="status-dot" :class="row.status"></span>{{ row.status_display }}</span>
          </template>
        </el-table-column>
        <el-table-column label="CPU" width="95">
          <template #default="{ row }">
            <el-progress :percentage="row.cpu_usage" :stroke-width="6" :color="progressColor(row.cpu_usage)" :show-text="false" />
            <span style="font-size:12px; color:var(--text-secondary);">{{ row.cpu_usage }}%</span>
          </template>
        </el-table-column>
        <el-table-column label="内存" width="95">
          <template #default="{ row }">
            <el-progress :percentage="row.memory_usage" :stroke-width="6" :color="progressColor(row.memory_usage)" :show-text="false" />
            <span style="font-size:12px; color:var(--text-secondary);">{{ row.memory_usage }}%</span>
          </template>
        </el-table-column>
        <el-table-column label="磁盘" width="95">
          <template #default="{ row }">
            <el-progress :percentage="row.disk_usage" :stroke-width="6" :color="progressColor(row.disk_usage)" :show-text="false" />
            <span style="font-size:12px; color:var(--text-secondary);">{{ row.disk_usage }}%</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="260" fixed="right">
          <template #default="{ row }">
            <el-button link type="success" size="small" @click="handleTestConnection(row)" :loading="row._testing">
              测试
            </el-button>
            <el-button link type="warning" size="small" @click="handleRefreshInfo(row)" :loading="row._refreshing">
              刷新
            </el-button>
            <el-button link type="primary" size="small" @click="openTerminal(row)">
              <el-icon><Monitor /></el-icon> 终端
            </el-button>
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
        <el-pagination
          v-model:current-page="page"
          :page-size="20"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="fetchData"
        />
      </div>
    </div>

    <!-- 新增/编辑对话框 -->
    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑主机' : '新增主机'" width="90%" style="max-width:560px;" top="5vh" append-to-body destroy-on-close>
      <el-form :model="form" label-width="90px">
        <el-form-item label="主机名">
          <el-input v-model="form.hostname" placeholder="例如 web-server-01" />
        </el-form-item>
        <el-form-item label="IP 地址">
          <el-input v-model="form.ip_address" placeholder="例如 192.168.1.10" />
        </el-form-item>
        <el-form-item label="操作系统">
          <el-input v-model="form.os_type" placeholder="例如 CentOS 7.9" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.status" style="width: 100%">
            <el-option label="在线" value="online" />
            <el-option label="离线" value="offline" />
            <el-option label="告警" value="warning" />
          </el-select>
        </el-form-item>

        <el-divider content-position="left">SSH 连接信息</el-divider>

        <el-form-item label="SSH 端口">
          <el-input-number v-model="form.ssh_port" :min="1" :max="65535" controls-position="right" style="width: 100%" />
        </el-form-item>
        <el-form-item label="SSH 用户">
          <el-input v-model="form.ssh_user" placeholder="root" />
        </el-form-item>
        <el-form-item label="SSH 密码">
          <el-input v-model="form.ssh_password" type="password" placeholder="输入 SSH 密码" show-password />
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
import { useRouter } from 'vue-router'
import { Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { getHosts, createHost, updateHost, deleteHost, testHostConnection, refreshHostInfo } from '@/api/modules/ops'

const router = useRouter()
const hosts = ref([])
const loading = ref(false)
const search = ref('')
const statusFilter = ref('')
const page = ref(1)
const total = ref(0)

const dialogVisible = ref(false)
const editingId = ref(null)
const saving = ref(false)
const defaultForm = {
  hostname: '', ip_address: '', os_type: 'Linux', status: 'online',
  ssh_port: 22, ssh_user: 'root', ssh_password: '',
}
const form = ref({ ...defaultForm })

const progressColor = (val) => {
  if (val >= 90) return '#ef4444'
  if (val >= 70) return '#f59e0b'
  return '#10b981'
}

const fetchData = async () => {
  loading.value = true
  try {
    const params = { page: page.value }
    if (search.value) params.search = search.value
    if (statusFilter.value) params.status = statusFilter.value
    const res = await getHosts(params)
    hosts.value = (res.results || res).map(h => ({ ...h, _testing: false, _refreshing: false }))
    total.value = res.count || hosts.value.length
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

const openDialog = (row) => {
  if (row) {
    editingId.value = row.id
    form.value = {
      hostname: row.hostname, ip_address: row.ip_address,
      os_type: row.os_type, status: row.status,
      ssh_port: row.ssh_port || 22, ssh_user: row.ssh_user || 'root',
      ssh_password: row.ssh_password || '',
    }
  } else {
    editingId.value = null
    form.value = { ...defaultForm }
  }
  dialogVisible.value = true
}

const handleSave = async () => {
  saving.value = true
  try {
    if (editingId.value) {
      await updateHost(editingId.value, form.value)
      ElMessage.success('更新成功')
    } else {
      await createHost(form.value)
      ElMessage.success('创建成功')
    }
    dialogVisible.value = false
    fetchData()
  } catch (e) {
    console.error(e)
  } finally {
    saving.value = false
  }
}

const handleDelete = async (id) => {
  try {
    await deleteHost(id)
    ElMessage.success('删除成功')
    fetchData()
  } catch (e) {
    console.error(e)
  }
}

const handleTestConnection = async (row) => {
  row._testing = true
  try {
    const res = await testHostConnection(row.id)
    if (res.success) {
      ElMessage.success(res.message)
    } else {
      ElMessage.error(res.message)
    }
  } catch (e) {
    ElMessage.error('测试连接失败')
  } finally {
    row._testing = false
  }
}

const handleRefreshInfo = async (row) => {
  row._refreshing = true
  try {
    const res = await refreshHostInfo(row.id)
    // 更新表格中的数据
    Object.assign(row, res, { _testing: false, _refreshing: false })
    ElMessage.success('主机信息已刷新')
  } catch (e) {
    ElMessage.error('刷新主机信息失败')
  } finally {
    row._refreshing = false
  }
}

const openTerminal = (row) => {
  router.push({ name: 'WebShell', params: { hostId: row.id } })
}

onMounted(fetchData)
</script>
