from collections import Counter, defaultdict
from datetime import timedelta

from django.db.models import Count, Max, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from rbac.permissions import RBACPermissionMixin

from .models import EventEnvironment, EventRecord, EventSource
from .serializers import EventEnvironmentSerializer, EventRecordSerializer, EventSourceIngestSerializer, EventSourceSerializer
from .services import build_resource, record_event, resolve_event_environment


DEMO_WINDOW_MINUTES = 7 * 24 * 60 - 1

EVENT_CATEGORY_DEFINITIONS = [
    {
        'key': 'application_release',
        'label': '应用发布',
        'description': '应用发布、回滚、启停、下线和流水线发布类事件。',
        'required_fields': ['event_id', 'event_category', 'title', 'environment', 'application', 'result'],
        'recommended_fields': ['version', 'release_name', 'pipeline_url', 'rollback_source', 'approval_id'],
    },
    {
        'key': 'db_change',
        'label': 'DB变更',
        'description': 'SQL 上线、数据库结构变更、数据修复和执行结果类事件。',
        'required_fields': ['event_id', 'event_category', 'title', 'environment', 'result'],
        'recommended_fields': ['database', 'sql_type', 'affected_rows', 'duration_ms', 'datasource'],
    },
    {
        'key': 'config_change',
        'label': '配置变更',
        'description': '配置发布、参数调整、网络策略、域名路由和中间件配置类事件。',
        'required_fields': ['event_id', 'event_category', 'title', 'environment', 'result'],
        'recommended_fields': ['config_key', 'change_window', 'before', 'after', 'approval_id'],
    },
    {
        'key': 'ops_transaction',
        'label': '运维事务',
        'description': '权限开通、网络配置、机器申请释放和通用运维处理类事件。',
        'required_fields': ['event_id', 'event_category', 'title', 'environment', 'system_name', 'result'],
        'recommended_fields': ['ticket_type', 'owner', 'applicant', 'resource_type', 'resource_id'],
    },
    {
        'key': 'task_center',
        'label': '任务调度',
        'description': '平台内主机任务、定时编排、批量执行，以及外部自动化任务平台推送的执行类事件。',
        'required_fields': ['event_id', 'event_category', 'title', 'environment', 'result'],
        'recommended_fields': ['task_type', 'task_id', 'target', 'executor', 'duration_ms', 'schedule_id'],
    },
]
EVENT_CATEGORY_MAP = {item['key']: item for item in EVENT_CATEGORY_DEFINITIONS}
EVENT_CATEGORY_ALIASES = {
    'release': 'application_release',
    'deployment': 'application_release',
    'deployment_approval_flow': 'application_release',
    'deploy': 'application_release',
    'deploy_finish': 'application_release',
    'service_deployment': 'application_release',
    'rollback': 'application_release',
    'pipeline': 'application_release',
    'build': 'application_release',
    'jenkins_build': 'application_release',
    'argocd_app': 'application_release',
    'argocd_application': 'application_release',
    'app_release': 'application_release',
    'application': 'application_release',
    'sql': 'db_change',
    'sql_order': 'db_change',
    'database': 'db_change',
    'db': 'db_change',
    'config': 'config_change',
    'configuration': 'config_change',
    'ops': 'ops_transaction',
    'transaction': 'ops_transaction',
    'workorder': 'ops_transaction',
    'task': 'task_center',
    'tasks': 'task_center',
    'task_center': 'task_center',
    'taskcenter': 'task_center',
    'host_task': 'task_center',
    'host_task_batch': 'task_center',
    'host_task_schedule': 'task_center',
    'automation_task': 'task_center',
    'scheduled_task': 'task_center',
}

DEFAULT_EVENT_SOURCES = [
    {
        'code': 'builtin-workorder',
        'name': '工单系统',
        'source_kind': EventSource.KIND_BUILTIN,
        'source_type': EventSource.TYPE_BUILTIN_WORKORDER,
        'description': '沉淀应用发布、SQL 工单、事务工单和审批流结果，为故障窗口提供变更线索。',
        'enabled': True,
        'status': EventSource.STATUS_HEALTHY,
        'auth_type': EventSource.AUTH_NONE,
        'field_mapping': {'time': 'occurred_at', 'title': 'title', 'status': 'result', 'operator': 'actor_username'},
        'config': {
            'resource_types': ['deployment', 'sql_order', 'transaction_ticket', 'deployment_approval_flow'],
            'supported_event_categories': ['application_release', 'db_change', 'config_change', 'ops_transaction', 'task_center'],
        },
    },
    {
        'code': 'builtin-task-center',
        'name': '任务中心',
        'source_kind': EventSource.KIND_BUILTIN,
        'source_type': EventSource.TYPE_BUILTIN_TASK,
        'description': '沉淀主机任务、定时编排、批量执行、重跑和终止结果，为故障分析补充自动化执行上下文。',
        'enabled': True,
        'status': EventSource.STATUS_HEALTHY,
        'auth_type': EventSource.AUTH_NONE,
        'field_mapping': {'time': 'occurred_at', 'target': 'resource_name', 'status': 'result'},
        'config': {'resource_types': ['host_task', 'host_task_batch', 'host_task_schedule'], 'default_event_category': 'task_center'},
    },
    {'code': 'jira', 'name': 'Jira', 'source_kind': EventSource.KIND_EXTERNAL, 'source_type': EventSource.TYPE_JIRA, 'description': '接入 Jira issue 创建、流转、发布关联和故障工单事件。', 'enabled': False, 'status': EventSource.STATUS_NOT_CONFIGURED, 'auth_type': EventSource.AUTH_WEBHOOK, 'field_mapping': {'issue.key': 'resource_id', 'issue.fields.summary': 'title', 'user.name': 'actor'}, 'config': {'default_event_category': 'ops_transaction'}},
    {'code': 'jenkins', 'name': 'Jenkins', 'source_kind': EventSource.KIND_EXTERNAL, 'source_type': EventSource.TYPE_JENKINS, 'description': '接入 Jenkins 构建开始、成功、失败、回滚和部署流水线事件。', 'enabled': False, 'status': EventSource.STATUS_NOT_CONFIGURED, 'auth_type': EventSource.AUTH_WEBHOOK, 'field_mapping': {'job_name': 'application', 'build_number': 'resource_id', 'status': 'result'}, 'config': {'default_event_category': 'application_release'}},
    {'code': 'argocd', 'name': 'ArgoCD', 'source_kind': EventSource.KIND_EXTERNAL, 'source_type': EventSource.TYPE_ARGOCD, 'description': '接入 ArgoCD 应用同步、健康状态、回滚和 GitOps 发布事件。', 'enabled': False, 'status': EventSource.STATUS_NOT_CONFIGURED, 'auth_type': EventSource.AUTH_WEBHOOK, 'field_mapping': {'app.metadata.name': 'application', 'app.status.health.status': 'severity'}, 'config': {'default_event_category': 'application_release'}},
    {'code': 'gitlab', 'name': 'GitLab', 'source_kind': EventSource.KIND_EXTERNAL, 'source_type': EventSource.TYPE_GITLAB, 'description': '接入 GitLab push、merge request、tag、pipeline 和 deployment 事件。', 'enabled': False, 'status': EventSource.STATUS_NOT_CONFIGURED, 'auth_type': EventSource.AUTH_WEBHOOK, 'field_mapping': {'project.name': 'application', 'user_username': 'actor', 'object_kind': 'event_type'}, 'config': {'default_event_category': 'config_change'}},
    {'code': 'custom', 'name': '自定义事件源', 'source_kind': EventSource.KIND_EXTERNAL, 'source_type': EventSource.TYPE_CUSTOM, 'description': '为内部自研系统提供统一 webhook 规范，写入事件墙后可参与故障分析。', 'enabled': False, 'status': EventSource.STATUS_NOT_CONFIGURED, 'auth_type': EventSource.AUTH_WEBHOOK, 'field_mapping': {'event_id': 'event_id', 'event_category': 'event_category', 'occurred_at': 'occurred_at', 'title': 'title'}},
]

BUILTIN_RESOURCE_TYPES = {
    EventSource.TYPE_BUILTIN_WORKORDER: ['deployment', 'sql_order', 'transaction_ticket', 'deployment_approval_flow'],
    EventSource.TYPE_BUILTIN_TASK: ['host_task', 'host_task_batch', 'host_task_schedule'],
}

LEGACY_EVENT_SOURCE_CODES = {'builtin-k8s'}
WALL_BUILTIN_RESOURCE_TYPES = {
    resource_type
    for resource_types in BUILTIN_RESOURCE_TYPES.values()
    for resource_type in resource_types
}
HOURLY_DEMO_ENVIRONMENT = '电商测试环境-k3s'
HOURLY_DEMO_SYSTEM = '电商'
HOURLY_DEMO_CATEGORIES = ('db_change', 'config_change', 'ops_transaction', 'task_center')


def _is_application_release_category(value):
    return _normalize_event_category(value) == 'application_release'


def _application_for_event_category(category_key, value):
    return value if _is_application_release_category(category_key) else ''

HOURLY_DEMO_EVENT_TEMPLATES = {
    'db_change': [
        {
            'module': 'sqlaudit',
            'action': 'execute',
            'title': 'order_test.orders 表索引变更执行完成',
            'summary': '电商测试环境 order_test.orders 表完成索引调整，影响行数符合预期。',
            'result': EventRecord.RESULT_SUCCESS,
            'severity': EventRecord.SEVERITY_INFO,
            'actor_username': 'dba.bot',
            'actor_display': 'DBA Bot',
            'resource_type': 'sql_order',
            'resource_name': '订单库 orders 表索引变更',
            'application': '',
            'metadata': {'database': 'order_test', 'table': 'orders', 'sql_type': 'alter_index', 'affected_rows': 0, 'duration_ms': 1460},
        },
        {
            'module': 'sqlaudit',
            'action': 'execute',
            'title': 'member_test.member_profile 表数据修复待复核',
            'summary': 'member_test.member_profile 表数据修复脚本执行完成，存在少量待 DBA 复核记录。',
            'result': EventRecord.RESULT_PARTIAL,
            'severity': EventRecord.SEVERITY_WARNING,
            'actor_username': 'audit.bot',
            'actor_display': 'SQL Audit Bot',
            'resource_type': 'sql_order',
            'resource_name': '会员库 member_profile 表数据修复',
            'application': '',
            'metadata': {'database': 'member_test', 'table': 'member_profile', 'sql_type': 'data_fix', 'affected_rows': 37, 'duration_ms': 5280},
        },
    ],
    'config_change': [
        {
            'module': 'ops',
            'action': 'config_change',
            'title': 'gateway.gray.weight 灰度权重配置更新',
            'summary': '电商测试环境网关灰度权重 gateway.gray.weight 从 10 调整为 20，新的路由权重进入观测窗口。',
            'result': EventRecord.RESULT_SUCCESS,
            'severity': EventRecord.SEVERITY_INFO,
            'actor_username': 'release.bot',
            'actor_display': 'Release Bot',
            'resource_type': 'transaction_ticket',
            'resource_name': 'gateway.gray.weight',
            'application': '',
            'metadata': {'ticket_type': 'change', 'config_key': 'gateway.gray.weight', 'before': '10', 'after': '20'},
        },
        {
            'module': 'ops',
            'action': 'config_change',
            'title': 'product.cache.ttl 缓存 TTL 配置调整',
            'summary': '商品缓存配置 product.cache.ttl 从 600s 调整为 300s，用于验证活动页刷新策略。',
            'result': EventRecord.RESULT_SUCCESS,
            'severity': EventRecord.SEVERITY_WARNING,
            'actor_username': 'config.bot',
            'actor_display': 'Config Bot',
            'resource_type': 'transaction_ticket',
            'resource_name': 'product.cache.ttl',
            'application': '',
            'metadata': {'ticket_type': 'change', 'config_key': 'product.cache.ttl', 'before': '600s', 'after': '300s'},
        },
    ],
    'ops_transaction': [
        {
            'module': 'ops',
            'action': 'ticket_finish',
            'title': '测试账号权限开通完成',
            'summary': '电商测试环境临时排障账号权限已开通，过期时间已同步到权限中心。',
            'result': EventRecord.RESULT_SUCCESS,
            'severity': EventRecord.SEVERITY_INFO,
            'actor_username': 'ops.bot',
            'actor_display': 'Ops Bot',
            'resource_type': 'transaction_ticket',
            'resource_name': '临时权限开通',
            'application': '',
            'metadata': {'ticket_type': 'access_change', 'permission_scope': 'ecommerce-test', 'ttl_hours': 4},
        },
        {
            'module': 'ops',
            'action': 'ticket_pending',
            'title': '网络白名单调整待确认',
            'summary': '电商测试环境联调白名单调整已提交，等待网络策略生效确认。',
            'result': EventRecord.RESULT_PENDING,
            'severity': EventRecord.SEVERITY_WARNING,
            'actor_username': 'netops.bot',
            'actor_display': 'NetOps Bot',
            'resource_type': 'transaction_ticket',
            'resource_name': '联调白名单调整',
            'application': '',
            'metadata': {'ticket_type': 'network_change', 'cidr': '10.42.18.0/24', 'target': 'gateway-service'},
        },
    ],
    'task_center': [
        {
            'module': 'ops',
            'action': 'run_task',
            'title': '节点健康巡检完成',
            'summary': '电商测试环境节点健康巡检执行完成，发现 1 台节点负载偏高。',
            'result': EventRecord.RESULT_PARTIAL,
            'severity': EventRecord.SEVERITY_WARNING,
            'actor_username': 'task.bot',
            'actor_display': 'Task Bot',
            'resource_type': 'host_task',
            'resource_name': '节点健康巡检',
            'application': '',
            'metadata': {'task_type': 'health_check', 'target_count': 12, 'success_count': 11, 'failed_count': 1},
        },
        {
            'module': 'ops',
            'action': 'run_schedule',
            'title': '日志采集任务执行成功',
            'summary': '电商测试环境日志采集 Agent 状态检查任务执行成功。',
            'result': EventRecord.RESULT_SUCCESS,
            'severity': EventRecord.SEVERITY_INFO,
            'actor_username': 'task.bot',
            'actor_display': 'Task Bot',
            'resource_type': 'host_task_schedule',
            'resource_name': '日志采集 Agent 检查',
            'application': '',
            'metadata': {'task_type': 'agent_check', 'target_count': 12, 'success_count': 12, 'duration_ms': 3200},
        },
    ],
}

INGEST_SPEC = {
    'method': 'POST',
    'auth': 'Authorization: Bearer <token> 或 X-Event-Token: <token>',
    'content_type': 'application/json',
    'endpoint_template': '/api/event-sources/{type}/ingest/',
    'required_fields': ['title', 'event_category'],
    'recommended_fields': ['event_id', 'occurred_at', 'summary', 'event_type', 'action', 'result', 'severity', 'actor', 'system_name', 'environment', 'application', 'resource_type', 'resource_id', 'resource_name', 'correlation_id', 'tags', 'related_resources', 'changes', 'metadata'],
    'environment_rules': [
        'environment 对应事件中心的环境标识或环境别名，建议直接使用事件环境中维护的环境标识。',
        '外部事件推送时会按事件环境配置校验 environment，命中后统一归集到该事件环境。',
        '如果未命中已启用的事件环境，事件会被拒绝；请先在事件环境中新增标识或别名，或调整事件源的环境标识。',
        '平台内置工单系统和任务中心事件未命中时会进入事件环境页的未映射环境提示条，可点击后保存为新的事件环境。',
    ],
    'event_categories': EVENT_CATEGORY_DEFINITIONS,
    'idempotency': '同一事件源下 event_id 会作为幂等键，重复推送不会生成第二条事件。',
    'scope': '平台内置事件源只接收工单系统和任务中心；外部系统可通过 Webhook 推送 application_release、db_change、config_change、ops_transaction、task_center 事件；平台配置、资源管理、告警配置等内部操作请查看操作审计。',
    'result_values': [choice[0] for choice in EventRecord.RESULT_CHOICES],
    'severity_values': [choice[0] for choice in EventRecord.SEVERITY_CHOICES],
    'example': {
        'event_id': 'deploy-20260506-001',
        'event_category': 'application_release',
        'occurred_at': '2026-05-06T10:15:00+08:00',
        'title': 'payment-api 发布失败',
        'summary': 'Jenkins 构建 #184 发布到电商生产环境失败',
        'event_type': 'deployment',
        'action': 'deploy',
        'result': 'failed',
        'severity': 'danger',
        'actor': 'jenkins',
        'system_name': '交易',
        'environment': 'ecommerce-prod',
        'application': 'payment-api',
        'resource_type': 'jenkins_build',
        'resource_id': 'payment-api#184',
        'resource_name': 'payment-api #184',
        'correlation_id': 'payment-api:20260506',
        'tags': ['change', 'ci'],
        'metadata': {'job_url': 'https://jenkins.example/job/payment-api/184/'},
    },
}


def _ensure_default_event_sources():
    EventSource.objects.filter(code__in=LEGACY_EVENT_SOURCE_CODES).update(
        enabled=False,
        status=EventSource.STATUS_DISABLED,
        last_error='事件墙已收敛为故障分析视图，平台内置事件仅保留工单系统和任务中心。',
    )
    has_active_sources = EventSource.objects.exclude(code__in=LEGACY_EVENT_SOURCE_CODES).exists()
    for item in DEFAULT_EVENT_SOURCES:
        should_create = item['source_kind'] == EventSource.KIND_BUILTIN or not has_active_sources
        if should_create:
            source, created = EventSource.objects.get_or_create(code=item['code'], defaults={key: value for key, value in item.items() if key != 'code'})
        else:
            try:
                source = EventSource.objects.get(code=item['code'])
                created = False
            except EventSource.DoesNotExist:
                continue
        if created:
            continue
        update_fields = []
        default_update_keys = ('name', 'source_kind', 'source_type', 'description', 'auth_type', 'field_mapping', 'config')
        update_keys = default_update_keys if item['source_kind'] == EventSource.KIND_BUILTIN else ('source_kind', 'source_type', 'auth_type')
        for key in update_keys:
            if key in item and getattr(source, key) != item[key]:
                setattr(source, key, item[key])
                update_fields.append(key)
        if source.source_kind == EventSource.KIND_BUILTIN:
            for key in ('enabled', 'status'):
                if getattr(source, key) != item[key]:
                    setattr(source, key, item[key])
                    update_fields.append(key)
        if update_fields:
            update_fields.append('updated_at')
            source.save(update_fields=update_fields)


def _extract_event_source_token(request):
    auth = request.META.get('HTTP_AUTHORIZATION', '')
    if auth.lower().startswith('bearer '):
        return auth.split(' ', 1)[1].strip()
    return request.META.get('HTTP_X_EVENT_TOKEN', '').strip()


def _safe_get(payload, path, default=''):
    current = payload
    for part in str(path or '').split('.'):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return default
    return current if current is not None else default


def _normalize_service_name(value, metadata=None):
    metadata = metadata or {}
    service = str(metadata.get('service') or metadata.get('service_name') or '').strip()
    if service:
        return service
    name = str(value or '').strip()
    if name.endswith('-release'):
        return name[:-8]
    return name


def _normalize_provider_payload(source, payload):
    if source.source_type == EventSource.TYPE_JIRA:
        issue = payload.get('issue') or {}
        fields = issue.get('fields') or {}
        return {'event_id': payload.get('webhookEvent') or issue.get('id') or issue.get('key'), 'title': fields.get('summary') or f"Jira {issue.get('key', '')}".strip(), 'summary': payload.get('webhookEvent') or 'Jira 事件', 'event_type': 'jira_issue', 'action': payload.get('webhookEvent') or 'issue_event', 'result': EventRecord.RESULT_SUCCESS, 'actor': _safe_get(payload, 'user.name') or _safe_get(payload, 'user.displayName'), 'resource_type': 'jira_issue', 'resource_id': issue.get('key') or issue.get('id') or '', 'resource_name': fields.get('summary') or issue.get('key') or '', 'metadata': payload}
    if source.source_type == EventSource.TYPE_GITLAB:
        return {'event_id': payload.get('checkout_sha') or payload.get('object_kind') or payload.get('event_name'), 'title': payload.get('object_kind') or payload.get('event_name') or 'GitLab 事件', 'summary': payload.get('message') or payload.get('ref') or '', 'event_type': payload.get('object_kind') or 'gitlab', 'action': payload.get('event_name') or payload.get('object_kind') or 'gitlab_event', 'result': EventRecord.RESULT_SUCCESS, 'actor': payload.get('user_username') or payload.get('user_name') or '', 'environment': payload.get('environment') or '', 'application': _safe_get(payload, 'project.name'), 'resource_type': 'gitlab_project', 'resource_id': _safe_get(payload, 'project.id') or '', 'resource_name': _safe_get(payload, 'project.path_with_namespace') or _safe_get(payload, 'project.name'), 'metadata': payload}
    if source.source_type == EventSource.TYPE_JENKINS:
        status_value = str(payload.get('status') or _safe_get(payload, 'build.status') or '').lower()
        result = EventRecord.RESULT_FAILED if status_value in {'failed', 'failure', 'aborted'} else EventRecord.RESULT_SUCCESS
        job_name = payload.get('job_name') or payload.get('name') or _safe_get(payload, 'build.full_url')
        build_number = payload.get('build_number') or _safe_get(payload, 'build.number')
        application = _normalize_service_name(payload.get('application') or job_name or '', payload)
        environment = payload.get('environment') or _safe_get(payload, 'build.environment') or ''
        system_name = payload.get('system_name') or payload.get('business_line') or payload.get('team') or ''
        return {'event_id': f'{job_name}#{build_number}' if job_name and build_number else '', 'title': f'Jenkins {job_name or "构建事件"}', 'summary': payload.get('message') or status_value or 'Jenkins 构建事件', 'event_type': 'jenkins_build', 'action': payload.get('phase') or 'build', 'result': result, 'severity': EventRecord.SEVERITY_DANGER if result == EventRecord.RESULT_FAILED else EventRecord.SEVERITY_INFO, 'actor': payload.get('user') or 'jenkins', 'system_name': system_name, 'environment': environment, 'application': application, 'resource_type': 'jenkins_build', 'resource_id': str(build_number or ''), 'resource_name': str(job_name or ''), 'metadata': payload}
    if source.source_type == EventSource.TYPE_ARGOCD:
        app = payload.get('app') or payload.get('application') or {}
        app_name = _safe_get(app, 'metadata.name') or payload.get('app_name') or payload.get('application')
        health = str(_safe_get(app, 'status.health.status') or payload.get('health') or '').lower()
        result = EventRecord.RESULT_FAILED if health in {'degraded', 'missing', 'unknown'} else EventRecord.RESULT_SUCCESS
        return {'event_id': payload.get('event_id') or app_name, 'title': payload.get('title') or f'ArgoCD {app_name or "应用同步"}', 'summary': payload.get('summary') or _safe_get(app, 'status.sync.status') or 'ArgoCD 应用事件', 'event_type': 'argocd_app', 'action': payload.get('action') or 'sync', 'result': result, 'severity': EventRecord.SEVERITY_DANGER if result == EventRecord.RESULT_FAILED else EventRecord.SEVERITY_INFO, 'actor': payload.get('actor') or 'argocd', 'application': app_name or '', 'resource_type': 'argocd_application', 'resource_id': app_name or '', 'resource_name': app_name or '', 'metadata': payload}
    return payload


def _event_source_counts(days=7):
    start = timezone.now() - timedelta(days=days)
    result = defaultdict(int)
    builtin_code_map = {item['source_type']: item['code'] for item in DEFAULT_EVENT_SOURCES if item['source_kind'] == EventSource.KIND_BUILTIN}
    for item in EventRecord.objects.filter(_event_wall_record_q(), occurred_at__gte=start).values('resource_type', 'metadata'):
        source_code = (item.get('metadata') or {}).get('event_source_code')
        if source_code:
            result[source_code] += 1
            continue
        resource_type = item.get('resource_type') or ''
        for source_type, resource_types in BUILTIN_RESOURCE_TYPES.items():
            if resource_type in resource_types:
                result[builtin_code_map.get(source_type, source_type)] += 1
    return result


def _event_environment_counts():
    result = defaultdict(int)
    for item in EventRecord.objects.filter(_event_wall_record_q()).exclude(environment='').values('environment').annotate(count=Count('id')):
        result[item['environment']] = item['count']
    return result


def _configured_environment_options():
    environments = list(EventEnvironment.objects.filter(enabled=True).order_by('sort_order', 'code'))
    if environments:
        return [
            {
                'code': item.code,
                'name': item.name,
                'label': item.name,
                'aliases': item.aliases or [],
            }
            for item in environments
        ]
    return []


def _source_catalog():
    _ensure_default_event_sources()
    catalog = {}
    for source in EventSource.objects.exclude(code__in=LEGACY_EVENT_SOURCE_CODES):
        catalog[source.code] = {
            'code': source.code,
            'name': source.name,
            'source_kind': source.source_kind,
            'source_type': source.source_type,
            'status': source.status,
            'enabled': source.enabled,
            'config': source.config or {},
        }
    return catalog


def _classify_event_source(event, catalog=None):
    catalog = catalog or _source_catalog()
    metadata = event.metadata or {}
    source_code = metadata.get('event_source_code') or ''
    if source_code and source_code in catalog:
        return catalog[source_code]

    resource_type = event.resource_type or ''
    for item in DEFAULT_EVENT_SOURCES:
        if item['source_kind'] != EventSource.KIND_BUILTIN:
            continue
        resource_types = item.get('config', {}).get('resource_types') or []
        if resource_type in resource_types:
            return catalog.get(item['code']) or {
                'code': item['code'],
                'name': item['name'],
                'source_kind': item['source_kind'],
                'source_type': item['source_type'],
                'status': item.get('status'),
                'enabled': item.get('enabled'),
            }

    fallback_code = f'module-{event.module or "unknown"}'
    return {
        'code': fallback_code,
        'name': event.module or '其他事件',
        'source_kind': 'module',
        'source_type': event.module or 'unknown',
        'status': '',
        'enabled': True,
    }


def _event_wall_record_q():
    return (
        Q(source_type=EventRecord.SOURCE_EXTERNAL)
        | Q(category='external_event')
        | Q(resource_type__in=WALL_BUILTIN_RESOURCE_TYPES)
    )


def _normalize_event_category(value):
    key = str(value or '').strip()
    if not key:
        return ''
    normalized = key.lower().replace('-', '_').replace(' ', '_')
    return normalized if normalized in EVENT_CATEGORY_MAP else EVENT_CATEGORY_ALIASES.get(normalized, '')


def _event_category_payload(key):
    category = EVENT_CATEGORY_MAP.get(key) or EVENT_CATEGORY_MAP['ops_transaction']
    return {
        'key': category['key'],
        'label': category['label'],
        'description': category['description'],
    }


def _event_category_from_traits(*values):
    for value in values:
        normalized = _normalize_event_category(value)
        if normalized:
            return normalized
    return ''


def _infer_event_category(event, source=None):
    metadata = event.metadata or {}
    explicit = _normalize_event_category(metadata.get('event_category') or metadata.get('wall_category') or metadata.get('workorder_type'))
    if explicit:
        return explicit

    trait_category = _event_category_from_traits(event.resource_type, event.action, metadata.get('event_type'), metadata.get('event_source_type'))
    if trait_category:
        return trait_category

    if source:
        source_config_key = _normalize_event_category((source.get('config') or {}).get('default_event_category'))
        if source_config_key:
            return source_config_key

    if event.resource_type == 'deployment':
        return 'application_release'
    if event.resource_type == 'sql_order':
        return 'db_change'
    if event.resource_type in {'host_task', 'host_task_batch', 'host_task_schedule'}:
        return 'task_center'
    if event.resource_type == 'transaction_ticket':
        ticket_type = str(metadata.get('ticket_type') or '').lower()
        if ticket_type == 'change':
            return 'config_change'
        return 'ops_transaction'
    if event.resource_type == 'deployment_approval_flow':
        return 'application_release'
    if event.source_type == EventRecord.SOURCE_EXTERNAL:
        event_type = _normalize_event_category(metadata.get('event_source_type') or event.action)
        return event_type or 'ops_transaction'
    return 'ops_transaction'


def _event_suspicion(event, fault_at=None):
    score = 0
    reasons = []
    if event.result == EventRecord.RESULT_FAILED:
        score += 45
        reasons.append('结果失败')
    elif event.result in {EventRecord.RESULT_PARTIAL, EventRecord.RESULT_PENDING}:
        score += 24
        reasons.append('结果未完全成功')
    if event.severity == EventRecord.SEVERITY_DANGER:
        score += 32
        reasons.append('高风险级别')
    elif event.severity == EventRecord.SEVERITY_WARNING:
        score += 14
        reasons.append('需要关注')
    if event.category in {'execution', 'resource_change', 'external_event', 'workflow'}:
        score += 16
        reasons.append('变更或执行类事件')
    if event.action in {'deploy', 'rollback', 'run_schedule', 'create_task', 'rerun_task', 'config_resource_update', 'sync', 'build'}:
        score += 12
        reasons.append('关键操作')
    if event.changes:
        score += 10
        reasons.append('包含变更内容')
    minutes_from_fault = None
    if fault_at:
        minutes_from_fault = round((event.occurred_at - fault_at).total_seconds() / 60, 1)
        abs_minutes = abs(minutes_from_fault)
        if -120 <= minutes_from_fault <= 15:
            score += 22
            reasons.append('靠近故障前窗口')
        elif abs_minutes <= 360:
            score += 8
            reasons.append('处于故障分析窗口')
    return score, reasons, minutes_from_fault


def _refresh_demo_event_timestamps():
    now = timezone.localtime().replace(second=0, microsecond=0)
    changed = []
    for item in EventRecord.objects.filter(is_demo=True).only('id', 'occurred_at', 'metadata'):
        metadata = item.metadata or {}
        offset = metadata.get('demo_offset_minutes')
        if offset is None:
            continue
        try:
            offset_minutes = max(0, min(int(offset), DEMO_WINDOW_MINUTES))
        except (TypeError, ValueError):
            continue
        target = now - timedelta(minutes=offset_minutes)
        if item.occurred_at != target:
            item.occurred_at = target
            changed.append(item)
    if changed:
        EventRecord.objects.bulk_update(changed, ['occurred_at'])


def _hourly_demo_event_time(hour_start, index, count, now):
    if hour_start.date() == now.date() and hour_start.hour == now.hour:
        span = max(1, now.minute)
        minute = min(now.minute, int((index + 1) * span / (count + 1)))
    else:
        slots = (9, 29, 49)
        minute = slots[index] if index < len(slots) else min(55, 9 + index * 15)
    return hour_start.replace(minute=minute, second=0, microsecond=0)


def _ensure_hourly_sample_demo_events(hours=24):
    now = timezone.localtime().replace(second=0, microsecond=0)
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    created = []
    for hour_offset in range(hours):
        hour_start = current_hour - timedelta(hours=hour_offset)
        hour_key = hour_start.strftime('%Y%m%d%H')
        target_count = 2 + ((hour_start.hour + hour_start.day) % 2)
        for index in range(target_count):
            category_key = HOURLY_DEMO_CATEGORIES[(hour_start.hour + index) % len(HOURLY_DEMO_CATEGORIES)]
            demo_key = f'ecommerce-k3s-hourly:{hour_key}:{index}'
            if EventRecord.objects.filter(metadata__hourly_demo_key=demo_key).exists():
                continue
            templates = HOURLY_DEMO_EVENT_TEMPLATES[category_key]
            template = templates[(hour_start.hour + index) % len(templates)]
            occurred_at = _hourly_demo_event_time(hour_start, index, target_count, now)
            resource_id = f'{category_key}-{hour_key}-{index + 1}'
            metadata = dict(template.get('metadata') or {})
            metadata.update({
                'event_category': category_key,
                'event_category_label': EVENT_CATEGORY_MAP[category_key]['label'],
                'hourly_demo_key': demo_key,
                'hourly_demo_environment': HOURLY_DEMO_ENVIRONMENT,
                'hourly_demo_hour': hour_key,
            })
            event = record_event(
                module=template['module'],
                category='workflow' if category_key == 'ops_transaction' else ('resource_change' if category_key == 'config_change' else 'execution'),
                action=template['action'],
                title=template['title'],
                summary=template['summary'],
                result=template['result'],
                severity=template['severity'],
                actor_username=template['actor_username'],
                actor_display=template['actor_display'],
                actor_type=EventRecord.ACTOR_SYSTEM,
                source_type=EventRecord.SOURCE_SEED,
                resource_type=template['resource_type'],
                resource_id=resource_id,
                resource_name=template['resource_name'],
                business_line=HOURLY_DEMO_SYSTEM,
                environment=HOURLY_DEMO_ENVIRONMENT,
                application=_application_for_event_category(category_key, template.get('application', '')),
                tags=['hourly-demo', category_key],
                related_resources=[
                    build_resource('ops', 'k8s_cluster', 'ecommerce-test-k3s', HOURLY_DEMO_ENVIRONMENT),
                    build_resource(template['module'], template['resource_type'], resource_id, template['resource_name']),
                ],
                metadata=metadata,
                correlation_id=f'hourly-demo:{HOURLY_DEMO_ENVIRONMENT}:{hour_key}:{index + 1}',
                occurred_at=occurred_at,
                is_demo=True,
            )
            if event:
                created.append(event)
    return created


def _parse_time_range(params):
    start_at = params.get('start_at', '').strip()
    end_at = params.get('end_at', '').strip()
    start = parse_datetime(start_at) if start_at else None
    end = parse_datetime(end_at) if end_at else None
    if start and timezone.is_naive(start):
        start = timezone.make_aware(start, timezone.get_current_timezone())
    if end and timezone.is_naive(end):
        end = timezone.make_aware(end, timezone.get_current_timezone())
    return start, end


def _build_window(queryset, params, default_days=7):
    start, end = _parse_time_range(params)
    if start:
        queryset = queryset.filter(occurred_at__gte=start)
    if end:
        queryset = queryset.filter(occurred_at__lte=end)
    if start or end:
        return queryset, start, end

    days = params.get('days', '').strip()
    if days.isdigit():
        start = timezone.now() - timedelta(days=int(days))
        return queryset.filter(occurred_at__gte=start), start, None

    if default_days is not None:
        start = timezone.now() - timedelta(days=default_days)
        return queryset.filter(occurred_at__gte=start), start, None

    return queryset, None, None


class EventRecordViewSet(RBACPermissionMixin, viewsets.ReadOnlyModelViewSet):
    queryset = EventRecord.objects.select_related('parent_event').all()
    serializer_class = EventRecordSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = [
        'title',
        'summary',
        'detail',
        'actor_username',
        'resource_name',
        'resource_type',
        'correlation_id',
    ]
    rbac_permissions = {
        'list': ['eventwall.view'],
        'retrieve': ['eventwall.view'],
        'overview': ['eventwall.view'],
        'associations': ['eventwall.view'],
        'filter_options': ['eventwall.view'],
        'analysis_wall': ['eventwall.view'],
        'operation_audit': ['rbac.audit.view'],
        'prune_operation_audit': ['rbac.audit.manage'],
    }

    def get_queryset(self):
        params = self.request.query_params
        if params.get('environment') == HOURLY_DEMO_ENVIRONMENT:
            _ensure_hourly_sample_demo_events()
        queryset = super().get_queryset().exclude(result=EventRecord.RESULT_REJECTED)
        if getattr(self, 'action', '') not in {'operation_audit', 'prune_operation_audit'}:
            queryset = queryset.filter(_event_wall_record_q())
        mapping = {
            'module': 'module',
            'category': 'category',
            'action': 'action',
            'result': 'result',
            'actor': 'actor_username',
            'resource_type': 'resource_type',
            'resource_id': 'resource_id',
            'environment': 'environment',
            'application': 'application',
            'correlation_id': 'correlation_id',
        }
        for key, field in mapping.items():
            value = params.get(key, '').strip()
            if value:
                queryset = queryset.filter(**{field: value})
        system_name = params.get('system_name', '').strip() or params.get('business_line', '').strip()
        if system_name:
            queryset = queryset.filter(business_line=system_name)
        event_source_code = params.get('event_source_code', '').strip()
        if event_source_code:
            source_def = next((item for item in DEFAULT_EVENT_SOURCES if item['code'] == event_source_code), None)
            if source_def and source_def['source_kind'] == EventSource.KIND_BUILTIN:
                queryset = queryset.filter(resource_type__in=source_def.get('config', {}).get('resource_types') or [])
            else:
                queryset = queryset.filter(metadata__event_source_code=event_source_code)
        if params.get('is_demo') in {'true', 'false'}:
            queryset = queryset.filter(is_demo=params.get('is_demo') == 'true')
        queryset, _, _ = _build_window(queryset, params, default_days=None)
        return queryset

    @action(detail=False, methods=['get'])
    def filter_options(self, request):
        queryset = self.get_queryset()
        configured_environments = _configured_environment_options()
        configured_codes = [item['code'] for item in configured_environments]
        event_environments = list(queryset.exclude(environment='').values_list('environment', flat=True).distinct().order_by('environment')[:50])
        if configured_codes:
            environment_values = configured_codes
            environment_options = configured_environments
        else:
            environment_values = event_environments
            environment_options = [{'code': item, 'name': item, 'label': item, 'aliases': []} for item in event_environments]
        scope_rows = list(
            queryset
            .exclude(environment='')
            .values('environment', 'business_line', 'application')
            .distinct()
            .order_by('environment', 'business_line', 'application')
        )
        systems_by_environment = {}
        applications_by_environment = {}
        applications_by_environment_system = {}
        for row in scope_rows:
            environment = row.get('environment') or ''
            business_line = row.get('business_line') or ''
            application = _normalize_service_name(row.get('application') or '')
            if business_line:
                systems_by_environment.setdefault(environment, set()).add(business_line)
            if application:
                applications_by_environment.setdefault(environment, set()).add(application)
                if business_line:
                    applications_by_environment_system.setdefault(environment, {}).setdefault(business_line, set()).add(application)
        applications_by_environment_system = {
            environment: {
                system: sorted(applications)
                for system, applications in systems.items()
            }
            for environment, systems in applications_by_environment_system.items()
        }
        system_names = list(queryset.exclude(business_line='').values_list('business_line', flat=True).distinct().order_by('business_line')[:50])
        return Response({
            'system_names': system_names,
            'systems': system_names,
            'business_lines': system_names,
            'environments': environment_values,
            'environment_options': environment_options,
            'event_environments': event_environments,
            'applications': sorted({
                _normalize_service_name(application)
                for application in queryset.exclude(application='').values_list('application', flat=True).distinct()
                if _normalize_service_name(application)
            })[:100],
            'systems_by_environment': {key: sorted(value) for key, value in systems_by_environment.items()},
            'applications_by_environment': {key: sorted(value) for key, value in applications_by_environment.items()},
            'applications_by_environment_system': applications_by_environment_system,
        })

    @action(detail=False, methods=['get'])
    def overview(self, request):
        recent, start, end = _build_window(self.get_queryset(), request.query_params, default_days=7)
        module_counts = list(recent.values('module').annotate(count=Count('id')).order_by('-count'))
        action_counts = list(recent.values('action').annotate(count=Count('id')).order_by('-count')[:8])
        applications = list(
            recent.exclude(application='')
            .values('application')
            .annotate(count=Count('id'))
            .order_by('-count')[:8]
        )
        system_names = list(
            recent.exclude(business_line='')
            .values('business_line')
            .annotate(count=Count('id'))
            .order_by('-count')[:8]
        )
        environments = list(
            recent.exclude(environment='')
            .values('environment')
            .annotate(count=Count('id'))
            .order_by('-count')[:8]
        )
        scopes = [
            {
                'system_name': item['business_line'],
                'business_line': item['business_line'],
                'environment': item['environment'],
                'count': item['count'],
                'label': f"{item['business_line']} / {item['environment']}",
            }
            for item in (
                recent.exclude(business_line='')
                .exclude(environment='')
                .values('business_line', 'environment')
                .annotate(count=Count('id'))
                .order_by('-count')[:8]
            )
        ]
        actors = list(
            recent.exclude(actor_username='')
            .values('actor_username')
            .annotate(count=Count('id'))
            .order_by('-count')[:8]
        )
        recent_items = EventRecordSerializer(recent[:12], many=True).data
        priority_events = EventRecordSerializer(
            recent.filter(category='execution', result__in=[EventRecord.RESULT_FAILED, EventRecord.RESULT_PARTIAL])[:8],
            many=True,
        ).data
        return Response({
            'summary': {
                'total_7d': recent.count(),
                'failed_7d': recent.filter(result=EventRecord.RESULT_FAILED).count(),
                'pending_7d': recent.filter(result=EventRecord.RESULT_PENDING).count(),
                'unique_actors_7d': recent.exclude(actor_username='').values('actor_username').distinct().count(),
                'tracked_resources_7d': recent.exclude(resource_type='').values('resource_type', 'resource_id').distinct().count(),
            },
            'window': {
                'start_at': start,
                'end_at': end,
            },
            'modules': module_counts,
            'actions': action_counts,
            'top_actors': actors,
            'top_applications': applications,
            'top_system_names': system_names,
            'top_systems': system_names,
            'top_business_lines': system_names,
            'top_environments': environments,
            'top_scopes': scopes,
            'recent': recent_items,
            'high_risk': priority_events,
            'priority_events': priority_events,
            'failed_deployments': [],
            'rejected_sql': [],
            'execution_watchlist': priority_events,
            'tips': [
                '事件墙只展示故障定位线索：外部事件源、工单系统和任务中心；平台内部操作请查看操作审计。',
                '排查问题时优先按系统、环境、应用缩小范围，再结合执行人、失败结果和关联链路快速定位。',
            ],
        })

    @action(detail=False, methods=['get'])
    def associations(self, request):
        recent, _, _ = _build_window(self.get_queryset(), request.query_params, default_days=14)
        recent = recent[:400]
        chains = defaultdict(list)
        hot_resources = Counter()
        module_links = Counter()

        for item in recent:
            if item.correlation_id:
                chains[item.correlation_id].append(item)
            resource_key = f'{item.resource_type}:{item.resource_name or item.resource_id}'
            if item.resource_type:
                hot_resources[resource_key] += 1
            related_modules = {entry.get('module') for entry in (item.related_resources or []) if entry.get('module')}
            for related_module in related_modules:
                if related_module != item.module:
                    module_links[f'{item.module}->{related_module}'] += 1

        chain_payload = []
        for correlation_id, items in sorted(chains.items(), key=lambda pair: len(pair[1]), reverse=True)[:8]:
            ordered = sorted(items, key=lambda record: (record.occurred_at, record.id))
            chain_payload.append({
                'correlation_id': correlation_id,
                'count': len(ordered),
                'title': ordered[0].title,
                'modules': list(dict.fromkeys(item.module for item in ordered)),
                'latest_at': ordered[-1].occurred_at,
                'events': EventRecordSerializer(ordered[:6], many=True).data,
            })

        hot_resource_payload = [{'resource': key, 'count': count} for key, count in hot_resources.most_common(10)]
        module_link_payload = [{'link': key, 'count': count} for key, count in module_links.most_common(10)]
        return Response({
            'chains': chain_payload,
            'hot_resources': hot_resource_payload,
            'module_links': module_link_payload,
        })

    @action(detail=False, methods=['get'])
    def operation_audit(self, request):
        queryset = self.filter_queryset(
            self.get_queryset()
            .exclude(source_type=EventRecord.SOURCE_EXTERNAL)
            .exclude(category='external_event')
            .order_by('-occurred_at', '-id')
        )
        page = self.paginate_queryset(queryset)
        if page is not None:
            return self.get_paginated_response(EventRecordSerializer(page, many=True).data)
        return Response(EventRecordSerializer(queryset[:100], many=True).data)

    @action(detail=False, methods=['post'])
    def prune_operation_audit(self, request):
        cutoff_raw = (request.data.get('before_at') or '').strip()
        cutoff = parse_datetime(cutoff_raw) if cutoff_raw else None
        if not cutoff:
            return Response({'detail': '请提供有效的截止时间 before_at。'}, status=status.HTTP_400_BAD_REQUEST)
        if timezone.is_naive(cutoff):
            cutoff = timezone.make_aware(cutoff, timezone.get_current_timezone())

        queryset = (
            self.get_queryset()
            .exclude(source_type=EventRecord.SOURCE_EXTERNAL)
            .exclude(category='external_event')
            .filter(occurred_at__lt=cutoff)
        )
        deleted_count = queryset.count()
        queryset.delete()
        record_event(
            module='rbac',
            category='resource_change',
            action='prune_operation_audit',
            title='批量删除操作审计',
            summary=f'删除 {cutoff.isoformat()} 之前的操作审计记录 {deleted_count} 条',
            result=EventRecord.RESULT_SUCCESS,
            severity=EventRecord.SEVERITY_WARNING,
            actor_username=getattr(request.user, 'username', '') or '',
            actor_display=getattr(request.user, 'get_full_name', lambda: '')() or getattr(request.user, 'username', '') or '',
            actor_type=EventRecord.ACTOR_USER,
            source_type=EventRecord.SOURCE_HTTP,
            request_method=request.method,
            source_path=request.path,
            ip_address=request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or request.META.get('REMOTE_ADDR', ''),
            resource_module='rbac',
            resource_type='operation_audit',
            resource_id=cutoff.isoformat(),
            resource_name='操作审计',
            metadata={'before_at': cutoff.isoformat(), 'deleted': deleted_count},
        )
        return Response({'deleted': deleted_count, 'before_at': cutoff})

    @action(detail=False, methods=['get'])
    def analysis_wall(self, request):
        params = request.query_params
        queryset = self.get_queryset()
        fault_at = parse_datetime(params.get('fault_at', '').strip()) if params.get('fault_at') else None
        if fault_at and timezone.is_naive(fault_at):
            fault_at = timezone.make_aware(fault_at, timezone.get_current_timezone())

        if fault_at and not (params.get('start_at') or params.get('end_at')):
            try:
                lookback_minutes = min(max(int(params.get('lookback_minutes', 240)), 15), 7 * 24 * 60)
            except (TypeError, ValueError):
                lookback_minutes = 240
            try:
                after_minutes = min(max(int(params.get('after_minutes', 60)), 0), 24 * 60)
            except (TypeError, ValueError):
                after_minutes = 60
            start = fault_at - timedelta(minutes=lookback_minutes)
            end = fault_at + timedelta(minutes=after_minutes)
            queryset = queryset.filter(occurred_at__gte=start, occurred_at__lte=end)
        else:
            queryset, start, end = _build_window(queryset, params, default_days=3)

        try:
            limit = min(max(int(params.get('limit', 160)), 20), 500)
        except (TypeError, ValueError):
            limit = 160

        catalog = _source_catalog()
        ordered_events = list(queryset.order_by('occurred_at', 'id')[:limit])
        serialized = EventRecordSerializer(ordered_events, many=True).data
        lanes = {}
        suspects = []
        events = []

        for event, payload in zip(ordered_events, serialized):
            source = _classify_event_source(event, catalog)
            event_category_key = _infer_event_category(event, source)
            score, reasons, minutes_from_fault = _event_suspicion(event, fault_at=fault_at)
            payload['event_source'] = source
            payload['event_category'] = _event_category_payload(event_category_key)
            payload['minutes_from_fault'] = minutes_from_fault
            payload['suspicion_score'] = score
            payload['suspicion_reasons'] = reasons
            events.append(payload)

            lane = lanes.setdefault(source['code'], {
                'source': source,
                'count': 0,
                'failed': 0,
                'warning': 0,
                'before_fault': 0,
                'after_fault': 0,
                'events': [],
            })
            lane['count'] += 1
            lane['failed'] += 1 if event.result == EventRecord.RESULT_FAILED else 0
            lane['warning'] += 1 if event.severity in {EventRecord.SEVERITY_WARNING, EventRecord.SEVERITY_DANGER} else 0
            if fault_at and event.occurred_at <= fault_at:
                lane['before_fault'] += 1
            elif fault_at:
                lane['after_fault'] += 1
            lane['events'].append(payload)

            if score >= 35:
                suspects.append(payload)

        suspects = sorted(suspects, key=lambda item: (-item['suspicion_score'], abs(item['minutes_from_fault'] or 999999), item['occurred_at']))[:12]
        lane_payload = sorted(lanes.values(), key=lambda item: (-item['failed'], -item['warning'], -item['count'], item['source']['name']))
        source_breakdown = [
            {
                'code': lane['source']['code'],
                'name': lane['source']['name'],
                'source_kind': lane['source']['source_kind'],
                'count': lane['count'],
                'failed': lane['failed'],
                'warning': lane['warning'],
            }
            for lane in lane_payload
        ]
        category_sections = []
        for category_def in EVENT_CATEGORY_DEFINITIONS:
            section_events = [item for item in events if (item.get('event_category') or {}).get('key') == category_def['key']]
            category_sections.append({
                'key': category_def['key'],
                'label': category_def['label'],
                'description': category_def['description'],
                'count': len(section_events),
                'failed': sum(1 for item in section_events if item.get('result') == EventRecord.RESULT_FAILED),
                'warning': sum(1 for item in section_events if item.get('severity') in {EventRecord.SEVERITY_WARNING, EventRecord.SEVERITY_DANGER}),
                'events': section_events[:30],
            })
        suspect_ids = {item['id'] for item in suspects}
        impact_map = {}
        correlation_map = {}
        for item in events:
            scope_key = (
                item.get('system_name') or item.get('business_line') or '未标注系统',
                item.get('environment') or '未标注环境',
                item.get('application') or item.get('resource_name') or '未标注应用',
            )
            impact = impact_map.setdefault(scope_key, {
                'system_name': scope_key[0],
                'business_line': scope_key[0],
                'environment': scope_key[1],
                'application': scope_key[2],
                'count': 0,
                'failed': 0,
                'warning': 0,
                'suspects': 0,
                'source_codes': set(),
                'source_names': set(),
                'latest_at': '',
            })
            impact['count'] += 1
            impact['failed'] += 1 if item.get('result') == EventRecord.RESULT_FAILED else 0
            impact['warning'] += 1 if item.get('severity') in {EventRecord.SEVERITY_WARNING, EventRecord.SEVERITY_DANGER} else 0
            impact['suspects'] += 1 if item.get('id') in suspect_ids else 0
            impact['source_codes'].add((item.get('event_source') or {}).get('code') or item.get('module') or 'unknown')
            impact['source_names'].add((item.get('event_source') or {}).get('name') or item.get('module') or '其他事件')
            if not impact['latest_at'] or str(item.get('occurred_at') or '') > impact['latest_at']:
                impact['latest_at'] = item.get('occurred_at') or ''

            correlation_id = item.get('correlation_id') or ''
            if correlation_id:
                chain = correlation_map.setdefault(correlation_id, {
                    'correlation_id': correlation_id,
                    'title': item.get('title') or correlation_id,
                    'count': 0,
                    'failed': 0,
                    'warning': 0,
                    'suspects': 0,
                    'source_names': set(),
                    'events': [],
                    'latest_at': '',
                })
                chain['count'] += 1
                chain['failed'] += 1 if item.get('result') == EventRecord.RESULT_FAILED else 0
                chain['warning'] += 1 if item.get('severity') in {EventRecord.SEVERITY_WARNING, EventRecord.SEVERITY_DANGER} else 0
                chain['suspects'] += 1 if item.get('id') in suspect_ids else 0
                chain['source_names'].add((item.get('event_source') or {}).get('name') or item.get('module') or '其他事件')
                chain['events'].append(item)
                if not chain['latest_at'] or str(item.get('occurred_at') or '') > chain['latest_at']:
                    chain['latest_at'] = item.get('occurred_at') or ''

        affected_scopes = []
        for item in impact_map.values():
            source_codes = item.pop('source_codes')
            source_names = item.pop('source_names')
            item['source_count'] = len(source_codes)
            item['source_names'] = sorted(source_names)
            item['risk_score'] = item['failed'] * 30 + item['warning'] * 12 + item['suspects'] * 18 + item['source_count'] * 4
            affected_scopes.append(item)
        affected_scopes = sorted(affected_scopes, key=lambda item: (-item['risk_score'], -item['failed'], -item['count'], item['application']))[:10]

        correlation_chains = []
        for item in correlation_map.values():
            if item['count'] < 2 and not item['failed'] and not item['suspects']:
                continue
            item['source_names'] = sorted(item['source_names'])
            item['events'] = item['events'][:6]
            item['risk_score'] = item['failed'] * 32 + item['warning'] * 12 + item['suspects'] * 20 + item['count']
            correlation_chains.append(item)
        correlation_chains = sorted(correlation_chains, key=lambda item: (-item['risk_score'], -item['count'], item['correlation_id']))[:8]

        recommendations = []
        if suspects:
            first = suspects[0]
            recommendations.append(f"先核查「{first.get('title')}」，它的风险分最高且{'; '.join(first.get('suspicion_reasons') or ['靠近故障窗口'])}。")
        if affected_scopes:
            scope = affected_scopes[0]
            recommendations.append(f"优先收敛到 {scope['system_name']} / {scope['environment']} / {scope['application']}，该范围内有 {scope['failed']} 个失败事件、{scope['suspects']} 个疑似事件。")
        if correlation_chains:
            chain = correlation_chains[0]
            recommendations.append(f"检查关联链路 {chain['correlation_id']}，它串起 {chain['count']} 个事件和 {len(chain['source_names'])} 个来源。")
        if not recommendations:
            recommendations.append('当前窗口未发现明显高风险线索，可扩大时间窗口或按应用、环境继续收敛。')

        return Response({
            'window': {
                'start_at': start,
                'end_at': end,
                'fault_at': fault_at,
            },
            'summary': {
                'total': len(events),
                'failed': sum(1 for item in events if item['result'] == EventRecord.RESULT_FAILED),
                'warning': sum(1 for item in events if item['severity'] in {EventRecord.SEVERITY_WARNING, EventRecord.SEVERITY_DANGER}),
                'suspects': len(suspects),
                'source_count': len(lane_payload),
                'scope_count': len(affected_scopes),
                'chain_count': len(correlation_chains),
                'category_count': sum(1 for item in category_sections if item['count']),
            },
            'event_categories': [_event_category_payload(item['key']) for item in EVENT_CATEGORY_DEFINITIONS],
            'category_sections': category_sections,
            'source_breakdown': source_breakdown,
            'affected_scopes': affected_scopes,
            'correlation_chains': correlation_chains,
            'lanes': lane_payload,
            'suspects': suspects,
            'events': events,
            'recommendations': recommendations,
            'tips': [
                '先确定故障时刻，再看故障前 1-4 小时内失败、高风险、工单、任务和外部系统事件。',
                '同一应用、环境、系统内靠近故障时刻的发布工单、任务执行和外部流水线异常优先排查。',
            ],
        })


class EventSourceViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    serializer_class = EventSourceSerializer
    lookup_field = 'code'
    search_fields = ['name', 'code', 'description']
    filterset_fields = ['source_kind', 'source_type', 'enabled', 'status']
    http_method_names = ['get', 'post', 'put', 'patch', 'delete', 'head', 'options']
    rbac_permissions = {
        'list': ['eventwall.source.view'],
        'retrieve': ['eventwall.source.view'],
        'create': ['eventwall.source.manage'],
        'update': ['eventwall.source.manage'],
        'partial_update': ['eventwall.source.manage'],
        'destroy': ['eventwall.source.manage'],
        'summary': ['eventwall.source.view'],
        'ingest_spec': ['eventwall.source.view'],
        'issue_token': ['eventwall.source.manage'],
        'toggle_enabled': ['eventwall.source.manage'],
    }

    def get_queryset(self):
        _ensure_default_event_sources()
        return EventSource.objects.exclude(code__in=LEGACY_EVENT_SOURCE_CODES)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['recent_event_counts'] = _event_source_counts()
        return context

    @action(detail=False, methods=['get'])
    def summary(self, request):
        queryset = self.get_queryset()
        recent_counts = _event_source_counts()
        total_recent = sum(recent_counts.values())
        external_enabled = queryset.filter(source_kind=EventSource.KIND_EXTERNAL, enabled=True).count()
        warning = queryset.filter(status__in=[EventSource.STATUS_WARNING, EventSource.STATUS_NOT_CONFIGURED]).count()
        latest = EventRecord.objects.filter(source_type=EventRecord.SOURCE_EXTERNAL).order_by('-occurred_at').first()
        return Response({
            'total_sources': queryset.count(),
            'builtin_sources': queryset.filter(source_kind=EventSource.KIND_BUILTIN).count(),
            'external_sources': queryset.filter(source_kind=EventSource.KIND_EXTERNAL).count(),
            'external_enabled': external_enabled,
            'warning_sources': warning,
            'recent_events_7d': total_recent,
            'latest_external_event_at': latest.occurred_at if latest else None,
        })

    @action(detail=False, methods=['get'])
    def ingest_spec(self, request):
        return Response(INGEST_SPEC)

    def destroy(self, request, *args, **kwargs):
        source = self.get_object()
        if source.source_kind == EventSource.KIND_BUILTIN:
            return Response({'detail': '平台内置事件源不允许删除。'}, status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['post'])
    def issue_token(self, request, code=None):
        source = self.get_object()
        if source.source_kind != EventSource.KIND_EXTERNAL:
            return Response({'detail': '平台内置事件源不需要接入令牌。'}, status=status.HTTP_400_BAD_REQUEST)
        token = source.issue_token()
        source.enabled = True
        source.status = EventSource.STATUS_HEALTHY
        source.last_error = ''
        source.save(update_fields=['token_hash', 'token_preview', 'enabled', 'status', 'last_error', 'updated_at'])
        return Response({'token': token, 'token_preview': source.token_preview})

    @action(detail=True, methods=['post'])
    def toggle_enabled(self, request, code=None):
        source = self.get_object()
        source.enabled = not source.enabled
        if source.enabled and source.status == EventSource.STATUS_DISABLED:
            source.status = EventSource.STATUS_HEALTHY if source.source_kind == EventSource.KIND_BUILTIN or source.token_hash else EventSource.STATUS_NOT_CONFIGURED
        elif not source.enabled:
            source.status = EventSource.STATUS_DISABLED
        source.save(update_fields=['enabled', 'status', 'updated_at'])
        return Response(self.get_serializer(source).data)


class EventEnvironmentViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    serializer_class = EventEnvironmentSerializer
    queryset = EventEnvironment.objects.all()
    lookup_field = 'code'
    search_fields = ['code', 'name', 'description']
    filter_backends = [filters.SearchFilter]
    filterset_fields = ['enabled']
    rbac_permissions = {
        'list': ['eventwall.environment.view'],
        'retrieve': ['eventwall.environment.view'],
        'create': ['eventwall.environment.manage'],
        'update': ['eventwall.environment.manage'],
        'partial_update': ['eventwall.environment.manage'],
        'destroy': ['eventwall.environment.manage'],
        'unmatched': ['eventwall.environment.view'],
    }

    def get_queryset(self):
        return EventEnvironment.objects.all().order_by('sort_order', 'code')

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['environment_event_counts'] = _event_environment_counts()
        return context

    @action(detail=False, methods=['get'])
    def unmatched(self, request):
        rows = (
            EventRecord.objects
            .filter(metadata__environment_unmatched=True)
            .exclude(environment='')
            .values('environment')
            .annotate(count=Count('id'), latest_at=Max('occurred_at'))
            .order_by('-count', 'environment')[:50]
        )
        return Response([
            {
                'environment': item['environment'],
                'count': item['count'],
                'latest_at': item['latest_at'],
            }
            for item in rows
        ])


class ExternalEventIngestView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request, type=None, code=None):
        _ensure_default_event_sources()
        source_key = type or code
        try:
            source = EventSource.objects.get(code=source_key, source_kind=EventSource.KIND_EXTERNAL)
        except EventSource.DoesNotExist:
            return Response({'detail': '事件源不存在。'}, status=status.HTTP_404_NOT_FOUND)

        if not source.enabled:
            return Response({'detail': '事件源未启用。'}, status=status.HTTP_403_FORBIDDEN)
        if not source.verify_token(_extract_event_source_token(request)):
            source.status = EventSource.STATUS_WARNING
            source.last_error = '接入令牌校验失败'
            source.save(update_fields=['status', 'last_error', 'updated_at'])
            return Response({'detail': '接入令牌无效。'}, status=status.HTTP_403_FORBIDDEN)

        payload = request.data if isinstance(request.data, dict) else {}
        normalized = _normalize_provider_payload(source, payload)
        serializer = EventSourceIngestSerializer(data=normalized)
        if not serializer.is_valid():
            source.status = EventSource.STATUS_WARNING
            source.last_error = '事件载荷不符合接入规范'
            source.save(update_fields=['status', 'last_error', 'updated_at'])
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        environment_resolution = resolve_event_environment(data.get('environment', ''), strict=EventEnvironment.objects.filter(enabled=True).exists())
        if not environment_resolution['ok']:
            source.status = EventSource.STATUS_WARNING
            source.last_error = environment_resolution['detail']
            source.save(update_fields=['status', 'last_error', 'updated_at'])
            return Response({'environment': environment_resolution['detail']}, status=status.HTTP_400_BAD_REQUEST)
        source_default_category = _normalize_event_category((source.config or {}).get('default_event_category'))
        payload_category = _normalize_event_category(data.get('event_category'))
        trait_category = _event_category_from_traits(data.get('event_type'), data.get('action'), data.get('resource_type'))
        event_category = payload_category or trait_category or source_default_category
        if not event_category:
            source.status = EventSource.STATUS_WARNING
            source.last_error = '事件载荷缺少有效事件分类 event_category'
            source.save(update_fields=['status', 'last_error', 'updated_at'])
            return Response(
                {'event_category': '请提供有效事件分类：application_release、db_change、config_change、ops_transaction、task_center。'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        event_id = data.get('event_id', '')
        if event_id:
            existing = EventRecord.objects.filter(
                metadata__event_source_code=source.code,
                metadata__external_event_id=event_id,
            ).order_by('-occurred_at', '-id').first()
            if existing:
                source.status = EventSource.STATUS_HEALTHY
                source.last_error = ''
                source.last_sync_at = timezone.now()
                source.last_event_at = existing.occurred_at
                source.save(update_fields=['status', 'last_error', 'last_sync_at', 'last_event_at', 'updated_at'])
                response_data = EventRecordSerializer(existing).data
                response_data['deduplicated'] = True
                return Response(response_data, status=status.HTTP_200_OK)

        metadata = dict(data.get('metadata') or {})
        metadata.update({
            'event_source_code': source.code,
            'event_source_name': source.name,
            'event_source_type': source.source_type,
            'event_category': event_category,
            'event_category_label': EVENT_CATEGORY_MAP[event_category]['label'],
            'event_category_source': 'payload' if payload_category else ('traits' if trait_category else 'source_default'),
            'external_event_id': event_id,
        })
        event = record_event(
            module='eventwall',
            category='external_event',
            action=data.get('action') or data.get('event_type') or 'ingest',
            title=data['title'],
            summary=data.get('summary') or data['title'],
            detail=data.get('detail', ''),
            result=data.get('result') or EventRecord.RESULT_SUCCESS,
            severity=data.get('severity') or EventRecord.SEVERITY_INFO,
            actor_username=data.get('actor') or source.code,
            actor_display=data.get('actor') or source.name,
            actor_type=EventRecord.ACTOR_SYSTEM,
            source_type=EventRecord.SOURCE_EXTERNAL,
            source_path=request.path,
            ip_address=request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or request.META.get('REMOTE_ADDR', ''),
            resource_module='eventwall',
            resource_type=data.get('resource_type') or source.source_type,
            resource_id=data.get('resource_id') or data.get('event_id', ''),
            resource_name=data.get('resource_name') or data['title'],
            business_line=data.get('system_name') or data.get('business_line', ''),
            environment=data.get('environment', ''),
            application=data.get('application', ''),
            tags=data.get('tags') or [],
            related_resources=data.get('related_resources') or [],
            changes=data.get('changes') or {},
            metadata=metadata,
            correlation_id=data.get('correlation_id') or f'{source.code}:{data.get("event_id") or timezone.now().strftime("%Y%m%d%H%M%S")}',
            occurred_at=data.get('occurred_at'),
        )
        source.status = EventSource.STATUS_HEALTHY
        source.last_error = ''
        source.last_sync_at = timezone.now()
        source.last_event_at = event.occurred_at if event else timezone.now()
        source.save(update_fields=['status', 'last_error', 'last_sync_at', 'last_event_at', 'updated_at'])
        return Response(EventRecordSerializer(event).data, status=status.HTTP_201_CREATED)

