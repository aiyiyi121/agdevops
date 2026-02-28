import { createRouter, createWebHistory } from 'vue-router'
import AppLayout from '@/layout/AppLayout.vue'

const routes = [
    {
        path: '/',
        component: AppLayout,
        redirect: '/dashboard',
        children: [
            {
                path: 'dashboard',
                name: 'Dashboard',
                component: () => import('@/views/Dashboard.vue'),
                meta: { title: '仪表盘', icon: 'Odometer' },
            },
            {
                path: 'hosts',
                name: 'Hosts',
                component: () => import('@/views/Hosts.vue'),
                meta: { title: '主机管理', icon: 'Monitor' },
            },
            {
                path: 'deployments',
                name: 'Deployments',
                component: () => import('@/views/Deployments.vue'),
                meta: { title: '部署管理', icon: 'Promotion' },
            },
            {
                path: 'logs',
                name: 'Logs',
                component: () => import('@/views/Logs.vue'),
                meta: { title: '日志中心', icon: 'Document' },
            },
            {
                path: 'alerts',
                name: 'Alerts',
                component: () => import('@/views/Alerts.vue'),
                meta: { title: '告警中心', icon: 'Bell' },
            },
            {
                path: 'users',
                name: 'Users',
                component: () => import('@/views/Users.vue'),
                meta: { title: '用户管理', icon: 'User' },
            },
            {
                path: 'sql/datasources',
                name: 'SqlDatasources',
                component: () => import('@/views/SqlDatasources.vue'),
                meta: { title: '数据源管理', icon: 'Coin', group: 'SQL 审计' },
            },
            {
                path: 'sql/orders',
                name: 'SqlOrders',
                component: () => import('@/views/SqlOrders.vue'),
                meta: { title: 'SQL 工单', icon: 'Tickets', group: 'SQL 审计' },
            },
            {
                path: 'sql/query',
                name: 'SqlQuery',
                component: () => import('@/views/SqlQuery.vue'),
                meta: { title: 'SQL 查询', icon: 'Search', group: 'SQL 审计' },
            },
        ],
    },
]

const router = createRouter({
    history: createWebHistory(),
    routes,
})

export default router
