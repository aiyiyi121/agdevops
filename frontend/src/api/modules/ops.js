import request from '../request'

export const getDashboardStats = () => request.get('/dashboard/stats/')

export const getHosts = (params) => request.get('/hosts/', { params })
export const createHost = (data) => request.post('/hosts/', data)
export const updateHost = (id, data) => request.put(`/hosts/${id}/`, data)
export const deleteHost = (id) => request.delete(`/hosts/${id}/`)

export const getDeployments = (params) => request.get('/deployments/', { params })
export const createDeployment = (data) => request.post('/deployments/', data)
export const updateDeployment = (id, data) => request.put(`/deployments/${id}/`, data)
export const deleteDeployment = (id) => request.delete(`/deployments/${id}/`)

export const getAlerts = (params) => request.get('/alerts/', { params })
export const updateAlert = (id, data) => request.patch(`/alerts/${id}/`, data)
export const deleteAlert = (id) => request.delete(`/alerts/${id}/`)

export const getLogs = (params) => request.get('/logs/', { params })

export const getUsers = (params) => request.get('/users/', { params })

// Loki API
export const getLokiLabels = (params) => request.get('/loki/labels/', { params })
export const getLokiLabelValues = (name, params) => request.get(`/loki/label/${name}/values/`, { params })
export const queryLokiLogs = (params) => request.get('/loki/query_range/', { params })
export const getLokiSeries = (params) => request.get('/loki/series/', { params })
