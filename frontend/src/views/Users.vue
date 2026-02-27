<template>
  <div class="fade-in">
    <div class="page-header">
      <h2>用户管理</h2>
      <el-button type="primary" @click="openDialog()">
        <el-icon><Plus /></el-icon> 新增用户
      </el-button>
    </div>

    <div class="table-card">
      <div class="filter-bar">
        <el-input v-model="search" placeholder="搜索用户名" clearable style="width: 260px"
          :prefix-icon="Search" @input="fetchData" />
      </div>

      <el-table :data="users" stripe v-loading="loading" style="width: 100%">
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="username" label="用户名" min-width="140" />
        <el-table-column prop="email" label="邮箱" min-width="200" />
        <el-table-column prop="is_active" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'danger'" size="small">
              {{ row.is_active ? '启用' : '禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="is_staff" label="角色" width="100">
          <template #default="{ row }">
            <el-tag :type="row.is_superuser ? 'danger' : row.is_staff ? 'warning' : ''" size="small">
              {{ row.is_superuser ? '超级管理员' : row.is_staff ? '管理员' : '普通用户' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="date_joined" label="注册时间" width="170">
          <template #default="{ row }">{{ formatTime(row.date_joined) }}</template>
        </el-table-column>
      </el-table>

      <div style="display:flex; justify-content:flex-end; margin-top:16px;">
        <el-pagination v-model:current-page="page" :page-size="20" :total="total"
          layout="total, prev, pager, next" @current-change="fetchData" />
      </div>
    </div>

    <el-dialog v-model="dialogVisible" title="新增用户" width="480px" destroy-on-close>
      <el-form :model="form" label-width="80px">
        <el-form-item label="用户名">
          <el-input v-model="form.username" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="form.email" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="dialogVisible = false">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { Search } from '@element-plus/icons-vue'
import { getUsers } from '@/api/modules/ops'

const users = ref([])
const loading = ref(false)
const search = ref('')
const page = ref(1)
const total = ref(0)

const dialogVisible = ref(false)
const form = ref({ username: '', email: '', password: '' })

const formatTime = (t) => t ? new Date(t).toLocaleString('zh-CN') : ''

const openDialog = () => {
  form.value = { username: '', email: '', password: '' }
  dialogVisible.value = true
}

const fetchData = async () => {
  loading.value = true
  try {
    const params = { page: page.value }
    if (search.value) params.search = search.value
    const res = await getUsers(params)
    users.value = res.results || res || []
    total.value = res.count || users.value.length
  } catch (e) {
    // 用户 API 暂未实现，使用空数据
    users.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

onMounted(fetchData)
</script>
