import axios from 'axios'
import { ElMessage } from 'element-plus'

const request = axios.create({
    baseURL: '/api',
    timeout: 15000,
})

// 响应拦截器
request.interceptors.response.use(
    (response) => response.data,
    (error) => {
        const msg = error.response?.data?.detail || error.message || '请求失败'
        ElMessage.error(msg)
        return Promise.reject(error)
    }
)

export default request
