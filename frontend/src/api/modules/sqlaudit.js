import request from '../request'

// 数据源
export const getDataSources = (params) => request.get('/sqlaudit/datasources/', { params })
export const createDataSource = (data) => request.post('/sqlaudit/datasources/', data)
export const updateDataSource = (id, data) => request.put(`/sqlaudit/datasources/${id}/`, data)
export const deleteDataSource = (id) => request.delete(`/sqlaudit/datasources/${id}/`)
export const testDataSourceConnection = (id) => request.post(`/sqlaudit/datasources/${id}/test_connection/`)
export const getDataSourceDatabases = (id) => request.get(`/sqlaudit/datasources/${id}/databases/`)

// SQL 工单
export const getSqlOrders = (params) => request.get('/sqlaudit/orders/', { params })
export const createSqlOrder = (data) => request.post('/sqlaudit/orders/', data)
export const getSqlOrderDetail = (id) => request.get(`/sqlaudit/orders/${id}/`)
export const deleteSqlOrder = (id) => request.delete(`/sqlaudit/orders/${id}/`)
export const approveSqlOrder = (id, data) => request.post(`/sqlaudit/orders/${id}/approve/`, data)
export const rejectSqlOrder = (id, data) => request.post(`/sqlaudit/orders/${id}/reject/`, data)
export const executeSqlOrder = (id) => request.post(`/sqlaudit/orders/${id}/execute/`)

// SQL 检查
export const checkSql = (data) => request.post('/sqlaudit/check/', data)

// 查询工单
export const getQueryOrders = (params) => request.get('/sqlaudit/queries/', { params })
export const submitQuery = (data) => request.post('/sqlaudit/queries/', data)
