import json
from datetime import timedelta
import paramiko
from django.db.models import Avg, Count, Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from aiops.models import AIOpsPendingAction
from eventwall.mixins import EventWallModelViewSetMixin
from eventwall.models import EventRecord
from eventwall.services import build_json_preview, build_resource, record_event
from rbac.permissions import RBACPermissionMixin, build_rbac_permission

from . import deployer
from .host_task_schedules import (
    build_schedule_snapshot,
    preview_next_runs,
    resolve_schedule_hosts,
    trigger_schedule,
)
from .host_tasks import build_host_target_queryset, build_k8s_target_snapshot, mark_stale_running_host_tasks, record_task_center_event, resolve_host_source_refs, start_host_task, start_k8s_task
from .models import (
    Alert,
    AlertAction,
    AlertAggregationRule,
    AlertEscalationPolicy,
    AlertInhibitionRule,
    AlertIntegration,
    AlertMuteRule,
    AlertNotificationChannel,
    AlertNotificationLog,
    AlertNotificationRule,
    AlertRecipient,
    AlertRecipientGroup,
    Deployment,
    DeploymentApprovalFlow,
    DeploymentApprovalStep,
    Host,
    HostTask,
    HostTaskSchedule,
    HostTaskScheduleExecution,
    HostTaskTemplate,
    K8sCluster,
    LogEntry,
    TaskResource,
    TaskResourceGroup,
    TransactionTicket,
)
from .serializers import (
    AlertActionSerializer,
    AlertAggregationRuleSerializer,
    AlertEscalationPolicySerializer,
    AlertInhibitionRuleSerializer,
    AlertIntegrationSerializer,
    AlertMuteRuleSerializer,
    AlertNotificationChannelSerializer,
    AlertNotificationLogSerializer,
    AlertNotificationRuleSerializer,
    AlertRecipientGroupSerializer,
    AlertRecipientSerializer,
    AlertSerializer,
    ApprovalActionSerializer,
    DeploymentActionSerializer,
    DeploymentApprovalFlowSerializer,
    DeploymentSerializer,
    HostSerializer,
    HostTaskBatchCancelSerializer,
    HostTaskDetailSerializer,
    HostTaskRenameSerializer,
    HostTaskScheduleExecutionSerializer,
    HostTaskSchedulePreviewSerializer,
    HostTaskScheduleSerializer,
    HostTaskSerializer,
    HostTaskSubmitSerializer,
    HostTaskTargetSerializer,
    HostTaskTemplateSerializer,
    LogEntrySerializer,
    TaskResourceGroupSerializer,
    TaskResourceSerializer,
    TransactionTicketSerializer,
)
from .alerting import (
    alert_group_summary,
    alert_summary,
    apply_alert_action,
    dispatch_alert_notifications,
    handle_interaction_token,
    ingest_webhook,
    match_matchers,
    normalize_provider,
    resolve_integration,
)


def _resolve_approval_flow(environment):
    flow = DeploymentApprovalFlow.objects.filter(is_active=True, environment=environment).prefetch_related('nodes').first()
    if flow:
        return flow
    return DeploymentApprovalFlow.objects.filter(is_active=True, environment='').prefetch_related('nodes').first()


def _build_schedule_preview_input(request):
    if request.method == 'GET':
        payload = {}
        for key, value in request.query_params.items():
            if key in {'payload', 'selection_filters', 'target_host_ids'} and value:
                try:
                    payload[key] = json.loads(value)
                except json.JSONDecodeError:
                    payload[key] = value
            else:
                payload[key] = value
        return payload
    return request.data


def _initialize_approval_steps(deployment):
    flow = _resolve_approval_flow(deployment.environment)
    deployment.approval_flow = flow
    deployment.save(update_fields=['approval_flow'])
    deployment.approval_steps.all().delete()
    if not flow:
        return
    steps = []
    nodes = list(flow.nodes.all().order_by('order', 'id'))
    for index, node in enumerate(nodes):
        steps.append(
            DeploymentApprovalStep(
                deployment=deployment,
                flow=flow,
                node_name=node.name,
                node_order=node.order,
                approver_type=node.approver_type,
                approver_value=node.approver_value,
                is_current=index == 0,
            )
        )
    DeploymentApprovalStep.objects.bulk_create(steps)


def _match_step_approver(user, step):
    if user.is_superuser:
        return True
    if not step or not step.approver_value:
        return True
    if step.approver_type == 'user':
        return user.username == step.approver_value
    if step.approver_type == 'role':
        return user.rbac_roles.filter(code=step.approver_value).exists()
    if step.approver_type == 'group':
        return user.rbac_groups.filter(code=step.approver_value).exists()
    return True


def _apply_system_alias_filter(request, queryset, *fields):
    system_name = (request.query_params.get('system_name') or request.query_params.get('system') or '').strip()
    if not system_name:
        return queryset
    condition = Q()
    for field in fields:
        condition |= Q(**{field: system_name})
    return queryset.filter(condition)


class HostViewSet(EventWallModelViewSetMixin, RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = Host.objects.all()
    serializer_class = HostSerializer
    search_fields = ['hostname', 'ip_address']
    filterset_fields = ['status', 'business_line', 'environment']
    event_module = 'ops'
    event_resource_type = 'host'
    event_resource_label = '主机'
    event_resource_name_fields = ('hostname',)
    event_exclude_fields = ('ssh_password',)
    rbac_permissions = {
        'list': ['ops.host.view'],
        'retrieve': ['ops.host.view'],
        'create': ['ops.host.manage'],
        'update': ['ops.host.manage'],
        'partial_update': ['ops.host.manage'],
        'destroy': ['ops.host.manage'],
        'test_connection': ['ops.host.manage'],
        'refresh_info': ['ops.host.manage'],
    }

    def get_queryset(self):
        return _apply_system_alias_filter(self.request, super().get_queryset(), 'business_line')

    @action(detail=True, methods=['post'])
    def test_connection(self, request, pk=None):
        host = self.get_object()
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                hostname=host.ip_address,
                port=host.ssh_port or 22,
                username=host.ssh_user or 'root',
                password=host.ssh_password or None,
                timeout=10,
            )
            stdin, stdout, stderr = client.exec_command('uname -a', timeout=5)
            uname = stdout.read().decode('utf-8', errors='replace').strip()
            client.close()
            record_event(
                request=request,
                module='ops',
                category='execution',
                action='test_connection',
                title='\u6d4b\u8bd5\u4e3b\u673a\u8fde\u901a\u6027',
                summary=f'\u4e3b\u673a {host.hostname} \u8fde\u901a\u6027\u6d4b\u8bd5\u6210\u529f',
                resource_type='host',
                resource_id=host.id,
                resource_name=host.hostname,
                business_line=host.business_line,
                environment=host.environment,
                correlation_id=f'host:{host.id}',
                metadata={'ip_address': host.ip_address},
            )
            return Response({'success': True, 'message': f'\u8fde\u63a5\u6210\u529f: {uname}'})
        except Exception as exc:
            record_event(
                request=request,
                module='ops',
                category='execution',
                action='test_connection',
                title='\u6d4b\u8bd5\u4e3b\u673a\u8fde\u901a\u6027',
                summary=f'\u4e3b\u673a {host.hostname} \u8fde\u901a\u6027\u6d4b\u8bd5\u5931\u8d25',
                result=EventRecord.RESULT_FAILED,
                severity=EventRecord.SEVERITY_WARNING,
                resource_type='host',
                resource_id=host.id,
                resource_name=host.hostname,
                business_line=host.business_line,
                environment=host.environment,
                correlation_id=f'host:{host.id}',
                metadata={'ip_address': host.ip_address, 'error': str(exc)},
            )
            return Response({'success': False, 'message': f'\u8fde\u63a5\u5931\u8d25: {str(exc)}'})

    @action(detail=True, methods=['post'])
    def refresh_info(self, request, pk=None):
        host = self.get_object()
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                hostname=host.ip_address,
                port=host.ssh_port or 22,
                username=host.ssh_user or 'root',
                password=host.ssh_password or None,
                timeout=10,
            )

            def run_cmd(command):
                stdin, stdout, stderr = client.exec_command(command, timeout=5)
                return stdout.read().decode('utf-8', errors='replace').strip()

            try:
                host.cpu_usage = round(float(run_cmd("top -bn1 | grep 'Cpu(s)' | awk '{print $2}'")), 1)
            except (ValueError, TypeError):
                pass
            try:
                host.memory_usage = round(float(run_cmd("free | grep Mem | awk '{printf(\"%.1f\", $3/$2*100)}'")), 1)
            except (ValueError, TypeError):
                pass
            try:
                host.disk_usage = round(float(run_cmd("df / | tail -1 | awk '{print $5}' | tr -d '%'")), 1)
            except (ValueError, TypeError):
                pass

            host.status = 'online'
            host.save(update_fields=['cpu_usage', 'memory_usage', 'disk_usage', 'status'])
            client.close()
            record_event(
                request=request,
                module='ops',
                category='execution',
                action='refresh_info',
                title='\u5237\u65b0\u4e3b\u673a\u72b6\u6001',
                summary=f'\u4e3b\u673a {host.hostname} \u72b6\u6001\u5df2\u5237\u65b0',
                resource_type='host',
                resource_id=host.id,
                resource_name=host.hostname,
                business_line=host.business_line,
                environment=host.environment,
                correlation_id=f'host:{host.id}',
                metadata={
                    'cpu_usage': host.cpu_usage,
                    'memory_usage': host.memory_usage,
                    'disk_usage': host.disk_usage,
                },
            )
            return Response(HostSerializer(host).data)
        except Exception as exc:
            host.status = 'offline'
            host.save(update_fields=['status'])
            record_event(
                request=request,
                module='ops',
                category='execution',
                action='refresh_info',
                title='\u5237\u65b0\u4e3b\u673a\u72b6\u6001',
                summary=f'\u4e3b\u673a {host.hostname} \u5237\u65b0\u5931\u8d25\uff0c\u5df2\u6807\u8bb0\u79bb\u7ebf',
                result=EventRecord.RESULT_FAILED,
                severity=EventRecord.SEVERITY_WARNING,
                resource_type='host',
                resource_id=host.id,
                resource_name=host.hostname,
                business_line=host.business_line,
                environment=host.environment,
                correlation_id=f'host:{host.id}',
                metadata={'error': str(exc)},
            )
            return Response({'detail': f'\u83b7\u53d6\u4fe1\u606f\u5931\u8d25: {str(exc)}'}, status=400)


class TaskResourceGroupViewSet(EventWallModelViewSetMixin, RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = TaskResourceGroup.objects.select_related('parent', 'event_environment').prefetch_related('children').all()
    serializer_class = TaskResourceGroupSerializer
    pagination_class = None
    event_module = 'ops'
    event_resource_type = 'task_resource_group'
    event_resource_label = '任务资源分组'
    event_resource_name_fields = ('name',)
    rbac_permissions = {
        'list': ['ops.task.resource.view'],
        'retrieve': ['ops.task.resource.view'],
        'create': ['ops.task.resource.manage'],
        'update': ['ops.task.resource.manage'],
        'partial_update': ['ops.task.resource.manage'],
        'destroy': ['ops.task.resource.manage'],
        'tree': ['ops.task.resource.view'],
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        group_type = self.request.query_params.get('group_type')
        parent = self.request.query_params.get('parent')
        if group_type:
            queryset = queryset.filter(group_type=group_type)
        if parent:
            queryset = queryset.filter(parent_id=parent)
        return queryset.order_by('group_type', 'sort_order', 'name', 'id')

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user.username)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user.username)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.children.exists():
            return Response({'detail': '请先删除该节点下的系统'}, status=status.HTTP_400_BAD_REQUEST)
        if TaskResource.objects.filter(Q(environment=instance) | Q(system=instance)).exists():
            return Response({'detail': '该节点下仍存在执行资源，不能删除'}, status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)

    @action(detail=False, methods=['get'])
    def tree(self, request):
        groups = list(TaskResourceGroup.objects.select_related('parent', 'event_environment').order_by('group_type', 'sort_order', 'name', 'id'))
        resources = TaskResource.objects.values('environment_id', 'system_id', 'resource_type').annotate(total=Count('id'))
        env_counts = {}
        system_counts = {}
        for item in resources:
            env_counts[item['environment_id']] = env_counts.get(item['environment_id'], 0) + item['total']
            if item['system_id']:
                system_counts[item['system_id']] = system_counts.get(item['system_id'], 0) + item['total']
        systems_by_env = {}
        for group in groups:
            if group.group_type == TaskResourceGroup.GROUP_SYSTEM and group.parent_id:
                systems_by_env.setdefault(group.parent_id, []).append(group)
        tree = []
        for group in groups:
            if group.group_type != TaskResourceGroup.GROUP_ENVIRONMENT:
                continue
            children = [
                {
                    'id': system.id,
                    'name': system.name,
                    'code': system.code,
                    'group_type': system.group_type,
                    'parent': system.parent_id,
                    'event_environment': system.event_environment_id,
                    'event_environment_code': system.event_environment.code if system.event_environment_id else '',
                    'event_environment_name': system.event_environment.name if system.event_environment_id else '',
                    'description': system.description,
                    'sort_order': system.sort_order,
                    'resource_count': system_counts.get(system.id, 0),
                    'children': [],
                }
                for system in systems_by_env.get(group.id, [])
            ]
            tree.append({
                'id': group.id,
                'name': group.name,
                'code': group.code,
                'group_type': group.group_type,
                'parent': None,
                'event_environment': group.event_environment_id,
                'event_environment_code': group.event_environment.code if group.event_environment_id else '',
                'event_environment_name': group.event_environment.name if group.event_environment_id else '',
                'description': group.description,
                'sort_order': group.sort_order,
                'resource_count': env_counts.get(group.id, 0),
                'children': children,
            })
        return Response(tree)


class TaskResourceViewSet(EventWallModelViewSetMixin, RBACPermissionMixin, viewsets.ModelViewSet):
    serializer_class = TaskResourceSerializer
    search_fields = ['name', 'ip_address', 'description', 'cluster__name']
    event_module = 'ops'
    event_resource_type = 'task_resource'
    event_resource_label = '任务执行资源'
    event_resource_name_fields = ('name',)
    event_exclude_fields = ('ssh_password',)
    rbac_permissions = {
        'list': ['ops.task.resource.view'],
        'retrieve': ['ops.task.resource.view'],
        'create': ['ops.task.resource.manage'],
        'update': ['ops.task.resource.manage'],
        'partial_update': ['ops.task.resource.manage'],
        'destroy': ['ops.task.resource.manage'],
        'stats': ['ops.task.resource.view'],
    }

    def get_queryset(self):
        queryset = TaskResource.objects.select_related('environment', 'system', 'cluster').all()
        resource_type = self.request.query_params.get('resource_type')
        status_value = self.request.query_params.get('status')
        environment = self.request.query_params.get('environment')
        system_value = self.request.query_params.get('system')
        search = (self.request.query_params.get('search') or '').strip()
        if resource_type:
            queryset = queryset.filter(resource_type=resource_type)
        if status_value:
            queryset = queryset.filter(status=status_value)
        if environment:
            queryset = queryset.filter(Q(environment_id=environment) | Q(environment__name=environment))
        if system_value:
            queryset = queryset.filter(Q(system_id=system_value) | Q(system__name=system_value))
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search)
                | Q(ip_address__icontains=search)
                | Q(description__icontains=search)
                | Q(cluster__name__icontains=search)
            )
        return queryset.order_by('environment__sort_order', 'system__sort_order', 'resource_type', 'name', 'id')

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user.username)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user.username)

    @action(detail=False, methods=['get'])
    def stats(self, request):
        queryset = TaskResource.objects.select_related('environment', 'system', 'cluster').all()
        environment = request.query_params.get('environment')
        system_value = request.query_params.get('system')
        status_value = request.query_params.get('status')
        search = (request.query_params.get('search') or '').strip()
        if environment:
            queryset = queryset.filter(Q(environment_id=environment) | Q(environment__name=environment))
        if system_value:
            queryset = queryset.filter(Q(system_id=system_value) | Q(system__name=system_value))
        if status_value:
            queryset = queryset.filter(status=status_value)
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search)
                | Q(ip_address__icontains=search)
                | Q(description__icontains=search)
                | Q(cluster__name__icontains=search)
            )
        return Response({
            'total': queryset.count(),
            'host': queryset.filter(resource_type=TaskResource.RESOURCE_HOST).count(),
            'k8s': queryset.filter(resource_type=TaskResource.RESOURCE_K8S).count(),
            'active': queryset.filter(status=TaskResource.STATUS_ACTIVE).count(),
            'warning': queryset.filter(status=TaskResource.STATUS_WARNING).count(),
            'inactive': queryset.filter(status=TaskResource.STATUS_INACTIVE).count(),
        })


class HostTaskTemplateViewSet(EventWallModelViewSetMixin, RBACPermissionMixin, viewsets.ModelViewSet):
    serializer_class = HostTaskTemplateSerializer
    search_fields = ['name', 'description', 'created_by']
    http_method_names = ['get', 'post', 'put', 'patch', 'delete', 'head', 'options']
    event_module = 'ops'
    event_resource_type = 'host_task_template'
    event_resource_label = '主机任务模板'
    event_resource_name_fields = ('name',)
    rbac_permissions = {
        'list': ['ops.task.execute'],
        'retrieve': ['ops.task.execute'],
        'create': ['ops.task.execute'],
        'update': ['ops.task.execute'],
        'partial_update': ['ops.task.execute'],
        'destroy': ['ops.task.execute'],
    }

    def get_queryset(self):
        username = self.request.user.username
        return HostTaskTemplate.objects.filter(Q(is_builtin=True) | Q(created_by=username)).order_by('-is_builtin', 'name', '-id')

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user.username)

    def _validate_editable(self, instance):
        if instance.is_builtin:
            return Response({'detail': '\u5185\u7f6e\u6a21\u677f\u4e0d\u5141\u8bb8\u4fee\u6539\u6216\u5220\u9664'}, status=status.HTTP_400_BAD_REQUEST)
        return None

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        error_response = self._validate_editable(instance)
        if error_response:
            return error_response
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        error_response = self._validate_editable(instance)
        if error_response:
            return error_response
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        error_response = self._validate_editable(instance)
        if error_response:
            return error_response
        return super().destroy(request, *args, **kwargs)


class HostTaskViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = HostTask.objects.prefetch_related('executions').all()
    search_fields = ['name', 'description', 'created_by']
    filterset_fields = ['target_type', 'task_type', 'status', 'created_by', 'trigger_source', 'lifecycle_status', 'risk_level']
    http_method_names = ['get', 'post', 'delete', 'head', 'options']
    rbac_permissions = {
        'list': ['ops.task.execute'],
        'retrieve': ['ops.task.execute'],
        'create': ['ops.task.execute'],
        'destroy': ['ops.task.execute'],
        'rerun': ['ops.task.execute'],
        'cancel': ['ops.task.execute'],
        'batch_cancel': ['ops.task.execute'],
        'execute': ['ops.task.execute'],
        'rename': ['ops.task.execute'],
        'stats': ['ops.task.execute'],
        'host_options': ['ops.task.execute'],
        'resource_options': ['ops.task.execute'],
    }

    def get_serializer_class(self):
        if self.action == 'create':
            return HostTaskSubmitSerializer
        if self.action == 'retrieve':
            return HostTaskDetailSerializer
        return HostTaskSerializer

    def list(self, request, *args, **kwargs):
        mark_stale_running_host_tasks()
        return super().list(request, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        mark_stale_running_host_tasks()
        return super().retrieve(request, *args, **kwargs)

    @action(detail=True, methods=['post'])
    def rename(self, request, pk=None):
        task = self.get_object()
        serializer = HostTaskRenameSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        old_name = task.name
        task.name = serializer.validated_data['name']
        task.save(update_fields=['name', 'updated_at'])
        record_task_center_event(
            task,
            request=request,
            action='rename_task',
            title='重命名任务中心任务',
            summary=f'任务 {old_name} 已重命名为 {task.name}',
        )
        return Response(HostTaskSerializer(task).data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data
        target_type = validated.get('target_type') or HostTask.TARGET_HOST
        trigger_source = validated.get('trigger_source') or HostTask.TRIGGER_SOURCE_MANUAL
        source_context = dict(validated.get('source_context') or {})
        if not source_context.get('source'):
            source_context['source'] = trigger_source
        hosts = []
        k8s_targets = []
        target_label = ''
        if target_type == HostTask.TARGET_K8S:
            k8s_targets = validated.get('k8s_targets') or []
            target_label = f'{len(k8s_targets)} 个 K8s 目标'
        else:
            resource_ids = validated.get('resource_ids') or []
            if resource_ids:
                resource_map = {
                    resource.id: resource
                    for resource in TaskResource.objects.select_related('environment__event_environment', 'system').filter(
                        id__in=resource_ids,
                        resource_type=TaskResource.RESOURCE_HOST,
                    )
                }
                hosts = [resource_map[item] for item in resource_ids if item in resource_map]
                if len(hosts) != len(resource_ids):
                    return Response({'detail': '存在无效的主机资源，请刷新后重试'}, status=status.HTTP_400_BAD_REQUEST)
            else:
                host_ids = validated['host_ids']
                host_map = {host.id: host for host in Host.objects.filter(id__in=host_ids)}
                hosts = [host_map[item] for item in host_ids if item in host_map]
                if len(hosts) != len(host_ids):
                    return Response({'detail': '\u5b58\u5728\u65e0\u6548\u7684\u76ee\u6807\u4e3b\u673a\uff0c\u8bf7\u5237\u65b0\u540e\u91cd\u8bd5'}, status=status.HTTP_400_BAD_REQUEST)
            target_label = f'{len(hosts)} 台主机'

        risk_level = self._infer_risk_level(validated, hosts, k8s_targets)
        selection_filters = dict(validated.get('selection_filters') or {})
        if target_type == HostTask.TARGET_K8S:
            k8s_snapshot = build_k8s_target_snapshot(k8s_targets)
            k8s_environment = self._first_k8s_environment(k8s_targets, k8s_snapshot)
            if k8s_environment:
                source_context.setdefault('resource_environment', k8s_environment)
                source_context.setdefault('environment_name', k8s_environment)
                selection_filters.setdefault('resource_environment', k8s_environment)
                selection_filters.setdefault('environment_name', k8s_environment)
        task = HostTask.objects.create(
            name=validated['name'],
            target_type=target_type,
            task_type=validated['task_type'],
            description=validated.get('description', ''),
            payload=validated.get('payload') or {},
            selection_filters=selection_filters,
            execution_mode=validated.get('execution_mode', HostTask.EXECUTION_MODE_SSH),
            execution_strategy=validated.get('execution_strategy', HostTask.STRATEGY_CONTINUE),
            timeout_seconds=validated.get('timeout_seconds', 15),
            trigger_source=trigger_source,
            lifecycle_status=HostTask.LIFECYCLE_PENDING_EXECUTION,
            risk_level=risk_level,
            source_context=source_context,
            created_by=request.user.username,
            summary='AIOps 任务草稿已创建，等待调度执行' if trigger_source == HostTask.TRIGGER_SOURCE_AIOPS else '\u4efb\u52a1\u5df2\u521b\u5efa\uff0c\u7b49\u5f85\u8c03\u5ea6\u6267\u884c',
        )
        task.correlation_id = f'task-center:{task.id}'
        task.save(update_fields=['correlation_id'])
        if target_type == HostTask.TARGET_K8S:
            start_k8s_task(task, k8s_targets)
        else:
            start_host_task(task, hosts)
        record_task_center_event(
            task,
            request=request,
            action='create_task',
            title='创建任务中心任务',
            summary=f'任务 {task.name} 已创建，目标 {target_label}',
        )
        self._sync_aiops_pending_action_task(task, request.user)
        data = HostTaskDetailSerializer(self.get_queryset().get(pk=task.pk)).data
        return Response(data, status=status.HTTP_201_CREATED)

    def _first_k8s_environment(self, targets, snapshot):
        for item in list(targets or []) + list(snapshot or []):
            environment = item.get('environment_name') or item.get('environment') or item.get('env')
            if environment:
                return environment
        return ''

    def _sync_aiops_pending_action_task(self, task, user):
        source_context = task.source_context or {}
        pending_action_id = source_context.get('pending_action_id')
        if not pending_action_id or source_context.get('source') != 'aiops':
            return
        action = AIOpsPendingAction.objects.filter(
            pk=pending_action_id,
            session__user_id=user.id,
            action_type=AIOpsPendingAction.ACTION_EXECUTE_HOST_TASK,
            mirror_source__isnull=True,
        ).first()
        if not action:
            return
        action.result_payload = {
            **(action.result_payload or {}),
            'draft_ready': True,
            'task_id': task.id,
            'created_task_id': task.id,
            'task_name': task.name,
            'materialized_in_task_center': True,
        }
        if action.status != AIOpsPendingAction.STATUS_EXECUTED:
            action.status = AIOpsPendingAction.STATUS_EXECUTED
        action.save(update_fields=['status', 'result_payload', 'updated_at'])

    def destroy(self, request, *args, **kwargs):
        task = self.get_object()
        if task.status in [HostTask.STATUS_PENDING, HostTask.STATUS_RUNNING]:
            return Response({'detail': '当前任务仍在待执行或执行中，请终止后再删除'}, status=status.HTTP_400_BAD_REQUEST)
        record_task_center_event(
            task,
            request=request,
            actor_username=request.user.username,
            action='delete_task',
            title='删除任务中心历史记录',
            summary=f'任务 {task.name} 的历史记录已删除',
        )
        return super().destroy(request, *args, **kwargs)

    def _infer_risk_level(self, validated, hosts=None, k8s_targets=None):
        hosts = hosts or []
        k8s_targets = k8s_targets or []
        task_type = validated.get('task_type')
        payload = validated.get('payload') or {}
        command = str(payload.get('command') or payload.get('playbook_content') or '').lower()
        destructive_keywords = ['rm -rf', 'mkfs', 'shutdown', 'reboot', 'systemctl restart', 'drop database', 'truncate', 'iptables -f']
        if any(keyword in command for keyword in destructive_keywords):
            return HostTask.RISK_CRITICAL
        if task_type in [HostTask.TASK_RUN_COMMAND, HostTask.TASK_RUN_PLAYBOOK]:
            if len(hosts) > 20 or any(host.environment == 'prod' for host in hosts):
                return HostTask.RISK_HIGH
            return HostTask.RISK_MEDIUM
        if task_type == HostTask.TASK_K8S_SCALE_WORKLOAD:
            return HostTask.RISK_HIGH
        if task_type in [HostTask.TASK_K8S_RESTART_POD, HostTask.TASK_K8S_POD_EXEC]:
            if any(keyword in command for keyword in ['kubectl patch', 'kubectl apply', 'kubectl delete', 'kubectl scale', 'kubectl rollout restart', 'kubectl replace']):
                return HostTask.RISK_HIGH
            if any((target.get('namespace') or '') in ['prod', 'production'] for target in k8s_targets):
                return HostTask.RISK_HIGH
            return HostTask.RISK_MEDIUM
        if any(host.environment == 'prod' for host in hosts):
            return HostTask.RISK_MEDIUM
        return HostTask.RISK_LOW

    @action(detail=False, methods=['get'])
    def stats(self, request):
        mark_stale_running_host_tasks()
        queryset = self.filter_queryset(self.get_queryset())
        total = queryset.count()
        success = queryset.filter(status=HostTask.STATUS_SUCCESS).count()
        partial = queryset.filter(status=HostTask.STATUS_PARTIAL).count()
        failed = queryset.filter(status=HostTask.STATUS_FAILED).count()
        running = queryset.filter(status=HostTask.STATUS_RUNNING).count()
        pending = queryset.filter(status=HostTask.STATUS_PENDING).count()
        canceled = queryset.filter(status=HostTask.STATUS_CANCELED).count()
        aiops_pending = queryset.filter(trigger_source=HostTask.TRIGGER_SOURCE_AIOPS, status=HostTask.STATUS_PENDING).count()
        high_risk = queryset.filter(risk_level__in=[HostTask.RISK_HIGH, HostTask.RISK_CRITICAL]).count()
        by_source = {
            key: queryset.filter(trigger_source=key).count()
            for key, _label in HostTask.TRIGGER_SOURCE_CHOICES
        }
        by_target_type = {
            key: queryset.filter(target_type=key).count()
            for key, _label in HostTask.TARGET_TYPE_CHOICES
        }
        target_total = sum(item.target_count for item in queryset[:50]) if total else 0
        latest = queryset.first()
        rate_base = success + partial + failed + canceled
        success_rate = round(((success + partial) / rate_base) * 100, 1) if rate_base else 0
        return Response({
            'total': total,
            'running': running,
            'pending': pending,
            'success': success,
            'partial': partial,
            'failed': failed,
            'canceled': canceled,
            'aiops_pending': aiops_pending,
            'high_risk': high_risk,
            'by_source': by_source,
            'by_target_type': by_target_type,
            'target_total': target_total,
            'success_rate': success_rate,
            'latest_finished_at': latest.finished_at if latest else None,
        })

    @action(detail=True, methods=['post'])
    def execute(self, request, pk=None):
        task = self.get_object()
        if task.status != HostTask.STATUS_PENDING:
            return Response({'detail': '仅待执行任务可以从任务中心发起执行'}, status=status.HTTP_400_BAD_REQUEST)
        if task.target_type == HostTask.TARGET_K8S:
            targets = self._k8s_targets_from_snapshot(task)
            if not targets:
                return Response({'detail': '没有找到有效的 K8s 目标'}, status=status.HTTP_400_BAD_REQUEST)
            start_k8s_task(task, targets)
            record_task_center_event(
                task,
                request=request,
                action='start_task',
                title='启动任务中心任务',
                summary=f'任务 {task.name} 已从任务中心启动执行',
            )
            return Response(HostTaskDetailSerializer(self.get_queryset().get(pk=task.pk)).data)
        hosts = self._host_targets_from_snapshot(task)
        if not hosts:
            return Response({'detail': '没有找到有效的目标主机'}, status=status.HTTP_400_BAD_REQUEST)
        start_host_task(task, hosts)
        record_task_center_event(
            task,
            request=request,
            action='start_task',
            title='启动任务中心任务',
            summary=f'任务 {task.name} 已从任务中心启动执行',
        )
        return Response(HostTaskDetailSerializer(self.get_queryset().get(pk=task.pk)).data)

    def _k8s_targets_from_snapshot(self, task):
        return [
            {
                'cluster_id': item.get('cluster_id'),
                'cluster_name': item.get('cluster_name') or '',
                'resource_id': item.get('resource_id') or item.get('task_resource_id'),
                'task_resource_id': item.get('task_resource_id') or item.get('resource_id'),
                'resource_name': item.get('resource_name') or '',
                'environment_name': item.get('environment_name') or item.get('environment') or '',
                'event_environment': item.get('event_environment') or item.get('event_environment_code') or '',
                'event_environment_name': item.get('event_environment_name') or '',
                'system_name': item.get('system_name') or '',
                'namespace': item.get('namespace') or '',
                'name': item.get('name') or '',
                'kind': item.get('kind') or '',
                'container': item.get('container') or '',
            }
            for item in (task.target_snapshot or [])
            if item.get('cluster_id')
        ]

    def _host_targets_from_snapshot(self, task):
        refs = []
        legacy_host_ids = []
        for item in (task.target_snapshot or []):
            source = item.get('source') or ''
            if source == 'task_resource' or item.get('resource_id'):
                refs.append({'source': 'task_resource', 'id': item.get('resource_id') or item.get('id')})
            elif item.get('id'):
                legacy_host_ids.append(item.get('id'))
        if refs:
            return resolve_host_source_refs(refs)
        host_map = {host.id: host for host in Host.objects.filter(id__in=legacy_host_ids)}
        return [host_map[item] for item in legacy_host_ids if item in host_map]

    @action(detail=False, methods=['get'])
    def host_options(self, request):
        filters = {
            'search': request.query_params.get('search', ''),
            'status': request.query_params.get('status', ''),
            'business_line': request.query_params.get('business_line', ''),
            'environment': request.query_params.get('environment', ''),
        }
        queryset = build_host_target_queryset(filters)
        data = HostTaskTargetSerializer(queryset[:200], many=True).data
        return Response(data)

    @action(detail=False, methods=['get'])
    def resource_options(self, request):
        queryset = TaskResource.objects.select_related('environment', 'system', 'cluster').all()
        resource_type = request.query_params.get('resource_type') or ''
        if resource_type:
            queryset = queryset.filter(resource_type=resource_type)
        environment = request.query_params.get('environment') or ''
        system_value = request.query_params.get('system') or request.query_params.get('business_line') or ''
        status_value = request.query_params.get('status') or ''
        search = (request.query_params.get('search') or '').strip()
        if environment:
            queryset = queryset.filter(Q(environment_id=environment) | Q(environment__name=environment))
        if system_value:
            queryset = queryset.filter(Q(system_id=system_value) | Q(system__name=system_value))
        if status_value:
            queryset = queryset.filter(status=status_value)
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search)
                | Q(ip_address__icontains=search)
                | Q(description__icontains=search)
                | Q(cluster__name__icontains=search)
            )
        data = TaskResourceSerializer(queryset[:200], many=True).data
        if resource_type == TaskResource.RESOURCE_K8S:
            mapped_cluster_ids = {
                item['cluster']
                for item in data
                if item.get('cluster')
            }
            cluster_queryset = K8sCluster.objects.exclude(id__in=mapped_cluster_ids).order_by('name', 'id')
            if status_value:
                cluster_status = {
                    TaskResource.STATUS_ACTIVE: 'connected',
                    TaskResource.STATUS_INACTIVE: 'disconnected',
                    TaskResource.STATUS_WARNING: 'error',
                }.get(status_value, status_value)
                cluster_queryset = cluster_queryset.filter(status=cluster_status)
            if search:
                cluster_queryset = cluster_queryset.filter(
                    Q(name__icontains=search)
                    | Q(api_server__icontains=search)
                    | Q(description__icontains=search)
                )
            cluster_options = [
                self._k8s_cluster_resource_option(cluster)
                for cluster in cluster_queryset[: max(200 - len(data), 0)]
            ]
            data = list(data) + cluster_options
        return Response(data)

    def _k8s_cluster_resource_option(self, cluster):
        status_map = {
            'connected': (TaskResource.STATUS_ACTIVE, '可用'),
            'disconnected': (TaskResource.STATUS_INACTIVE, '停用'),
            'error': (TaskResource.STATUS_WARNING, '异常'),
        }
        status_value, status_display = status_map.get(cluster.status, (TaskResource.STATUS_WARNING, cluster.get_status_display()))
        return {
            'id': f'cluster:{cluster.id}',
            'name': cluster.name,
            'hostname': cluster.name,
            'resource_type': TaskResource.RESOURCE_K8S,
            'resource_type_display': 'K8s',
            'environment': None,
            'environment_name': '',
            'environment_display': '',
            'system': None,
            'system_name': '',
            'business_line': '',
            'status': status_value,
            'status_display': status_display,
            'ip_address': None,
            'ssh_port': 22,
            'ssh_user': '',
            'cluster': cluster.id,
            'cluster_id': cluster.id,
            'cluster_name': cluster.name,
            'namespace': 'default',
            'endpoint': cluster.api_server or cluster.name,
            'owner': '',
            'admin_user': '',
            'description': cluster.description or cluster.api_server or 'K8s 集群',
            'metadata': {'source': 'k8s_cluster'},
            'created_by': '',
            'updated_by': '',
            'created_at': cluster.created_at,
            'updated_at': cluster.updated_at,
        }

    @action(detail=True, methods=['post'])
    def rerun(self, request, pk=None):
        source = self.get_object()
        hosts = []
        k8s_targets = []
        if source.target_type == HostTask.TARGET_K8S:
            k8s_targets = self._k8s_targets_from_snapshot(source)
            if not k8s_targets:
                return Response({'detail': '没有找到有效的 K8s 目标'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            hosts = self._host_targets_from_snapshot(source)
            if not hosts:
                return Response({'detail': '\u6ca1\u6709\u627e\u5230\u6709\u6548\u7684\u76ee\u6807\u4e3b\u673a'}, status=status.HTTP_400_BAD_REQUEST)

        rerun_task = HostTask.objects.create(
            name=f'{source.name} / \u91cd\u8dd1',
            target_type=source.target_type,
            task_type=source.task_type,
            description=source.description,
            payload=dict(source.payload or {}),
            selection_filters=dict(source.selection_filters or {}),
            execution_mode=source.execution_mode or HostTask.EXECUTION_MODE_SSH,
            execution_strategy=source.execution_strategy,
            timeout_seconds=source.timeout_seconds,
            trigger_source=HostTask.TRIGGER_SOURCE_MANUAL,
            lifecycle_status=HostTask.LIFECYCLE_PENDING_EXECUTION,
            risk_level=source.risk_level,
            source_context={'source': 'manual', 'rerun_source_task_id': source.id},
            created_by=request.user.username,
            summary='\u91cd\u8dd1\u4efb\u52a1\u5df2\u521b\u5efa\uff0c\u7b49\u5f85\u8c03\u5ea6\u6267\u884c',
        )
        rerun_task.correlation_id = source.correlation_id or f'host-task:{source.id}'
        rerun_task.save(update_fields=['correlation_id'])
        if source.target_type == HostTask.TARGET_K8S:
            start_k8s_task(rerun_task, k8s_targets)
            target_label = f'{len(k8s_targets)} 个 K8s 目标'
        else:
            start_host_task(rerun_task, hosts)
            target_label = f'{len(hosts)} 台主机'
        record_task_center_event(
            rerun_task,
            request=request,
            action='rerun_task',
            title='重跑任务中心任务',
            summary=f'任务 {source.name} 已发起重跑，目标 {target_label}',
        )
        data = HostTaskDetailSerializer(self.get_queryset().get(pk=rerun_task.pk)).data
        return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        task = self.get_object()
        if task.status not in [HostTask.STATUS_PENDING, HostTask.STATUS_RUNNING]:
            return Response({'detail': '\u5f53\u524d\u4efb\u52a1\u72b6\u6001\u4e0d\u5141\u8bb8\u7ec8\u6b62'}, status=status.HTTP_400_BAD_REQUEST)
        if task.cancel_requested:
            return Response({'detail': '\u8be5\u4efb\u52a1\u5df2\u63d0\u4ea4\u7ec8\u6b62\u7533\u8bf7'}, status=status.HTTP_400_BAD_REQUEST)
        task.cancel_requested = True
        task.cancel_requested_by = request.user.username
        task.cancel_requested_at = timezone.now()
        task.summary = '\u5df2\u63d0\u4ea4\u7ec8\u6b62\u8bf7\u6c42\uff0c\u7b49\u5f85\u6267\u884c\u5668\u505c\u6b62\u4efb\u52a1'
        if task.status == HostTask.STATUS_PENDING:
            task.status = HostTask.STATUS_CANCELED
            task.lifecycle_status = HostTask.LIFECYCLE_CANCELED
        task.save(update_fields=['status', 'lifecycle_status', 'cancel_requested', 'cancel_requested_by', 'cancel_requested_at', 'summary'])
        record_task_center_event(
            task,
            request=request,
            action='cancel_task',
            title='终止任务中心任务',
            summary=f'任务 {task.name} 已提交终止请求',
        )
        return Response(HostTaskSerializer(task).data)

    @action(detail=False, methods=['post'])
    def batch_cancel(self, request):
        serializer = HostTaskBatchCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = serializer.validated_data['ids']
        queryset = self.get_queryset().filter(id__in=ids, status__in=[HostTask.STATUS_PENDING, HostTask.STATUS_RUNNING])
        tasks = list(queryset)
        if not tasks:
            return Response({'detail': '\u6ca1\u6709\u53ef\u7ec8\u6b62\u7684\u4efb\u52a1'}, status=status.HTTP_400_BAD_REQUEST)
        now = timezone.now()
        queryset.update(
            cancel_requested=True,
            cancel_requested_by=request.user.username,
            cancel_requested_at=now,
            summary='\u5df2\u6279\u91cf\u63d0\u4ea4\u7ec8\u6b62\u8bf7\u6c42\uff0c\u7b49\u5f85\u6267\u884c\u5668\u505c\u6b62\u4efb\u52a1',
        )
        record_event(
            request=request,
            module='ops',
            category='execution',
            action='batch_cancel_task',
            title='\u6279\u91cf\u7ec8\u6b62\u4e3b\u673a\u4efb\u52a1',
            summary=f'\u5df2\u6279\u91cf\u63d0\u4ea4 {len(tasks)} \u4e2a\u4e3b\u673a\u4efb\u52a1\u7684\u7ec8\u6b62\u8bf7\u6c42',
            severity=EventRecord.SEVERITY_WARNING,
            resource_type='host_task_batch',
            resource_id='batch_cancel',
            resource_name='批量终止任务',
            correlation_id=f'host-task-batch-cancel:{now.strftime("%Y%m%d%H%M%S")}',
            metadata={'ids': [item.id for item in tasks]},
        )
        return Response({
            'count': len(tasks),
            'ids': [item.id for item in tasks],
            'detail': f'\u5df2\u63d0\u4ea4 {len(tasks)} \u4e2a\u4efb\u52a1\u7684\u7ec8\u6b62\u8bf7\u6c42',
        })


class HostTaskScheduleViewSet(EventWallModelViewSetMixin, RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = HostTaskSchedule.objects.all()
    serializer_class = HostTaskScheduleSerializer
    search_fields = ['name', 'description', 'created_by', 'updated_by']
    filterset_fields = ['enabled', 'task_type', 'execution_mode', 'schedule_type']
    http_method_names = ['get', 'post', 'put', 'patch', 'delete', 'head', 'options']
    event_module = 'ops'
    event_resource_type = 'host_task_schedule'
    event_resource_label = '主机定时任务'
    event_resource_name_fields = ('name',)
    rbac_permissions = {
        'list': ['ops.host.schedule.view'],
        'retrieve': ['ops.host.schedule.view'],
        'create': ['ops.host.schedule.manage'],
        'update': ['ops.host.schedule.manage'],
        'partial_update': ['ops.host.schedule.manage'],
        'destroy': ['ops.host.schedule.manage'],
        'stats': ['ops.host.schedule.view'],
        'preview_next_runs': ['ops.host.schedule.manage'],
        'toggle_enabled': ['ops.host.schedule.manage'],
        'run_now': ['ops.host.schedule.execute'],
    }

    def get_queryset(self):
        return HostTaskSchedule.objects.order_by('-enabled', 'next_run_at', '-id')

    def _persist_schedule(self, serializer, created=False):
        next_run_at = serializer.validated_data.pop('computed_next_run_at', None)
        actor_field = {'created_by': self.request.user.username} if created else {}
        schedule = serializer.save(updated_by=self.request.user.username, **actor_field)
        hosts = resolve_schedule_hosts(schedule)
        schedule.target_count = len(hosts)
        schedule.target_snapshot = build_schedule_snapshot(hosts)
        schedule.next_run_at = next_run_at if schedule.enabled else None
        schedule.save(update_fields=['updated_by', 'target_count', 'target_snapshot', 'next_run_at', 'updated_at'])
        return schedule

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        schedule = self._persist_schedule(serializer, created=True)
        return Response(self.get_serializer(schedule).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        schedule = self._persist_schedule(serializer, created=False)
        return Response(self.get_serializer(schedule).data)

    def partial_update(self, request, *args, **kwargs):
        kwargs['partial'] = True
        return self.update(request, *args, **kwargs)

    @action(detail=False, methods=['get'])
    def stats(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        now = timezone.now()
        total = queryset.count()
        enabled = queryset.filter(enabled=True).count()
        running = queryset.filter(generated_tasks__status__in=[HostTask.STATUS_PENDING, HostTask.STATUS_RUNNING]).distinct().count()
        due_soon = queryset.filter(enabled=True, next_run_at__isnull=False, next_run_at__lte=now + timedelta(hours=1)).count()
        recent_executions = HostTaskScheduleExecution.objects.filter(schedule__in=queryset, requested_at__gte=now - timedelta(days=7))
        finished_total = recent_executions.filter(status__in=[HostTask.STATUS_SUCCESS, HostTask.STATUS_PARTIAL, HostTask.STATUS_FAILED, HostTask.STATUS_CANCELED]).count()
        success_total = recent_executions.filter(status__in=[HostTask.STATUS_SUCCESS, HostTask.STATUS_PARTIAL]).count()
        success_rate = round((success_total / finished_total) * 100, 1) if finished_total else 0
        latest = recent_executions.order_by('-requested_at').first()
        return Response({
            'total': total,
            'enabled': enabled,
            'disabled': max(total - enabled, 0),
            'running': running,
            'due_soon': due_soon,
            'success_rate': success_rate,
            'latest_requested_at': latest.requested_at if latest else None,
        })

    @action(detail=False, methods=['get', 'post'])
    def preview_next_runs(self, request):
        serializer = HostTaskSchedulePreviewSerializer(data=_build_schedule_preview_input(request))
        serializer.is_valid(raise_exception=True)
        hosts = resolve_schedule_hosts(serializer.validated_data)
        return Response({
            'next_run_at': serializer.validated_data.get('computed_next_run_at'),
            'next_runs': preview_next_runs(serializer.validated_data, count=5),
            'target_count': len(hosts),
            'target_snapshot': build_schedule_snapshot(hosts[:12]),
        })

    @action(detail=True, methods=['post'])
    def toggle_enabled(self, request, pk=None):
        schedule = self.get_object()
        schedule.enabled = not schedule.enabled
        schedule.updated_by = request.user.username
        if schedule.enabled:
            next_runs = preview_next_runs(schedule, count=1)
            schedule.next_run_at = next_runs[0] if next_runs else None
        else:
            schedule.next_run_at = None
        schedule.save(update_fields=['enabled', 'updated_by', 'next_run_at', 'updated_at'])
        schedule_status = '启用' if schedule.enabled else '停用'
        record_event(
            request=request,
            module='ops',
            category='workflow',
            action='toggle_schedule',
            title='\u5207\u6362\u5b9a\u65f6\u4efb\u52a1\u72b6\u6001',
            summary=f'定时任务 {schedule.name} 已{schedule_status}',
            resource_type='host_task_schedule',
            resource_id=schedule.id,
            resource_name=schedule.name,
            correlation_id=f'host-task-schedule:{schedule.id}',
            metadata={'enabled': schedule.enabled, 'next_run_at': schedule.next_run_at},
        )
        return Response(self.get_serializer(schedule).data)

    @action(detail=True, methods=['post'])
    def run_now(self, request, pk=None):
        schedule = self.get_object()
        execution, _task = trigger_schedule(
            schedule,
            actor=request.user.username,
            trigger_source=HostTaskScheduleExecution.TRIGGER_MANUAL,
            scheduled_run=False,
        )
        if not execution:
            return Response(
                {'detail': '\u5f53\u524d\u5df2\u6709\u6267\u884c\u4e2d\u7684\u540c\u540d\u7f16\u6392\uff0c\u5df2\u6309\u5e76\u53d1\u7b56\u7565\u8df3\u8fc7\u672c\u6b21\u89e6\u53d1'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        record_event(
            request=request,
            module='ops',
            category='execution',
            action='run_schedule',
            title='\u624b\u52a8\u89e6\u53d1\u5b9a\u65f6\u4efb\u52a1',
            summary=f'\u5df2\u624b\u52a8\u89e6\u53d1\u5b9a\u65f6\u4efb\u52a1 {schedule.name}',
            result=EventRecord.RESULT_PENDING,
            severity=EventRecord.SEVERITY_WARNING,
            resource_type='host_task_schedule',
            resource_id=schedule.id,
            resource_name=schedule.name,
            correlation_id=f'host-task-schedule:{schedule.id}',
            related_resources=[build_resource('ops', 'host_task', _task.id, _task.name)] if _task else [],
            metadata={'execution_id': execution.id},
        )
        return Response(HostTaskScheduleExecutionSerializer(execution).data, status=status.HTTP_201_CREATED)


class HostTaskScheduleExecutionViewSet(RBACPermissionMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = HostTaskScheduleExecutionSerializer
    search_fields = ['schedule__name', 'summary', 'requested_by', 'host_task__name']
    filterset_fields = ['schedule', 'status', 'trigger_source']
    http_method_names = ['get', 'head', 'options']
    rbac_permissions = {
        'list': ['ops.host.schedule.view'],
        'retrieve': ['ops.host.schedule.view'],
    }

    def get_queryset(self):
        queryset = HostTaskScheduleExecution.objects.select_related('schedule', 'host_task').order_by('-requested_at', '-id')
        schedule_id = self.request.query_params.get('schedule')
        if schedule_id:
            queryset = queryset.filter(schedule_id=schedule_id)
        return queryset

class DeploymentApprovalFlowViewSet(EventWallModelViewSetMixin, RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = DeploymentApprovalFlow.objects.prefetch_related('nodes').all()
    serializer_class = DeploymentApprovalFlowSerializer
    search_fields = ['name', 'description']
    event_module = 'ops'
    event_resource_type = 'deployment_approval_flow'
    event_resource_label = '\u53d1\u5e03\u5ba1\u6279\u6d41'
    event_resource_name_fields = ('name',)
    rbac_permissions = {
        'list': ['ops.deployment.view'],
        'retrieve': ['ops.deployment.view'],
        'create': ['ops.deployment.manage'],
        'update': ['ops.deployment.manage'],
        'partial_update': ['ops.deployment.manage'],
        'destroy': ['ops.deployment.manage'],
    }

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user.username)


def deployment_event_metadata(deployment, **extra):
    metadata = {
        'event_category': 'application_release',
        'service': deployment.app_name,
        'service_name': deployment.app_name,
        'version': deployment.version,
        'release_version': deployment.version,
        'release_name': deployment.release_name,
        'action_type': deployment.action_type,
        'deploy_mode': deployment.deploy_mode,
        'release_strategy': deployment.release_strategy,
        'image': deployment.image,
        'namespace': deployment.namespace,
    }
    metadata.update({key: value for key, value in extra.items() if value not in (None, '')})
    return metadata


class DeploymentViewSet(EventWallModelViewSetMixin, RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = Deployment.objects.select_related(
        'host',
        'docker_host',
        'cluster',
        'approval_flow',
        'previous_success',
        'rollback_source',
        'rerun_source',
    ).prefetch_related('approval_steps').all()
    serializer_class = DeploymentSerializer
    search_fields = ['app_name', 'business_line', 'version', 'image', 'submitter', 'deployer']
    filterset_fields = ['business_line', 'environment', 'deploy_mode', 'approval_status', 'status', 'release_strategy']
    event_module = 'ops'
    event_resource_type = 'deployment'
    event_resource_label = '发布单'
    event_resource_name_fields = ('app_name',)
    rbac_permissions = {
        'list': ['ops.deployment.view'],
        'retrieve': ['ops.deployment.view'],
        'create': ['ops.deployment.manage'],
        'update': ['ops.deployment.manage'],
        'partial_update': ['ops.deployment.manage'],
        'destroy': ['ops.deployment.manage'],
        'approve': ['ops.deployment.approve'],
        'reject': ['ops.deployment.approve'],
        'stop': ['ops.deployment.manage'],
        'start': ['ops.deployment.manage'],
        'remove': ['ops.deployment.manage'],
        'logs': ['ops.deployment.view'],
        'status_detail': ['ops.deployment.view'],
        'rerun': ['ops.deployment.manage'],
        'rollback': ['ops.deployment.manage'],
        'advance_batch': ['ops.deployment.manage'],
    }

    def get_queryset(self):
        return _apply_system_alias_filter(self.request, super().get_queryset(), 'business_line')

    def perform_create(self, serializer):
        deployment = serializer.save(submitter=self.request.user.username)
        _initialize_approval_steps(deployment)
        record_event(
            request=self.request,
            module='ops',
            category='workflow',
            action=deployment.action_type or 'deploy',
            title='提交应用发布单',
            summary=f'发布单 {deployment.app_name} {deployment.version} 已提交',
            result=EventRecord.RESULT_PENDING,
            resource_type='deployment',
            resource_id=deployment.id,
            resource_name=deployment.app_name,
            business_line=deployment.business_line,
            environment=deployment.environment,
            application=deployment.app_name,
            correlation_id=f'deployment:{deployment.id}',
            related_resources=self.eventwall_related_resources(deployment),
            metadata=deployment_event_metadata(deployment),
        )

    def eventwall_should_record(self, action, instance=None):
        return False

    def eventwall_related_resources(self, instance):
        related = []
        if instance.cluster_id:
            related.append(build_resource('ops', 'k8s_cluster', instance.cluster_id, instance.cluster.name))
        if instance.docker_host_id:
            related.append(build_resource('ops', 'docker_host', instance.docker_host_id, instance.docker_host.name))
        if instance.host_id:
            related.append(build_resource('ops', 'host', instance.host_id, instance.host.hostname))
        return related

    def _clone_release(
        self,
        source,
        actor,
        action_type,
        change_summary='',
        previous_success=None,
        rollback_source=None,
        rerun_source=None,
    ):
        deployment = Deployment.objects.create(
            app_name=source.app_name,
            business_line=source.business_line,
            version=source.version,
            image=source.image,
            environment=source.environment,
            deploy_mode=source.deploy_mode,
            release_strategy=source.release_strategy,
            submitter=actor,
            host=source.host,
            docker_host=source.docker_host,
            cluster=source.cluster,
            namespace=source.namespace,
            release_name=source.release_name,
            replicas=source.replicas,
            container_port=source.container_port,
            service_port=source.service_port,
            canary_percent=source.canary_percent,
            batch_total=source.batch_total,
            batch_size=source.batch_size,
            strategy_config=dict(source.strategy_config or {}),
            env_config=dict(source.env_config or {}),
            description=source.description,
            change_summary=change_summary,
            action_type=action_type,
            previous_success=previous_success,
            rollback_source=rollback_source,
            rerun_source=rerun_source,
        )
        _initialize_approval_steps(deployment)
        action_title = '发起版本回滚' if action_type == 'rollback' else '发起重新发布'
        record_event(
            module='ops',
            category='workflow',
            action=action_type,
            title=action_title,
            summary=f'发布单 {deployment.app_name} {deployment.version} 已{("发起回滚" if action_type == "rollback" else "发起重跑")}',
            result=EventRecord.RESULT_PENDING,
            actor_username=actor,
            actor_display=actor,
            actor_type=EventRecord.ACTOR_USER,
            resource_type='deployment',
            resource_id=deployment.id,
            resource_name=deployment.app_name,
            business_line=deployment.business_line,
            environment=deployment.environment,
            application=deployment.app_name,
            correlation_id=f'deployment:{deployment.id}',
            related_resources=self.eventwall_related_resources(deployment),
            metadata=deployment_event_metadata(
                deployment,
                source_deployment_id=getattr(source, 'id', None),
                rollback_source_id=getattr(rollback_source, 'id', None),
                rerun_source_id=getattr(rerun_source, 'id', None),
            ),
        )
        return deployment

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        deployment = self.get_object()
        if deployment.approval_status != 'pending':
            return Response({'detail': '\u53ea\u80fd\u5ba1\u6279\u5f85\u5ba1\u6279\u7684\u53d1\u5e03\u5355'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = ApprovalActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comment = serializer.validated_data.get('comment', '')
        current_step = deployment.current_approval_step
        if current_step and not _match_step_approver(request.user, current_step):
            return Response({'detail': '\u5f53\u524d\u8d26\u53f7\u4e0d\u5728\u8be5\u5ba1\u6279\u8282\u70b9\u7684\u5ba1\u6279\u8303\u56f4\u5185'}, status=status.HTTP_403_FORBIDDEN)

        if current_step:
            current_step.status = 'approved'
            current_step.is_current = False
            current_step.approver = request.user.username
            current_step.comment = comment
            current_step.acted_at = timezone.now()
            current_step.save(update_fields=['status', 'is_current', 'approver', 'comment', 'acted_at'])

            next_step = deployment.approval_steps.filter(status='pending').order_by('node_order', 'id').first()
            deployment.approver = request.user.username
            deployment.approval_comment = comment
            if next_step:
                next_step.is_current = True
                next_step.save(update_fields=['is_current'])
                deployment.save(update_fields=['approver', 'approval_comment'])
                return Response(DeploymentSerializer(deployment).data)

        deployment.approval_status = 'approved'
        deployment.approver = request.user.username
        deployment.approval_comment = comment
        deployment.approved_at = timezone.now()
        deployment.deployer = request.user.username
        deployment.save(update_fields=['approval_status', 'approver', 'approval_comment', 'approved_at', 'deployer'])
        deployer.start_deployment_thread(deployment.id)
        return Response(DeploymentSerializer(deployment).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        deployment = self.get_object()
        if deployment.approval_status != 'pending':
            return Response({'detail': '\u53ea\u80fd\u9a73\u56de\u5f85\u5ba1\u6279\u7684\u53d1\u5e03\u5355'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = ApprovalActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comment = serializer.validated_data.get('comment', '')
        current_step = deployment.current_approval_step
        if current_step and not _match_step_approver(request.user, current_step):
            return Response({'detail': '\u5f53\u524d\u8d26\u53f7\u4e0d\u5728\u8be5\u5ba1\u6279\u8282\u70b9\u7684\u5ba1\u6279\u8303\u56f4\u5185'}, status=status.HTTP_403_FORBIDDEN)

        if current_step:
            current_step.status = 'rejected'
            current_step.is_current = False
            current_step.approver = request.user.username
            current_step.comment = comment
            current_step.acted_at = timezone.now()
            current_step.save(update_fields=['status', 'is_current', 'approver', 'comment', 'acted_at'])
            deployment.approval_steps.filter(status='pending').update(is_current=False)

        deployment.approval_status = 'rejected'
        deployment.status = 'rejected'
        deployment.approver = request.user.username
        deployment.approval_comment = comment
        deployment.approved_at = timezone.now()
        deployment.save(update_fields=['approval_status', 'status', 'approver', 'approval_comment', 'approved_at'])
        record_event(
            request=request,
            module='ops',
            category='workflow',
            action='reject',
            title='驳回发布单',
            summary=f'发布单 {deployment.app_name} 已被驳回',
            result=EventRecord.RESULT_REJECTED,
            severity=EventRecord.SEVERITY_WARNING,
            resource_type='deployment',
            resource_id=deployment.id,
            resource_name=deployment.app_name,
            business_line=deployment.business_line,
            environment=deployment.environment,
            application=deployment.app_name,
            correlation_id=f'deployment:{deployment.id}',
            related_resources=self.eventwall_related_resources(deployment),
            metadata=deployment_event_metadata(deployment, comment=comment),
        )
        return Response(DeploymentSerializer(deployment).data)

    @action(detail=True, methods=['post'])
    def rerun(self, request, pk=None):
        deployment = self.get_object()
        serializer = DeploymentActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_release = self._clone_release(
            deployment,
            actor=request.user.username,
            action_type='rerun',
            change_summary=serializer.validated_data.get('change_summary') or f'重新执行 #{deployment.id}',
            previous_success=deployment if deployment.approval_status == 'approved' and deployment.execution_count else deployment.previous_success,
            rerun_source=deployment,
        )
        return Response(DeploymentSerializer(new_release).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def rollback(self, request, pk=None):
        deployment = self.get_object()
        previous_release = deployment.get_previous_successful_release()
        if not previous_release:
            return Response({'detail': '\u672a\u627e\u5230\u53ef\u56de\u6eda\u7684\u5386\u53f2\u6210\u529f\u7248\u672c'}, status=status.HTTP_400_BAD_REQUEST)
        serializer = DeploymentActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_release = self._clone_release(
            previous_release,
            actor=request.user.username,
            action_type='rollback',
            change_summary=serializer.validated_data.get('change_summary') or f'回滚到 v{previous_release.version}',
            previous_success=deployment if deployment.approval_status == 'approved' and deployment.execution_count else deployment.previous_success,
            rollback_source=deployment,
        )
        return Response(DeploymentSerializer(new_release).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def advance_batch(self, request, pk=None):
        deployment = self.get_object()
        serializer = DeploymentActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            deployer.advance_batch(
                deployment,
                actor=request.user.username,
                change_summary=serializer.validated_data.get('change_summary', ''),
            )
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(DeploymentSerializer(deployment).data)

    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        deployment = self.get_object()
        deployer.stop_service(deployment)
        record_event(
            request=request,
            module='ops',
            category='execution',
            action='stop',
            title='停止应用发布实例',
            summary=f'发布单 {deployment.app_name} 已执行停止操作',
            severity=EventRecord.SEVERITY_WARNING,
            resource_type='deployment',
            resource_id=deployment.id,
            resource_name=deployment.app_name,
            business_line=deployment.business_line,
            environment=deployment.environment,
            application=deployment.app_name,
            correlation_id=f'deployment:{deployment.id}',
            related_resources=self.eventwall_related_resources(deployment),
            metadata=deployment_event_metadata(deployment),
        )
        return Response(DeploymentSerializer(deployment).data)

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        deployment = self.get_object()
        deployer.start_service(deployment)
        record_event(
            request=request,
            module='ops',
            category='execution',
            action='start',
            title='启动应用发布实例',
            summary=f'发布单 {deployment.app_name} 已执行启动操作',
            resource_type='deployment',
            resource_id=deployment.id,
            resource_name=deployment.app_name,
            business_line=deployment.business_line,
            environment=deployment.environment,
            application=deployment.app_name,
            correlation_id=f'deployment:{deployment.id}',
            related_resources=self.eventwall_related_resources(deployment),
            metadata=deployment_event_metadata(deployment),
        )
        return Response(DeploymentSerializer(deployment).data)

    @action(detail=True, methods=['post'])
    def remove(self, request, pk=None):
        deployment = self.get_object()
        deployer.remove_service(deployment)
        record_event(
            request=request,
            module='ops',
            category='execution',
            action='remove',
            title='下线应用发布实例',
            summary=f'发布单 {deployment.app_name} 已执行下线操作',
            severity=EventRecord.SEVERITY_WARNING,
            resource_type='deployment',
            resource_id=deployment.id,
            resource_name=deployment.app_name,
            business_line=deployment.business_line,
            environment=deployment.environment,
            application=deployment.app_name,
            correlation_id=f'deployment:{deployment.id}',
            related_resources=self.eventwall_related_resources(deployment),
            metadata=deployment_event_metadata(deployment),
        )
        return Response(DeploymentSerializer(deployment).data)

    @action(detail=True, methods=['get'])
    def logs(self, request, pk=None):
        deployment = self.get_object()
        tail = int(request.query_params.get('tail', 100))
        return Response({'logs': deployer.get_service_logs(deployment, tail=tail)})

    @action(detail=True, methods=['get'])
    def status_detail(self, request, pk=None):
        deployment = self.get_object()
        return Response(deployer.get_service_status(deployment))


class TransactionTicketViewSet(EventWallModelViewSetMixin, RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = TransactionTicket.objects.select_related('approval_flow').all()
    serializer_class = TransactionTicketSerializer
    search_fields = ['title', 'description', 'owner', 'applicant']
    filterset_fields = ['ticket_type', 'priority', 'status', 'business_line', 'environment']
    event_module = 'ops'
    event_resource_type = 'transaction_ticket'
    event_resource_label = '事务工单'
    event_resource_name_fields = ('title',)
    rbac_permissions = {
        'list': ['ops.ticket.view'],
        'retrieve': ['ops.ticket.view'],
        'create': ['ops.ticket.manage'],
        'update': ['ops.ticket.manage'],
        'partial_update': ['ops.ticket.manage'],
        'destroy': ['ops.ticket.manage'],
        'approve': ['ops.ticket.approve'],
        'reject': ['ops.ticket.approve'],
        'start_process': ['ops.ticket.manage'],
        'complete': ['ops.ticket.manage'],
    }

    def get_queryset(self):
        return _apply_system_alias_filter(self.request, super().get_queryset(), 'business_line')

    def perform_create(self, serializer):
        serializer.save(applicant=self.request.user.username)

    def eventwall_metadata(self, instance, action, before=None, after=None):
        return {
            'ticket_type': instance.ticket_type,
            'priority': instance.priority,
            'status': instance.status,
            'owner': instance.owner,
            'applicant': instance.applicant,
        }

    def _transition_ticket(self, request, ticket, *, target_status, action, title, summary, severity=EventRecord.SEVERITY_INFO):
        ticket.status = target_status
        if action == 'start_process' and not ticket.owner:
            ticket.owner = request.user.username
            ticket.save(update_fields=['status', 'owner', 'updated_at'])
        else:
            ticket.save(update_fields=['status', 'updated_at'])
        record_event(
            request=request,
            module='ops',
            category='workflow',
            action=action,
            title=title,
            summary=summary,
            result=EventRecord.RESULT_SUCCESS if target_status != TransactionTicket.STATUS_REJECTED else EventRecord.RESULT_FAILED,
            severity=severity,
            resource_type='transaction_ticket',
            resource_id=ticket.id,
            resource_name=ticket.title,
            business_line=ticket.business_line,
            environment=ticket.environment,
            correlation_id=f'transaction-ticket:{ticket.id}',
            metadata={'status': ticket.status, 'owner': ticket.owner, 'ticket_type': ticket.ticket_type},
            related_resources=(
                [build_resource('ops', 'deployment_approval_flow', ticket.approval_flow_id, ticket.approval_flow.name)]
                if ticket.approval_flow_id else []
            ),
        )
        return Response(self.get_serializer(ticket).data)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        ticket = self.get_object()
        if ticket.status != TransactionTicket.STATUS_PENDING:
            return Response({'detail': '仅待审批工单支持通过操作'}, status=status.HTTP_400_BAD_REQUEST)
        return self._transition_ticket(
            request,
            ticket,
            target_status=TransactionTicket.STATUS_APPROVED,
            action='approve',
            title='通过事务工单',
            summary=f'事务工单 {ticket.title} 已审批通过',
        )

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        ticket = self.get_object()
        if ticket.status != TransactionTicket.STATUS_PENDING:
            return Response({'detail': '仅待审批工单支持驳回操作'}, status=status.HTTP_400_BAD_REQUEST)
        return self._transition_ticket(
            request,
            ticket,
            target_status=TransactionTicket.STATUS_REJECTED,
            action='reject',
            title='驳回事务工单',
            summary=f'事务工单 {ticket.title} 已被驳回',
            severity=EventRecord.SEVERITY_WARNING,
        )

    @action(detail=True, methods=['post'])
    def start_process(self, request, pk=None):
        ticket = self.get_object()
        if ticket.status != TransactionTicket.STATUS_APPROVED:
            return Response({'detail': '仅已通过工单支持开始处理'}, status=status.HTTP_400_BAD_REQUEST)
        return self._transition_ticket(
            request,
            ticket,
            target_status=TransactionTicket.STATUS_PROCESSING,
            action='start_process',
            title='开始处理事务工单',
            summary=f'事务工单 {ticket.title} 已进入处理中',
        )

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        ticket = self.get_object()
        if ticket.status != TransactionTicket.STATUS_PROCESSING:
            return Response({'detail': '仅处理中工单支持完成操作'}, status=status.HTTP_400_BAD_REQUEST)
        return self._transition_ticket(
            request,
            ticket,
            target_status=TransactionTicket.STATUS_DONE,
            action='complete',
            title='完成事务工单',
            summary=f'事务工单 {ticket.title} 已处理完成',
        )


class AlertViewSet(EventWallModelViewSetMixin, RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = Alert.objects.select_related('host', 'integration').prefetch_related('actions', 'claim_records', 'notification_logs__channel', 'notification_logs__rule').all()
    serializer_class = AlertSerializer
    search_fields = ['title', 'source', 'message', 'host__hostname', 'service', 'resource', 'business_line', 'cluster', 'namespace']
    filterset_fields = ['level', 'status', 'source_type', 'source', 'is_acknowledged', 'is_suppressed', 'service', 'environment', 'cluster', 'namespace', 'region', 'business_line', 'claimed_by']
    event_module = 'ops'
    event_resource_type = 'alert'
    event_resource_label = '告警'
    event_resource_name_fields = ('title',)
    event_exclude_fields = ('raw_payload',)
    rbac_permissions = {
        'list': ['ops.alert.view'],
        'retrieve': ['ops.alert.view'],
        'create': ['ops.alert.manage'],
        'update': ['ops.alert.manage'],
        'partial_update': ['ops.alert.manage'],
        'destroy': ['ops.alert.manage'],
        'summary': ['ops.alert.view'],
        'groups': ['ops.alert.view'],
        'acknowledge': ['ops.alert.manage'],
        'claim': ['ops.alert.manage'],
        'unclaim': ['ops.alert.manage'],
        'mute': ['ops.alert.manage'],
        'escalate': ['ops.alert.manage'],
        'resolve': ['ops.alert.manage'],
        'close': ['ops.alert.manage'],
        'reopen': ['ops.alert.manage'],
        'notify': ['ops.alert.notify'],
    }

    def get_queryset(self):
        queryset = super().get_queryset().order_by('-last_received_at', '-created_at', '-id')
        queryset = _apply_system_alias_filter(self.request, queryset, 'business_line', 'host__business_line')
        params = self.request.query_params
        claimed = params.get('claimed')
        if claimed is None:
            claimed = params.get('ack')
        if claimed in {'0', 'false', 'False'}:
            queryset = queryset.filter(claim_records__isnull=True).distinct()
        elif claimed in {'1', 'true', 'True'}:
            queryset = queryset.exclude(claim_records__isnull=True).distinct()
        if params.get('only_open') in {'1', 'true', 'True'}:
            queryset = queryset.exclude(status__in=[Alert.STATUS_RESOLVED, Alert.STATUS_CLOSED])
        resource = params.get('resource')
        if resource:
            queryset = queryset.filter(Q(resource__icontains=resource) | Q(host__hostname__icontains=resource))
        label_key = params.get('label_key')
        label_value = params.get('label_value')
        if label_key and label_value:
            matched_ids = [
                alert.id for alert in queryset[:5000]
                if str((alert.labels or {}).get(label_key, '')) == str(label_value)
            ]
            queryset = Alert.objects.filter(id__in=matched_ids)
        return queryset

    @action(detail=False, methods=['get'])
    def summary(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        return Response(alert_summary(queryset[:5000]))

    @action(detail=False, methods=['get'])
    def groups(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        group_by = [item.strip() for item in request.query_params.get('group_by', '').split(',') if item.strip()]
        return Response(alert_group_summary(queryset, group_by=group_by or None))

    def _actor(self, request):
        return request.user.username if request.user and request.user.is_authenticated else ''

    def _action_response(self, request, action_name, note='', metadata=None, mute_minutes=60):
        alert = self.get_object()
        apply_alert_action(
            alert,
            action_name,
            actor=self._actor(request),
            note=note,
            metadata=metadata or {},
            request=request,
            mute_minutes=mute_minutes,
        )
        alert.refresh_from_db()
        record_event(
            request=request,
            module='ops',
            category='alert',
            action=action_name,
            title=f'告警{dict(AlertAction.ACTION_CHOICES).get(action_name, action_name)}',
            summary=f'{request.user.username} 对告警 {alert.title} 执行 {action_name}',
            resource_type='alert',
            resource_id=alert.id,
            resource_name=alert.title,
            severity=EventRecord.SEVERITY_WARNING if action_name in {AlertAction.ACTION_ESCALATE, AlertAction.ACTION_MUTE} else EventRecord.SEVERITY_INFO,
            correlation_id=f'alert:{alert.id}',
        )
        return Response(self.get_serializer(alert).data)

    @action(detail=True, methods=['post'])
    def acknowledge(self, request, pk=None):
        return self._action_response(request, AlertAction.ACTION_ACKNOWLEDGE, note=request.data.get('note', ''))

    @action(detail=True, methods=['post'])
    def claim(self, request, pk=None):
        return self._action_response(request, AlertAction.ACTION_CLAIM, note=request.data.get('note', ''))

    @action(detail=True, methods=['post'])
    def unclaim(self, request, pk=None):
        return self._action_response(request, AlertAction.ACTION_UNCLAIM, note=request.data.get('note', ''))

    @action(detail=True, methods=['post'])
    def mute(self, request, pk=None):
        try:
            mute_minutes = int(request.data.get('minutes') or 60)
        except (TypeError, ValueError):
            mute_minutes = 60
        return self._action_response(request, AlertAction.ACTION_MUTE, note=request.data.get('note', ''), mute_minutes=max(mute_minutes, 1))

    @action(detail=True, methods=['post'])
    def escalate(self, request, pk=None):
        return self._action_response(request, AlertAction.ACTION_ESCALATE, note=request.data.get('note', ''))

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        return self._action_response(request, AlertAction.ACTION_RESOLVE, note=request.data.get('note', ''))

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        return self._action_response(request, AlertAction.ACTION_CLOSE, note=request.data.get('note', ''))

    @action(detail=True, methods=['post'])
    def reopen(self, request, pk=None):
        return self._action_response(request, AlertAction.ACTION_REOPEN, note=request.data.get('note', ''))

    @action(detail=True, methods=['post'])
    def notify(self, request, pk=None):
        alert = self.get_object()
        logs = dispatch_alert_notifications(alert, action=request.data.get('action') or 'fire', request=request, force=True)
        return Response({'sent': len(logs), 'logs': AlertNotificationLogSerializer(logs, many=True).data})


class AlertIntegrationViewSet(EventWallModelViewSetMixin, RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = AlertIntegration.objects.all()
    serializer_class = AlertIntegrationSerializer
    search_fields = ['name', 'provider', 'description']
    event_module = 'ops'
    event_resource_type = 'alert_integration'
    event_resource_label = '告警接入源'
    event_resource_name_fields = ('name',)
    event_exclude_fields = ('secret', 'token')
    rbac_permissions = {
        'list': ['ops.alert.config.view'],
        'retrieve': ['ops.alert.config.view'],
        'create': ['ops.alert.config.manage'],
        'update': ['ops.alert.config.manage'],
        'partial_update': ['ops.alert.config.manage'],
        'destroy': ['ops.alert.config.manage'],
    }


class AlertRecipientViewSet(EventWallModelViewSetMixin, RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = AlertRecipient.objects.select_related('user').all()
    serializer_class = AlertRecipientSerializer
    search_fields = ['name', 'phone', 'email', 'description']
    event_module = 'ops'
    event_resource_type = 'alert_recipient'
    event_resource_label = '告警接收人'
    event_resource_name_fields = ('name',)
    rbac_permissions = {
        'list': ['ops.alert.config.view'],
        'retrieve': ['ops.alert.config.view'],
        'create': ['ops.alert.config.manage'],
        'update': ['ops.alert.config.manage'],
        'partial_update': ['ops.alert.config.manage'],
        'destroy': ['ops.alert.config.manage'],
    }


class AlertRecipientGroupViewSet(EventWallModelViewSetMixin, RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = AlertRecipientGroup.objects.prefetch_related('recipients', 'users').all()
    serializer_class = AlertRecipientGroupSerializer
    search_fields = ['name', 'description']
    event_module = 'ops'
    event_resource_type = 'alert_recipient_group'
    event_resource_label = '告警接收组'
    event_resource_name_fields = ('name',)
    rbac_permissions = {
        'list': ['ops.alert.config.view'],
        'retrieve': ['ops.alert.config.view'],
        'create': ['ops.alert.config.manage'],
        'update': ['ops.alert.config.manage'],
        'partial_update': ['ops.alert.config.manage'],
        'destroy': ['ops.alert.config.manage'],
    }


class AlertNotificationChannelViewSet(EventWallModelViewSetMixin, RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = AlertNotificationChannel.objects.all()
    serializer_class = AlertNotificationChannelSerializer
    search_fields = ['name', 'channel_type']
    event_module = 'ops'
    event_resource_type = 'alert_notification_channel'
    event_resource_label = '告警通知渠道'
    event_resource_name_fields = ('name',)
    event_exclude_fields = ('config',)
    rbac_permissions = {
        'list': ['ops.alert.config.view'],
        'retrieve': ['ops.alert.config.view'],
        'create': ['ops.alert.config.manage'],
        'update': ['ops.alert.config.manage'],
        'partial_update': ['ops.alert.config.manage'],
        'destroy': ['ops.alert.config.manage'],
        'test': ['ops.alert.notify'],
    }

    @action(detail=True, methods=['post'])
    def test(self, request, pk=None):
        channel = self.get_object()
        alert = Alert.objects.order_by('-created_at').first()
        if not alert:
            alert = Alert.objects.create(
                title='告警通知测试',
                level='info',
                source='SxDevOps',
                source_type=Alert.SOURCE_GENERIC,
                message='这是一条用于验证通知渠道的测试告警。',
                status=Alert.STATUS_ACTIVE,
            )
        temp_rule = AlertNotificationRule(name='渠道测试', is_enabled=True)
        logs = []
        from .alerting import send_alert_notification
        logs.append(send_alert_notification(channel, alert, {'names': ['渠道测试']}, action='test', rule=None, request=request))
        return Response(AlertNotificationLogSerializer(logs, many=True).data)


class AlertAggregationRuleViewSet(EventWallModelViewSetMixin, RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = AlertAggregationRule.objects.all()
    serializer_class = AlertAggregationRuleSerializer
    search_fields = ['name', 'description']
    event_module = 'ops'
    event_resource_type = 'alert_aggregation_rule'
    event_resource_label = '告警聚合规则'
    event_resource_name_fields = ('name',)
    rbac_permissions = {
        'list': ['ops.alert.config.view'],
        'retrieve': ['ops.alert.config.view'],
        'create': ['ops.alert.config.manage'],
        'update': ['ops.alert.config.manage'],
        'partial_update': ['ops.alert.config.manage'],
        'destroy': ['ops.alert.config.manage'],
    }


class AlertInhibitionRuleViewSet(EventWallModelViewSetMixin, RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = AlertInhibitionRule.objects.all()
    serializer_class = AlertInhibitionRuleSerializer
    search_fields = ['name', 'description']
    event_module = 'ops'
    event_resource_type = 'alert_inhibition_rule'
    event_resource_label = '告警抑制规则'
    event_resource_name_fields = ('name',)
    rbac_permissions = {
        'list': ['ops.alert.config.view'],
        'retrieve': ['ops.alert.config.view'],
        'create': ['ops.alert.config.manage'],
        'update': ['ops.alert.config.manage'],
        'partial_update': ['ops.alert.config.manage'],
        'destroy': ['ops.alert.config.manage'],
    }


class AlertMuteRuleViewSet(EventWallModelViewSetMixin, RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = AlertMuteRule.objects.all()
    serializer_class = AlertMuteRuleSerializer
    search_fields = ['name', 'reason']
    event_module = 'ops'
    event_resource_type = 'alert_mute_rule'
    event_resource_label = '告警屏蔽规则'
    event_resource_name_fields = ('name',)
    rbac_permissions = {
        'list': ['ops.alert.config.view'],
        'retrieve': ['ops.alert.config.view'],
        'create': ['ops.alert.config.manage'],
        'update': ['ops.alert.config.manage'],
        'partial_update': ['ops.alert.config.manage'],
        'destroy': ['ops.alert.config.manage'],
    }

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user.username)


class AlertEscalationPolicyViewSet(EventWallModelViewSetMixin, RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = AlertEscalationPolicy.objects.all()
    serializer_class = AlertEscalationPolicySerializer
    search_fields = ['name', 'description']
    event_module = 'ops'
    event_resource_type = 'alert_escalation_policy'
    event_resource_label = '告警升级策略'
    event_resource_name_fields = ('name',)
    rbac_permissions = {
        'list': ['ops.alert.config.view'],
        'retrieve': ['ops.alert.config.view'],
        'create': ['ops.alert.config.manage'],
        'update': ['ops.alert.config.manage'],
        'partial_update': ['ops.alert.config.manage'],
        'destroy': ['ops.alert.config.manage'],
    }


class AlertNotificationRuleViewSet(EventWallModelViewSetMixin, RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = AlertNotificationRule.objects.select_related('aggregation_rule', 'escalation_policy').prefetch_related('channels', 'recipients', 'recipient_groups').all()
    serializer_class = AlertNotificationRuleSerializer
    search_fields = ['name', 'description']
    event_module = 'ops'
    event_resource_type = 'alert_notification_rule'
    event_resource_label = '告警通知规则'
    event_resource_name_fields = ('name',)
    rbac_permissions = {
        'list': ['ops.alert.config.view'],
        'retrieve': ['ops.alert.config.view'],
        'create': ['ops.alert.config.manage'],
        'update': ['ops.alert.config.manage'],
        'partial_update': ['ops.alert.config.manage'],
        'destroy': ['ops.alert.config.manage'],
    }


class AlertNotificationLogViewSet(RBACPermissionMixin, viewsets.ReadOnlyModelViewSet):
    queryset = AlertNotificationLog.objects.select_related('alert', 'rule', 'channel').all()
    serializer_class = AlertNotificationLogSerializer
    search_fields = ['recipient_summary', 'response_body', 'error_message']
    filterset_fields = ['alert', 'rule', 'channel', 'action', 'status']
    rbac_permissions = {
        'list': ['ops.alert.view'],
        'retrieve': ['ops.alert.view'],
    }


class AlertActionViewSet(RBACPermissionMixin, viewsets.ReadOnlyModelViewSet):
    queryset = AlertAction.objects.select_related('alert').all()
    serializer_class = AlertActionSerializer
    search_fields = ['actor', 'note', 'action']
    filterset_fields = ['alert', 'action', 'actor']
    rbac_permissions = {
        'list': ['ops.alert.view'],
        'retrieve': ['ops.alert.view'],
    }


@api_view(['POST'])
@permission_classes([AllowAny])
def alert_webhook(request, provider, token=''):
    provider = normalize_provider(provider)
    supplied_token = (
        token
        or request.query_params.get('token')
        or request.headers.get('X-Alert-Token')
        or request.headers.get('X-Sxdevops-Token')
        or request.headers.get('X-SxDevOps-Token')
    )
    if provider != Alert.SOURCE_GENERIC and not supplied_token:
        return Response({'detail': '该告警接入源必须携带有效令牌。'}, status=status.HTTP_403_FORBIDDEN)
    integration = resolve_integration(provider, supplied_token)
    if supplied_token and not integration:
        return Response({'detail': '告警接入源令牌无效或已禁用。'}, status=status.HTTP_403_FORBIDDEN)
    result = ingest_webhook(provider, request.data, integration=integration, request=request)
    return Response({
        'success': True,
        'provider': provider,
        'created': result['created'],
        'updated': result['updated'],
        'alert_ids': [alert.id for alert in result['alerts']],
    }, status=status.HTTP_202_ACCEPTED)


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def alert_card_action(request, token):
    ok, message, alert = handle_interaction_token(token, request=request)
    http_status = status.HTTP_200_OK if ok else status.HTTP_400_BAD_REQUEST
    return Response({'success': ok, 'message': message, 'alert_id': alert.id if alert else None}, status=http_status)


class LogEntryViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = LogEntry.objects.select_related('host').all()
    serializer_class = LogEntrySerializer
    search_fields = ['service', 'message']
    rbac_permissions = {
        'list': ['ops.log.entry.view'],
        'retrieve': ['ops.log.entry.view'],
        'create': ['ops.log.entry.manage'],
        'update': ['ops.log.entry.manage'],
        'partial_update': ['ops.log.entry.manage'],
        'destroy': ['ops.log.entry.manage'],
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.dashboard.view')])
def dashboard_stats(request):
    host_total = Host.objects.count()
    host_status = dict(Host.objects.values_list('status').annotate(count=Count('id')).values_list('status', 'count'))
    host_avg = Host.objects.aggregate(
        avg_cpu=Avg('cpu_usage'),
        avg_memory=Avg('memory_usage'),
        avg_disk=Avg('disk_usage'),
    )

    deploy_total = Deployment.objects.count()
    deploy_running = Deployment.objects.filter(status='running', is_current=True).count()
    deploy_failed = Deployment.objects.filter(status__in=['failed', 'rejected']).count()
    deploy_success = Deployment.objects.filter(status__in=['running', 'stopped', 'removed']).count()

    alert_total = Alert.objects.count()
    alert_unacked = Alert.objects.filter(claim_records__isnull=True).distinct().count()
    alert_levels = dict(Alert.objects.values_list('level').annotate(count=Count('id')).values_list('level', 'count'))

    recent_deploys = DeploymentSerializer(
        Deployment.objects.select_related('host', 'docker_host', 'cluster', 'approval_flow').prefetch_related('approval_steps').all()[:10],
        many=True,
    ).data
    recent_alerts = AlertSerializer(
        Alert.objects.select_related('host').prefetch_related('claim_records').filter(claim_records__isnull=True)[:10],
        many=True,
    ).data

    return Response({
        'hosts': {
            'total': host_total,
            'online': host_status.get('online', 0),
            'offline': host_status.get('offline', 0),
            'warning': host_status.get('warning', 0),
            'avg_cpu': round(host_avg['avg_cpu'] or 0, 1),
            'avg_memory': round(host_avg['avg_memory'] or 0, 1),
            'avg_disk': round(host_avg['avg_disk'] or 0, 1),
        },
        'deployments': {
            'total': deploy_total,
            'success': deploy_success,
            'failed': deploy_failed,
            'running': deploy_running,
        },
        'alerts': {
            'total': alert_total,
            'unacknowledged': alert_unacked,
            'critical': alert_levels.get('critical', 0),
            'warning': alert_levels.get('warning', 0),
            'info': alert_levels.get('info', 0),
        },
        'recent_deploys': recent_deploys,
        'recent_alerts': recent_alerts,
    })



