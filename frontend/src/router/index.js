import { createRouter, createWebHistory } from 'vue-router'
import { ElMessage } from 'element-plus'
import AppLayout from '@/layout/AppLayout.vue'
import { pinia } from '@/stores'
import { useAuthStore } from '@/stores/auth'

const TASK_SCHEDULES_VISIBLE = false
const observabilityBoardPermissions = ['ops.grafana.view']
const observabilityOverviewPermissions = [
  'ops.metric.query',
  'ops.metric.datasource.view',
  'ops.log.query',
  'ops.log.datasource.view',
  'ops.alert.view',
  'ops.alert.config.view',
  'ops.trace.view',
  'ops.trace.datasource.view',
  'ops.observability.link.view',
  'ops.grafana.view',
]

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { public: true, title: '登录' },
  },
  {
    path: '/403',
    name: 'Forbidden',
    component: () => import('@/views/Forbidden.vue'),
    meta: { public: true, title: '无权访问' },
  },
  {
    path: '/ai-agent-promo',
    name: 'AIAgentPromo',
    component: () => import('@/views/AIAgentPromo.vue'),
    meta: { public: true, title: 'AI Agent 产品介绍' },
  },
  {
    path: '/',
    component: AppLayout,
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/Dashboard.vue'),
        meta: { title: '运行概览', icon: 'Odometer', permission: 'ops.dashboard.view' },
      },
      {
        path: 'hosts',
        redirect: '/tasks/resources',
        meta: { hidden: true },
      },
      {
        path: 'hosts/assets',
        redirect: '/tasks/resources',
        meta: { hidden: true, title: '资源底座', icon: 'Monitor', anyPermissions: ['ops.task.resource.view', 'ops.task.resource.manage', 'ops.host.view', 'ops.host.manage', 'ops.host.terminal'] },
      },
      {
        path: 'hosts/schedules',
        redirect: TASK_SCHEDULES_VISIBLE ? '/tasks/schedules' : '/tasks/workbench',
        meta: { hidden: true, title: '定时任务', icon: 'Timer', anyPermissions: ['ops.host.schedule.view', 'ops.host.schedule.manage', 'ops.host.schedule.execute'] },
      },
      {
        path: 'hosts/tasks',
        redirect: '/tasks/workbench',
        meta: { hidden: true, title: '任务中心', icon: 'Operation', permission: 'ops.task.execute' },
      },
      {
        path: 'tasks',
        name: 'TaskCenter',
        component: () => import('@/views/TaskCenter.vue'),
        meta: {
          title: '任务中心',
          icon: 'Operation',
          anyPermissions: [
            'ops.task.execute',
            'ops.task.resource.view',
            'ops.task.resource.manage',
            'ops.host.execute',
            'ops.host.view',
            'ops.host.manage',
            'ops.host.terminal',
          ],
        },
      },
      {
        path: 'tasks/resources',
        name: 'TaskResources',
        component: () => import('@/views/TaskResources.vue'),
        meta: {
          title: '资源底座',
          icon: 'Monitor',
          anyPermissions: ['ops.task.resource.view', 'ops.task.resource.manage'],
        },
      },
      {
        path: 'tasks/workbench',
        name: 'TaskWorkbench',
        component: () => import('@/views/TaskWorkbench.vue'),
        meta: {
          title: '任务工作台',
          icon: 'Operation',
          anyPermissions: ['ops.task.execute', 'ops.host.execute'],
        },
      },
      {
        path: 'tasks/schedules',
        ...(TASK_SCHEDULES_VISIBLE
          ? { name: 'TaskSchedules', component: () => import('@/views/TaskSchedules.vue') }
          : { redirect: '/tasks/workbench' }),
        meta: {
          hidden: !TASK_SCHEDULES_VISIBLE,
          title: '计划任务',
          icon: 'Timer',
          anyPermissions: ['ops.host.schedule.view', 'ops.host.schedule.manage', 'ops.host.schedule.execute'],
        },
      },
      {
        path: 'deployments',
        redirect: '/workorders/releases',
        meta: { hidden: true, anyPermissions: ['ops.deployment.view', 'ops.deployment.manage', 'ops.deployment.approve'] },
      },
      {
        path: 'workorders',
        redirect: () => {
          const authStore = useAuthStore(pinia)
          if (authStore.hasAnyPermission(['ops.deployment.view', 'ops.deployment.manage', 'ops.deployment.approve'])) {
            return '/workorders/releases'
          }
          if (authStore.hasAnyPermission([
            'sqlaudit.order.view',
            'sqlaudit.order.submit',
            'sqlaudit.order.review',
            'sqlaudit.order.execute',
            'sqlaudit.datasource.view',
            'sqlaudit.query.view',
            'sqlaudit.query.execute',
          ])) {
            return '/workorders/sql'
          }
          if (authStore.hasAnyPermission(['ops.ticket.view', 'ops.ticket.manage', 'ops.ticket.approve'])) {
            return '/workorders/transactions'
          }
          return '/403'
        },
        meta: { hidden: true },
      },
      {
        path: 'workorders/releases',
        name: 'WorkOrderReleases',
        component: () => import('@/views/Deployments.vue'),
        meta: {
          title: '应用发布',
          icon: 'Promotion',
          anyPermissions: ['ops.deployment.view', 'ops.deployment.manage', 'ops.deployment.approve'],
        },
      },
      {
        path: 'workorders/approval-flows',
        name: 'WorkOrderApprovalFlows',
        component: () => import('@/views/Deployments.vue'),
        meta: {
          title: '审批流',
          icon: 'Checked',
          anyPermissions: ['ops.deployment.view', 'ops.deployment.manage', 'ops.deployment.approve'],
        },
      },
      {
        path: 'workorders/sql',
        name: 'WorkOrderSqlAudit',
        component: () => import('@/views/SqlAudit.vue'),
        meta: {
          title: 'SQL 审计',
          icon: 'DataAnalysis',
          defaultTab: 'orders',
          anyPermissions: [
            'sqlaudit.datasource.view',
            'sqlaudit.order.view',
            'sqlaudit.order.submit',
            'sqlaudit.order.review',
            'sqlaudit.order.execute',
            'sqlaudit.query.view',
            'sqlaudit.query.execute',
          ],
        },
      },
      {
        path: 'workorders/transactions',
        name: 'TransactionTickets',
        component: () => import('@/views/TransactionTickets.vue'),
        meta: {
          title: '事务工单',
          icon: 'Tickets',
          anyPermissions: ['ops.ticket.view', 'ops.ticket.manage', 'ops.ticket.approve'],
        },
      },
      {
        path: 'containers/k8s',
        name: 'ContainerManageK8s',
        component: () => import('@/views/K8sManage.vue'),
        meta: { title: 'K8s 集群', icon: 'Connection', permission: 'ops.k8s.view' },
      },
      {
        path: 'containers/docker',
        name: 'ContainerManageDocker',
        component: () => import('@/views/ContainerManage.vue'),
        meta: { title: 'Docker 环境', icon: 'Platform', permission: 'ops.docker.view' },
      },
      {
        path: 'logs',
        redirect: () => {
          const authStore = useAuthStore(pinia)
          return authStore.hasPermission('ops.log.query') ? '/logs/query' : '/logs/datasources'
        },
        meta: { hidden: true },
      },
      {
        path: 'logs/query',
        name: 'LogsQuery',
        component: () => import('@/views/LogsQuery.vue'),
        meta: { title: '日志中心', icon: 'Search', permission: 'ops.log.query' },
      },
      {
        path: 'logs/datasources',
        name: 'LogDataSources',
        component: () => import('@/views/LogDataSources.vue'),
        meta: { title: '日志数据源', icon: 'DataBoard', permission: 'ops.log.datasource.view' },
      },
      {
        path: 'alerts',
        name: 'Alerts',
        component: () => import('@/views/Alerts.vue'),
        meta: { title: '告警中心', icon: 'Bell', anyPermissions: ['ops.alert.view', 'ops.alert.config.view'] },
      },
      {
        path: 'observability',
        redirect: () => {
          const authStore = useAuthStore(pinia)
          if (authStore.hasAnyPermission(observabilityBoardPermissions)) return '/observability/boards'
          if (authStore.hasPermission('ops.metric.query')) return '/observability/metrics'
          if (authStore.hasPermission('ops.log.query')) return '/logs/query'
          if (authStore.hasPermission('ops.trace.view')) return '/observability/tracing'
          if (authStore.hasAnyPermission(['ops.metric.datasource.view', 'ops.log.datasource.view', 'ops.trace.datasource.view', 'ops.observability.link.view'])) return '/observability/datasources'
          return '/403'
        },
        meta: { hidden: true },
      },
      {
        path: 'observability/boards',
        redirect: () => {
          const authStore = useAuthStore(pinia)
          if (authStore.hasPermission('ops.grafana.view')) return '/observability/grafana'
          return '/403'
        },
        meta: { hidden: true, anyPermissions: observabilityBoardPermissions },
      },
      {
        path: 'observability/query',
        redirect: () => {
          const authStore = useAuthStore(pinia)
          if (authStore.hasPermission('ops.metric.query')) return '/observability/metrics'
          if (authStore.hasPermission('ops.log.query')) return '/logs/query'
          if (authStore.hasPermission('ops.trace.view')) return '/observability/tracing'
          return '/403'
        },
        meta: { hidden: true, anyPermissions: ['ops.metric.query', 'ops.log.query', 'ops.trace.view'] },
      },
      {
        path: 'observability/datasources',
        redirect: () => {
          const authStore = useAuthStore(pinia)
          if (authStore.hasPermission('ops.metric.datasource.view')) return { path: '/observability/metrics', query: { tab: 'datasources' } }
          if (authStore.hasPermission('ops.log.datasource.view')) return '/logs/datasources'
          if (authStore.hasPermission('ops.trace.datasource.view')) return '/observability/tracing/datasources'
          if (authStore.hasPermission('ops.observability.link.view')) return '/observability/datasource-links'
          return '/403'
        },
        meta: { hidden: true, anyPermissions: ['ops.metric.datasource.view', 'ops.log.datasource.view', 'ops.trace.datasource.view', 'ops.observability.link.view'] },
      },
      {
        path: 'observability/overview',
        name: 'ObservabilityOverview',
        component: () => import('@/views/ObservabilityOverview.vue'),
        meta: {
          title: '平台总览',
          icon: 'DataLine',
          anyPermissions: observabilityOverviewPermissions,
        },
      },
      {
        path: 'observability/metrics',
        name: 'MetricsQuery',
        component: () => import('@/views/MetricsQuery.vue'),
        meta: { title: '指标查询', icon: 'DataAnalysis', anyPermissions: ['ops.metric.query', 'ops.metric.datasource.view'] },
      },
      {
        path: 'observability/metrics/datasources',
        redirect: { path: '/observability/metrics', query: { tab: 'datasources' } },
        meta: { hidden: true, permission: 'ops.metric.datasource.view' },
      },
      {
        path: 'observability/grafana',
        name: 'GrafanaDashboard',
        component: () => import('@/views/GrafanaDashboard.vue'),
        meta: { title: '仪表盘', icon: 'Histogram', permission: 'ops.grafana.view' },
      },
      {
        path: 'observability/tracing',
        name: 'TraceObservability',
        component: () => import('@/views/TraceObservability.vue'),
        meta: { title: '链路追踪', icon: 'Connection', anyPermissions: ['ops.trace.view', 'ops.trace.datasource.view', 'ops.observability.link.view'] },
      },
      {
        path: 'observability/tracing/datasources',
        redirect: { path: '/observability/tracing', query: { tab: 'datasources' } },
        meta: { hidden: true, permission: 'ops.trace.datasource.view' },
      },
      {
        path: 'observability/tracing/topology',
        redirect: (to) => ({ path: '/observability/tracing', query: { ...to.query, topology: '1' } }),
        meta: { hidden: true, permission: 'ops.trace.view' },
      },
      {
        path: 'observability/datasource-links',
        name: 'ObservabilityDataSourceLinks',
        component: () => import('@/views/ObservabilityDataSourceLinks.vue'),
        meta: { title: '关联配置', icon: 'Share', permission: 'ops.observability.link.view' },
      },
      {
        path: 'events',
        redirect: '/events/wall',
        meta: { hidden: true, permission: 'eventwall.view' },
      },
      {
        path: 'events/wall',
        name: 'EventWall',
        component: () => import('@/views/EventWall.vue'),
        meta: { title: '事件中心', icon: 'Aim', permission: 'eventwall.view' },
      },
      {
        path: 'events/overview',
        redirect: '/events/wall',
        meta: { hidden: true, permission: 'eventwall.view' },
      },
      {
        path: 'events/wall-v2',
        redirect: '/events/wall',
        meta: { hidden: true, permission: 'eventwall.view' },
      },
      {
        path: 'events/sources',
        name: 'EventSources',
        component: () => import('@/views/EventSources.vue'),
        meta: { title: '事件源', icon: 'Share', permission: 'eventwall.source.view' },
      },
      {
        path: 'events/environments',
        name: 'EventEnvironments',
        component: () => import('@/views/EventEnvironments.vue'),
        meta: { title: '事件环境', icon: 'CollectionTag', permission: 'eventwall.environment.view' },
      },
      {
        path: 'events/audit',
        redirect: '/events/wall',
        meta: { hidden: true, permission: 'eventwall.view' },
      },
      {
        path: 'events/analysis',
        redirect: '/events/wall',
        meta: { hidden: true, permission: 'eventwall.view' },
      },
      {
        path: 'users',
        name: 'Users',
        component: () => import('@/views/Users.vue'),
        meta: {
          title: '用户管理',
          icon: 'User',
          anyPermissions: ['rbac.user.view', 'rbac.role.view', 'rbac.group.view', 'rbac.permission.view', 'rbac.audit.view'],
        },
      },
      {
        path: 'users/audit',
        name: 'OperationAudit',
        component: () => import('@/views/OperationAudit.vue'),
        meta: { title: '操作审计', icon: 'DocumentChecked', permission: 'rbac.audit.view' },
      },
      {
        path: 'users/modules',
        name: 'ModuleManage',
        component: () => import('@/views/ModuleManage.vue'),
        meta: { title: '模块管理', icon: 'Menu', permission: 'rbac.module.manage' },
      },
      {
        path: 'aiops/chat',
        name: 'AIOpsChat',
        component: () => import('@/views/AIOpsChatEntry.vue'),
        meta: {
          title: '智能助手',
          icon: 'Service',
          permission: 'aiops.chat.view',
        },
      },
      {
        path: 'aiops/knowledge',
        name: 'AIOpsKnowledgeGraph',
        component: () => import('@/views/AIOpsKnowledgeGraph.vue'),
        meta: {
          title: '知识图谱',
          icon: 'Share',
          permission: 'aiops.knowledge.view',
        },
      },
      {
        path: 'aiops/knowledge/config',
        name: 'AIOpsKnowledgeConfig',
        redirect: (to) => ({ path: '/aiops/knowledge', query: { ...to.query, tab: 'config' } }),
        meta: { hidden: true },
      },
      {
        path: 'aiops/config',
        name: 'AIOpsConfig',
        component: () => import('@/views/AIOpsConfig.vue'),
        meta: {
          title: '智能体配置',
          icon: 'ChatDotSquare',
          permission: 'aiops.config.view',
        },
      },
      {
        path: 'aiops/audit',
        name: 'AIOpsAudit',
        component: () => import('@/views/AIOpsAudit.vue'),
        meta: {
          title: '智能体审计',
          icon: 'Tickets',
          permission: 'aiops.audit.view',
        },
      },
      {
        path: 'sql',
        redirect: (to) => ({ path: '/workorders/sql', query: to.query }),
        meta: { hidden: true },
      },
      {
        path: 'sql/datasources',
        redirect: { path: '/workorders/sql', query: { tab: 'datasources' } },
        meta: { hidden: true },
      },
      {
        path: 'sql/orders',
        redirect: { path: '/workorders/sql', query: { tab: 'orders' } },
        meta: { hidden: true },
      },
      {
        path: 'sql/query',
        redirect: { path: '/workorders/sql', query: { tab: 'query' } },
        meta: { hidden: true },
      },
    ],
  },
  {
    path: '/webshell/:hostId',
    name: 'WebShell',
    component: () => import('@/views/WebShell.vue'),
    meta: { title: 'WebShell', permission: 'ops.host.terminal' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(to, from, savedPosition) {
    if (savedPosition) {
      return savedPosition
    }
    return { top: 0 }
  },
})

router.beforeEach(async (to) => {
  const authStore = useAuthStore(pinia)
  if (!authStore.initialized) {
    await authStore.bootstrap()
  }

  if (to.meta.public) {
    if (to.name === 'Login' && authStore.isAuthenticated) {
      return '/dashboard'
    }
    return true
  }

  if (!authStore.isAuthenticated) {
    return { name: 'Login', query: { redirect: to.fullPath } }
  }

  const allowed = to.meta.permission
    ? authStore.hasPermission(to.meta.permission)
    : authStore.hasAnyPermission(to.meta.anyPermissions || [])

  if (!allowed) {
    ElMessage.warning('你没有访问该页面的权限')
    return { name: 'Forbidden' }
  }

  return true
})

export default router


