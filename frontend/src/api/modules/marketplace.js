import request from '../request'

// 模板
export const getTemplates = () => request.get('/marketplace/templates/')

// 部署实例
export const getDeployments = () => request.get('/marketplace/deployments/')
export const getDeployment = (id) => request.get(`/marketplace/deployments/${id}/`)

// 发起部署
export const deployService = (data) => request.post('/marketplace/deploy/', data)

// 操作
export const stopService = (id) => request.post(`/marketplace/deployments/${id}/stop/`)
export const startService = (id) => request.post(`/marketplace/deployments/${id}/start/`)
export const removeService = (id) => request.post(`/marketplace/deployments/${id}/remove/`)
export const getServiceLogs = (id, tail = 100) => request.get(`/marketplace/deployments/${id}/logs/`, { params: { tail } })
