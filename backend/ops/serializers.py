import re
import uuid

from django.contrib.auth import get_user_model
from rest_framework import serializers

from cmdb.models import CIRelation, ConfigItem, ResourceNode

from .host_task_schedules import CronExpressionError, compute_next_run, preview_next_runs, validate_cron_expression
from .models import (
    Alert,
    AlertAction,
    AlertAggregationRule,
    AlertClaim,
    AlertEscalationPolicy,
    AlertInhibitionRule,
    AlertIntegration,
    AlertInteractionToken,
    AlertMuteRule,
    AlertNotificationChannel,
    AlertNotificationLog,
    AlertNotificationRule,
    AlertRecipient,
    AlertRecipientGroup,
    Deployment,
    DeploymentApprovalFlow,
    DeploymentApprovalNode,
    DeploymentApprovalStep,
    DockerHost,
    GrafanaSetting,
    Host,
    HostTask,
    HostTaskExecution,
    HostTaskSchedule,
    HostTaskScheduleExecution,
    HostTaskTemplate,
    K8sCluster,
    LogDataSource,
    LogEntry,
    MetricDataSource,
    NginxCertificate,
    NginxDomain,
    NginxEnvironment,
    NginxRoute,
    ObservabilityDataSourceLink,
    TracingDataSource,
    TransactionTicket,
    TaskResource,
    TaskResourceGroup,
)


User = get_user_model()

LOG_SENSITIVE_KEYS = {
    'password',
    'api_key',
    'token',
    'bearer_token',
    'access_key_id',
    'access_key_secret',
    'authorization',
    'client_secret',
}

METRIC_SENSITIVE_KEYS = {
    'password',
    'prometheus.password',
    'token',
    'bearer_token',
    'api_key',
    'authorization',
    'client_secret',
}


def normalize_json_object(value):
    return value if isinstance(value, dict) else {}


def validate_host_task_payload(task_type, payload):
    payload = normalize_json_object(payload)
    if task_type == HostTask.TASK_RUN_COMMAND and not (payload.get('command') or '').strip():
        raise serializers.ValidationError({'payload': '请填写需要执行的命令'})
    if task_type == HostTask.TASK_RUN_PLAYBOOK and not (payload.get('playbook_content') or '').strip():
        raise serializers.ValidationError({'payload': '请填写 Playbook 内容'})
    if task_type == HostTask.TASK_SERVICE_STATUS and not (payload.get('service_name') or '').strip():
        raise serializers.ValidationError({'payload': '请填写需要巡检的服务名'})
    if task_type == HostTask.TASK_K8S_POD_EXEC and not (payload.get('command') or '').strip():
        raise serializers.ValidationError({'payload': '请填写需要在 Pod 内执行的命令'})
    if task_type == HostTask.TASK_K8S_SCALE_WORKLOAD:
        workload_type = (payload.get('workload_type') or '').strip().lower()
        if workload_type not in ('deployment', 'statefulset'):
            raise serializers.ValidationError({'payload': 'K8s 伸缩任务仅支持 Deployment 或 StatefulSet'})
        try:
            replicas = int(payload.get('replicas'))
        except (TypeError, ValueError):
            raise serializers.ValidationError({'payload': '请填写合法的副本数'})
        if replicas < 0:
            raise serializers.ValidationError({'payload': '副本数不能小于 0'})
    return payload


def normalize_schedule_hosts(value):
    value = value or []
    return list(dict.fromkeys(int(item) for item in value if item))


def validate_schedule_definition(attrs, instance=None):
    schedule_type = attrs.get('schedule_type') or getattr(instance, 'schedule_type', HostTaskSchedule.SCHEDULE_TYPE_CRON)
    timezone_name = attrs.get('timezone') or getattr(instance, 'timezone', 'Asia/Shanghai')
    cron_expression = (attrs.get('cron_expression') if 'cron_expression' in attrs else getattr(instance, 'cron_expression', '')) or ''
    interval_seconds = attrs.get('interval_seconds') if 'interval_seconds' in attrs else getattr(instance, 'interval_seconds', None)
    run_at = attrs.get('run_at') if 'run_at' in attrs else getattr(instance, 'run_at', None)

    if schedule_type == HostTaskSchedule.SCHEDULE_TYPE_CRON:
        if not str(cron_expression).strip():
            raise serializers.ValidationError({'cron_expression': '请填写 Cron 表达式'})
        try:
            validate_cron_expression(cron_expression)
        except CronExpressionError as exc:
            raise serializers.ValidationError({'cron_expression': str(exc)}) from exc
        attrs['interval_seconds'] = None
    elif schedule_type == HostTaskSchedule.SCHEDULE_TYPE_INTERVAL:
        if not interval_seconds:
            raise serializers.ValidationError({'interval_seconds': '请填写间隔秒数'})
        if int(interval_seconds) < 60:
            raise serializers.ValidationError({'interval_seconds': '间隔任务至少间隔 60 秒'})
        attrs['cron_expression'] = ''
    elif schedule_type == HostTaskSchedule.SCHEDULE_TYPE_ONCE:
        if not run_at:
            raise serializers.ValidationError({'run_at': '请选择执行时间'})
        attrs['cron_expression'] = ''
        attrs['interval_seconds'] = None
    else:
        raise serializers.ValidationError({'schedule_type': '不支持的调度类型'})

    preview_source = {
        'schedule_type': schedule_type,
        'cron_expression': attrs.get('cron_expression', cron_expression),
        'interval_seconds': attrs.get('interval_seconds', interval_seconds),
        'run_at': attrs.get('run_at', run_at),
        'timezone': timezone_name,
    }
    attrs['computed_next_run_at'] = compute_next_run(preview_source)
    return attrs


class HostSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    environment_display = serializers.SerializerMethodField()

    class Meta:
        model = Host
        fields = '__all__'

    def get_environment_display(self, obj):
        return obj.get_environment_display() if obj.environment else ''

    def validate(self, attrs):
        business_line = (attrs.get('business_line') if 'business_line' in attrs else getattr(self.instance, 'business_line', '')) or ''
        environment = (attrs.get('environment') if 'environment' in attrs else getattr(self.instance, 'environment', '')) or ''

        business_line = business_line.strip()
        if business_line and not ResourceNode.objects.filter(node_type='biz', name=business_line).exists():
            raise serializers.ValidationError({'business_line': '所选系统未在资源树中配置'})

        if environment:
            if not business_line:
                raise serializers.ValidationError({'environment': '请先选择系统'})
            if not ResourceNode.objects.filter(node_type='env', parent__name=business_line, name=environment).exists():
                raise serializers.ValidationError({'environment': '所选环境未在当前系统下配置'})

        attrs['business_line'] = business_line
        return attrs


class LogDataSourceSerializer(serializers.ModelSerializer):
    provider_display = serializers.CharField(source='get_provider_display', read_only=True)

    class Meta:
        model = LogDataSource
        fields = '__all__'


class TracingDataSourceSerializer(serializers.ModelSerializer):
    provider_display = serializers.CharField(source='get_provider_display', read_only=True)

    class Meta:
        model = TracingDataSource
        fields = '__all__'


class MetricDataSourceSerializer(serializers.ModelSerializer):
    provider_display = serializers.CharField(source='get_provider_display', read_only=True)

    class Meta:
        model = MetricDataSource
        fields = '__all__'


class ObservabilityDataSourceLinkSerializer(serializers.ModelSerializer):
    log_datasource_name = serializers.CharField(source='log_datasource.name', read_only=True)
    tracing_datasource_name = serializers.CharField(source='tracing_datasource.name', read_only=True)

    class Meta:
        model = ObservabilityDataSourceLink
        fields = '__all__'


class GrafanaSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = GrafanaSetting
        fields = '__all__'


class DockerHostSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = DockerHost
        fields = '__all__'
        extra_kwargs = {
            'ssh_password': {
                'write_only': True,
                'required': False,
                'allow_blank': True,
            },
        }


class K8sClusterSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = K8sCluster
        fields = [
            'id',
            'name',
            'api_server',
            'kubeconfig',
            'status',
            'status_display',
            'description',
            'created_at',
            'updated_at',
        ]
        extra_kwargs = {
            'kubeconfig': {
                'write_only': True,
                'required': False,
                'allow_blank': True,
            },
        }


class TaskResourceGroupSerializer(serializers.ModelSerializer):
    group_type_display = serializers.CharField(source='get_group_type_display', read_only=True)
    parent_name = serializers.CharField(source='parent.name', read_only=True)
    event_environment_code = serializers.CharField(source='event_environment.code', read_only=True)
    event_environment_name = serializers.CharField(source='event_environment.name', read_only=True)

    class Meta:
        model = TaskResourceGroup
        fields = [
            'id',
            'name',
            'code',
            'group_type',
            'group_type_display',
            'parent',
            'parent_name',
            'event_environment',
            'event_environment_code',
            'event_environment_name',
            'description',
            'sort_order',
            'created_by',
            'updated_by',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['created_by', 'updated_by', 'created_at', 'updated_at']

    def validate(self, attrs):
        group_type = attrs.get('group_type') or getattr(self.instance, 'group_type', '')
        parent = attrs.get('parent') if 'parent' in attrs else getattr(self.instance, 'parent', None)
        name = (attrs.get('name') if 'name' in attrs else getattr(self.instance, 'name', '')) or ''
        attrs['name'] = name.strip()
        attrs['code'] = ((attrs.get('code') if 'code' in attrs else getattr(self.instance, 'code', '')) or '').strip()
        if not attrs['name']:
            raise serializers.ValidationError({'name': '请填写节点名称'})
        if group_type == TaskResourceGroup.GROUP_ENVIRONMENT:
            attrs['parent'] = None
        elif group_type == TaskResourceGroup.GROUP_SYSTEM:
            attrs['event_environment'] = None
            if not parent:
                raise serializers.ValidationError({'parent': '系统必须归属到一个环境'})
            if parent.group_type != TaskResourceGroup.GROUP_ENVIRONMENT:
                raise serializers.ValidationError({'parent': '系统的上级节点必须是环境'})
        else:
            raise serializers.ValidationError({'group_type': '不支持的节点类型'})
        return attrs


class TaskResourceSerializer(serializers.ModelSerializer):
    resource_type_display = serializers.CharField(source='get_resource_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    environment_name = serializers.CharField(source='environment.name', read_only=True)
    system_name = serializers.CharField(source='system.name', read_only=True)
    cluster_name = serializers.CharField(source='cluster.name', read_only=True)
    endpoint = serializers.SerializerMethodField()
    hostname = serializers.CharField(source='name', read_only=True)
    business_line = serializers.CharField(source='system.name', read_only=True)
    admin_user = serializers.CharField(source='owner', read_only=True)
    environment_display = serializers.CharField(source='environment.name', read_only=True)

    class Meta:
        model = TaskResource
        fields = [
            'id',
            'name',
            'hostname',
            'resource_type',
            'resource_type_display',
            'environment',
            'environment_name',
            'environment_display',
            'system',
            'system_name',
            'business_line',
            'status',
            'status_display',
            'ip_address',
            'ssh_port',
            'ssh_user',
            'ssh_password',
            'cluster',
            'cluster_name',
            'namespace',
            'endpoint',
            'owner',
            'admin_user',
            'description',
            'metadata',
            'created_by',
            'updated_by',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['created_by', 'updated_by', 'created_at', 'updated_at']
        extra_kwargs = {
            'name': {'required': False, 'allow_blank': True},
            'ssh_password': {'write_only': True, 'required': False, 'allow_blank': True},
        }

    def to_internal_value(self, data):
        if data.get('resource_type') == TaskResource.RESOURCE_K8S and data.get('ip_address') in ('', None):
            data = data.copy()
            data['ip_address'] = None
        return super().to_internal_value(data)

    def get_endpoint(self, obj):
        if obj.resource_type == TaskResource.RESOURCE_K8S:
            return obj.cluster.name if obj.cluster else ''
        return str(obj.ip_address or '')

    def validate(self, attrs):
        resource_type = attrs.get('resource_type') or getattr(self.instance, 'resource_type', TaskResource.RESOURCE_HOST)
        environment = attrs.get('environment') if 'environment' in attrs else getattr(self.instance, 'environment', None)
        system = attrs.get('system') if 'system' in attrs else getattr(self.instance, 'system', None)
        name = (attrs.get('name') if 'name' in attrs else getattr(self.instance, 'name', '')) or ''
        if resource_type == TaskResource.RESOURCE_K8S and not name.strip():
            cluster_for_name = attrs.get('cluster') if 'cluster' in attrs else getattr(self.instance, 'cluster', None)
            if cluster_for_name:
                name = cluster_for_name.name
        attrs['name'] = name.strip()
        if not attrs['name']:
            raise serializers.ValidationError({'name': '请填写资源名称'})
        if not environment or environment.group_type != TaskResourceGroup.GROUP_ENVIRONMENT:
            raise serializers.ValidationError({'environment': '请选择环境'})
        if system:
            if system.group_type != TaskResourceGroup.GROUP_SYSTEM:
                raise serializers.ValidationError({'system': '请选择系统'})
            if system.parent_id != environment.id:
                raise serializers.ValidationError({'system': '系统必须归属到所选环境'})
        if resource_type == TaskResource.RESOURCE_HOST:
            ip_address = attrs.get('ip_address') if 'ip_address' in attrs else getattr(self.instance, 'ip_address', None)
            if not ip_address:
                raise serializers.ValidationError({'ip_address': '请填写主机 IP'})
            attrs['cluster'] = None
            attrs['namespace'] = ''
        elif resource_type == TaskResource.RESOURCE_K8S:
            cluster = attrs.get('cluster') if 'cluster' in attrs else getattr(self.instance, 'cluster', None)
            if not cluster:
                raise serializers.ValidationError({'cluster': '请选择 K8s 集群'})
            attrs['name'] = cluster.name
            attrs['ip_address'] = None
            attrs['ssh_password'] = ''
            attrs['namespace'] = ''
            attrs['owner'] = ''
        else:
            raise serializers.ValidationError({'resource_type': '不支持的资源类型'})
        return attrs


class HostTaskExecutionSerializer(serializers.ModelSerializer):
    status_display = serializers.SerializerMethodField()

    class Meta:
        model = HostTaskExecution
        fields = [
            'id',
            'target_type',
            'host',
            'host_name',
            'host_ip',
            'target_id',
            'target_name',
            'target_namespace',
            'target_kind',
            'status',
            'status_display',
            'command',
            'output',
            'error_message',
            'duration_ms',
            'started_at',
            'finished_at',
            'created_at',
        ]

    def get_status_display(self, obj):
        if obj.status == 'running':
            return '执行中'
        return obj.get_status_display()


class HostTaskSerializer(serializers.ModelSerializer):
    target_type_display = serializers.CharField(source='get_target_type_display', read_only=True)
    task_type_display = serializers.CharField(source='get_task_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    lifecycle_status_display = serializers.CharField(source='get_lifecycle_status_display', read_only=True)
    risk_level_display = serializers.CharField(source='get_risk_level_display', read_only=True)
    execution_mode_display = serializers.CharField(source='get_execution_mode_display', read_only=True)
    trigger_source_display = serializers.CharField(source='get_trigger_source_display', read_only=True)
    environment_name = serializers.SerializerMethodField()
    environment_display = serializers.SerializerMethodField()
    success_rate = serializers.SerializerMethodField()

    class Meta:
        model = HostTask
        fields = [
            'id',
            'name',
            'target_type',
            'target_type_display',
            'task_type',
            'task_type_display',
            'execution_mode',
            'execution_mode_display',
            'trigger_source',
            'trigger_source_display',
            'environment_name',
            'environment_display',
            'lifecycle_status',
            'lifecycle_status_display',
            'risk_level',
            'risk_level_display',
            'correlation_id',
            'source_context',
            'status',
            'status_display',
            'description',
            'payload',
            'selection_filters',
            'target_snapshot',
            'execution_strategy',
            'timeout_seconds',
            'target_count',
            'success_count',
            'failed_count',
            'skipped_count',
            'success_rate',
            'cancel_requested',
            'cancel_requested_by',
            'cancel_requested_at',
            'created_by',
            'summary',
            'started_at',
            'finished_at',
            'created_at',
            'updated_at',
        ]

    def get_success_rate(self, obj):
        if not obj.target_count:
            return 0
        return round((obj.success_count / obj.target_count) * 100, 1)

    def _environment_values(self, obj):
        values = []

        def append(value):
            text = str(value or '').strip()
            if text and not text.isdigit() and text not in values:
                values.append(text)

        source_context = obj.source_context or {}
        selection_filters = obj.selection_filters or {}
        append(source_context.get('resource_environment'))
        append(source_context.get('environment_name'))
        append(source_context.get('environment'))
        append(source_context.get('knowledge_environment'))
        append(selection_filters.get('environment_name'))
        append(selection_filters.get('resource_environment'))
        append(selection_filters.get('environment'))
        for item in obj.target_snapshot or []:
            append(item.get('environment_name'))
            append(item.get('environment'))
            append(item.get('env'))
        if obj.target_type == HostTask.TARGET_K8S and not values:
            resource_ids = []
            for item in obj.target_snapshot or []:
                for key in ['resource_id', 'task_resource_id', 'cluster_id']:
                    try:
                        value = int(item.get(key) or 0)
                    except (TypeError, ValueError):
                        value = 0
                    if value > 0 and value not in resource_ids:
                        resource_ids.append(value)
            if resource_ids:
                for resource in TaskResource.objects.select_related('environment').filter(
                    id__in=resource_ids,
                    resource_type=TaskResource.RESOURCE_K8S,
                ):
                    append(resource.environment.name if resource.environment_id else '')
        return values

    def get_environment_name(self, obj):
        values = self._environment_values(obj)
        return values[0] if values else ''

    def get_environment_display(self, obj):
        values = self._environment_values(obj)
        if not values:
            return ''
        if len(values) == 1:
            return values[0]
        return f'{values[0]} 等 {len(values)} 个'


class HostTaskDetailSerializer(HostTaskSerializer):
    executions = HostTaskExecutionSerializer(many=True, read_only=True)

    class Meta(HostTaskSerializer.Meta):
        fields = HostTaskSerializer.Meta.fields + ['executions']


class HostTaskTemplateSerializer(serializers.ModelSerializer):
    target_type_display = serializers.CharField(source='get_target_type_display', read_only=True)
    task_type_display = serializers.CharField(source='get_task_type_display', read_only=True)
    execution_mode_display = serializers.CharField(source='get_execution_mode_display', read_only=True)

    class Meta:
        model = HostTaskTemplate
        fields = [
            'id',
            'name',
            'target_type',
            'target_type_display',
            'task_type',
            'task_type_display',
            'execution_mode',
            'execution_mode_display',
            'description',
            'payload',
            'execution_strategy',
            'timeout_seconds',
            'is_builtin',
            'created_by',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['is_builtin', 'created_by', 'created_at', 'updated_at']

    def validate_payload(self, value):
        return normalize_json_object(value)

    def validate(self, attrs):
        task_type = attrs.get('task_type') or getattr(self.instance, 'task_type', '')
        target_type = attrs.get('target_type') or getattr(self.instance, 'target_type', HostTask.TARGET_HOST)
        execution_mode = attrs.get('execution_mode') or getattr(self.instance, 'execution_mode', HostTask.EXECUTION_MODE_SSH)
        validate_host_task_payload(task_type, attrs.get('payload') or {})
        if execution_mode == HostTask.EXECUTION_MODE_K8S_API and not str(task_type).startswith('k8s_'):
            raise serializers.ValidationError({'execution_mode': '只有 K8s 命令可以使用 K8s API'})
        if task_type.startswith('k8s_'):
            attrs['target_type'] = HostTask.TARGET_K8S
            attrs['execution_mode'] = HostTask.EXECUTION_MODE_K8S_API
        elif target_type == HostTask.TARGET_K8S:
            raise serializers.ValidationError({'task_type': 'K8s 资源仅支持 K8s 类型任务'})
        if task_type == HostTask.TASK_RUN_PLAYBOOK:
            attrs['execution_mode'] = HostTask.EXECUTION_MODE_ANSIBLE
        return attrs


class HostTaskSubmitSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=128)
    target_type = serializers.ChoiceField(choices=HostTask.TARGET_TYPE_CHOICES, default=HostTask.TARGET_HOST)
    task_type = serializers.ChoiceField(choices=HostTask.TASK_TYPE_CHOICES)
    description = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    host_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), allow_empty=True, required=False, default=list)
    resource_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), allow_empty=True, required=False, default=list)
    k8s_targets = serializers.ListField(child=serializers.DictField(), allow_empty=True, required=False, default=list)
    payload = serializers.JSONField(required=False, default=dict)
    selection_filters = serializers.JSONField(required=False, default=dict)
    execution_mode = serializers.ChoiceField(choices=HostTask.EXECUTION_MODE_CHOICES, default=HostTask.EXECUTION_MODE_SSH)
    execution_strategy = serializers.ChoiceField(choices=HostTask.STRATEGY_CHOICES, default=HostTask.STRATEGY_CONTINUE)
    timeout_seconds = serializers.IntegerField(min_value=5, max_value=120, default=15)
    trigger_source = serializers.ChoiceField(choices=HostTask.TRIGGER_SOURCE_CHOICES, default=HostTask.TRIGGER_SOURCE_MANUAL, required=False)
    source_context = serializers.JSONField(required=False, default=dict)

    def validate_host_ids(self, value):
        deduplicated = list(dict.fromkeys(value))
        return deduplicated

    def validate_resource_ids(self, value):
        deduplicated = list(dict.fromkeys(value))
        return deduplicated

    def validate_payload(self, value):
        return normalize_json_object(value)

    def validate_source_context(self, value):
        return normalize_json_object(value)

    def validate(self, attrs):
        task_type = attrs.get('task_type')
        target_type = attrs.get('target_type') or HostTask.TARGET_HOST
        execution_mode = attrs.get('execution_mode') or HostTask.EXECUTION_MODE_SSH
        validate_host_task_payload(task_type, attrs.get('payload') or {})
        if execution_mode == HostTask.EXECUTION_MODE_K8S_API and not str(task_type).startswith('k8s_'):
            raise serializers.ValidationError({'execution_mode': '只有 K8s 命令可以使用 K8s API'})
        if target_type == HostTask.TARGET_HOST:
            if task_type.startswith('k8s_'):
                raise serializers.ValidationError({'task_type': '主机资源不支持 K8s 类型任务'})
            if not attrs.get('host_ids') and not attrs.get('resource_ids'):
                raise serializers.ValidationError({'resource_ids': '请至少选择一个主机资源'})
        elif target_type == HostTask.TARGET_K8S:
            if not task_type.startswith('k8s_'):
                raise serializers.ValidationError({'task_type': 'K8s 资源仅支持 K8s 类型任务'})
            targets = attrs.get('k8s_targets') or []
            if not targets:
                raise serializers.ValidationError({'k8s_targets': '请至少选择一个 K8s 目标'})
            cluster_ids = []
            resource_ids = []
            normalized_source_items = []
            for item in targets:
                cluster_id = item.get('cluster_id')
                resource_id = item.get('resource_id') or item.get('task_resource_id')
                name = (item.get('name') or item.get('pod_name') or '').strip()
                namespace = (item.get('namespace') or '').strip()
                kind = (item.get('kind') or item.get('resource_type') or '').strip()
                try:
                    cluster_id = int(cluster_id) if cluster_id else None
                except (TypeError, ValueError):
                    cluster_id = None
                try:
                    resource_id = int(resource_id) if resource_id else None
                except (TypeError, ValueError):
                    resource_id = None
                if not cluster_id:
                    raise serializers.ValidationError({'k8s_targets': '请选择 K8s 集群'})
                cluster_ids.append(cluster_id)
                if resource_id:
                    resource_ids.append(resource_id)
                normalized_source_items.append((item, cluster_id, resource_id, namespace, name, kind))
            cluster_map = {item.id: item for item in K8sCluster.objects.filter(id__in=cluster_ids)}
            resource_map = {
                item.id: item
                for item in TaskResource.objects.select_related('environment__event_environment', 'system', 'cluster').filter(
                    id__in=set(resource_ids + [cluster_id for _item, cluster_id, _resource_id, _namespace, _name, _kind in normalized_source_items]),
                    resource_type=TaskResource.RESOURCE_K8S,
                )
            }
            normalized_targets = []
            for item, cluster_id, resource_id, namespace, name, kind in normalized_source_items:
                resource = resource_map.get(resource_id) or (resource_map.get(cluster_id) if cluster_id not in cluster_map else None)
                cluster = cluster_map.get(cluster_id) or (resource.cluster if resource else None)
                if not cluster and resource:
                    cluster = K8sCluster.objects.filter(name=resource.name).first()
                if not cluster:
                    cluster_name = (item.get('cluster_name') or item.get('name') or '').strip()
                    if cluster_name and not re.fullmatch(r'Cluster\s+\d+', cluster_name, flags=re.IGNORECASE):
                        cluster = K8sCluster.objects.filter(name=cluster_name).first() or K8sCluster.objects.filter(name__icontains=cluster_name).first()
                if not cluster:
                    raise serializers.ValidationError({'k8s_targets': '请选择有效的 K8s 集群'})
                if task_type == HostTask.TASK_K8S_RESTART_POD and not name:
                    raise serializers.ValidationError({'k8s_targets': '请填写 Pod 名称'})
                if task_type == HostTask.TASK_K8S_SCALE_WORKLOAD and not name:
                    raise serializers.ValidationError({'k8s_targets': '请填写工作负载名称'})
                if task_type in [HostTask.TASK_K8S_RESTART_POD, HostTask.TASK_K8S_SCALE_WORKLOAD]:
                    namespace = namespace or 'default'
                if task_type == HostTask.TASK_K8S_POD_EXEC:
                    payload = attrs.get('payload') or {}
                    payload_kind = (payload.get('resource_kind') or '').strip()
                    if payload_kind and payload_kind != 'pod':
                        kind = kind if kind and kind != 'cluster' else payload_kind
                        namespace = namespace or (payload.get('namespace') or '').strip()
                        name = name or (payload.get('service_name') or payload.get('workload_name') or payload.get('resource_name') or '').strip()
                resource_environment = resource.environment.name if resource and resource.environment_id else (item.get('environment_name') or item.get('environment') or '')
                event_environment = item.get('event_environment') or item.get('event_environment_code') or ''
                event_environment_name = item.get('event_environment_name') or ''
                if resource and resource.environment_id and resource.environment.event_environment_id:
                    event_environment = resource.environment.event_environment.code or event_environment
                    event_environment_name = resource.environment.event_environment.name or event_environment_name
                resource_system = resource.system.name if resource and resource.system_id else (item.get('system_name') or item.get('system') or '')
                normalized_targets.append({
                    'cluster_id': cluster.id,
                    'cluster_name': cluster.name,
                    'resource_id': resource.id if resource else resource_id,
                    'task_resource_id': resource.id if resource else resource_id,
                    'resource_name': resource.name if resource else (item.get('resource_name') or ''),
                    'environment_name': resource_environment,
                    'event_environment': event_environment,
                    'event_environment_name': event_environment_name,
                    'system_name': resource_system,
                    'namespace': namespace,
                    'name': name,
                    'kind': kind or ('cluster' if task_type == HostTask.TASK_K8S_POD_EXEC and not name else ''),
                    'container': (item.get('container') or '').strip(),
                })
            attrs['k8s_targets'] = normalized_targets
            attrs['execution_mode'] = HostTask.EXECUTION_MODE_K8S_API
        if task_type == HostTask.TASK_RUN_PLAYBOOK:
            attrs['execution_mode'] = HostTask.EXECUTION_MODE_ANSIBLE
        return attrs


class HostTaskBatchCancelSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(min_value=1), allow_empty=False)

    def validate_ids(self, value):
        deduplicated = list(dict.fromkeys(value))
        if not deduplicated:
            raise serializers.ValidationError('\u8bf7\u81f3\u5c11\u9009\u62e9\u4e00\u4e2a\u4efb\u52a1')
        return deduplicated


class HostTaskRenameSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=128, trim_whitespace=True)

    def validate_name(self, value):
        text = str(value or '').strip()
        if not text:
            raise serializers.ValidationError('请填写任务名称')
        return text


class HostTaskTargetSerializer(serializers.ModelSerializer):
    environment_display = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Host
        fields = [
            'id',
            'hostname',
            'ip_address',
            'business_line',
            'environment',
            'environment_display',
            'admin_user',
            'os_type',
            'status',
            'status_display',
        ]

    def get_environment_display(self, obj):
        return obj.get_environment_display() if obj.environment else ''


class HostTaskScheduleExecutionSerializer(serializers.ModelSerializer):
    schedule_name = serializers.CharField(source='schedule.name', read_only=True)
    host_task_name = serializers.CharField(source='host_task.name', read_only=True)
    trigger_source_display = serializers.CharField(source='get_trigger_source_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = HostTaskScheduleExecution
        fields = [
            'id',
            'schedule',
            'schedule_name',
            'host_task',
            'host_task_name',
            'trigger_source',
            'trigger_source_display',
            'status',
            'status_display',
            'summary',
            'target_count',
            'success_count',
            'failed_count',
            'skipped_count',
            'error_message',
            'requested_by',
            'requested_at',
            'started_at',
            'finished_at',
            'created_at',
        ]


class HostTaskScheduleSerializer(serializers.ModelSerializer):
    task_type_display = serializers.CharField(source='get_task_type_display', read_only=True)
    execution_mode_display = serializers.CharField(source='get_execution_mode_display', read_only=True)
    schedule_type_display = serializers.CharField(source='get_schedule_type_display', read_only=True)
    overlap_policy_display = serializers.CharField(source='get_overlap_policy_display', read_only=True)
    last_status_display = serializers.SerializerMethodField()
    next_runs_preview = serializers.SerializerMethodField()

    class Meta:
        model = HostTaskSchedule
        fields = [
            'id',
            'name',
            'description',
            'enabled',
            'task_type',
            'task_type_display',
            'payload',
            'selection_filters',
            'target_host_ids',
            'target_snapshot',
            'target_count',
            'execution_mode',
            'execution_mode_display',
            'execution_strategy',
            'timeout_seconds',
            'schedule_type',
            'schedule_type_display',
            'cron_expression',
            'interval_seconds',
            'run_at',
            'timezone',
            'overlap_policy',
            'overlap_policy_display',
            'next_run_at',
            'next_runs_preview',
            'last_run_at',
            'last_status',
            'last_status_display',
            'consecutive_failures',
            'total_run_count',
            'last_error',
            'created_by',
            'updated_by',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'target_snapshot',
            'target_count',
            'next_run_at',
            'last_run_at',
            'last_status',
            'consecutive_failures',
            'total_run_count',
            'last_error',
            'created_by',
            'updated_by',
            'created_at',
            'updated_at',
        ]

    def get_last_status_display(self, obj):
        return obj.get_last_status_display() if obj.last_status else ''

    def get_next_runs_preview(self, obj):
        return preview_next_runs(obj, count=3)

    def validate_payload(self, value):
        return normalize_json_object(value)

    def validate_selection_filters(self, value):
        return normalize_json_object(value)

    def validate_target_host_ids(self, value):
        return normalize_schedule_hosts(value)

    def validate(self, attrs):
        task_type = attrs.get('task_type') or getattr(self.instance, 'task_type', '')
        if str(task_type).startswith('k8s_'):
            raise serializers.ValidationError({'task_type': '当前计划任务仍使用主机资源底座，K8s 调度请先通过任务工作台下发'})
        validate_host_task_payload(task_type, attrs.get('payload') if 'payload' in attrs else getattr(self.instance, 'payload', {}))
        if task_type == HostTask.TASK_RUN_PLAYBOOK:
            attrs['execution_mode'] = HostTask.EXECUTION_MODE_ANSIBLE
        return validate_schedule_definition(attrs, instance=self.instance)


class HostTaskSchedulePreviewSerializer(serializers.Serializer):
    task_type = serializers.ChoiceField(choices=HostTask.TASK_TYPE_CHOICES)
    payload = serializers.JSONField(required=False, default=dict)
    selection_filters = serializers.JSONField(required=False, default=dict)
    target_host_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, default=list)
    execution_mode = serializers.ChoiceField(choices=HostTask.EXECUTION_MODE_CHOICES, default=HostTask.EXECUTION_MODE_SSH)
    execution_strategy = serializers.ChoiceField(choices=HostTask.STRATEGY_CHOICES, default=HostTask.STRATEGY_CONTINUE)
    timeout_seconds = serializers.IntegerField(min_value=5, max_value=300, default=15)
    enabled = serializers.BooleanField(required=False, default=True)
    schedule_type = serializers.ChoiceField(choices=HostTaskSchedule.SCHEDULE_TYPE_CHOICES)
    cron_expression = serializers.CharField(required=False, allow_blank=True, default='')
    interval_seconds = serializers.IntegerField(required=False, allow_null=True, min_value=60, max_value=2592000)
    run_at = serializers.DateTimeField(required=False, allow_null=True)
    timezone = serializers.CharField(required=False, allow_blank=True, default='Asia/Shanghai')
    overlap_policy = serializers.ChoiceField(choices=HostTaskSchedule.OVERLAP_POLICY_CHOICES, default=HostTaskSchedule.OVERLAP_SKIP)

    def validate_payload(self, value):
        return normalize_json_object(value)

    def validate_selection_filters(self, value):
        return normalize_json_object(value)

    def validate_target_host_ids(self, value):
        return normalize_schedule_hosts(value)

    def validate(self, attrs):
        if str(attrs.get('task_type') or '').startswith('k8s_'):
            raise serializers.ValidationError({'task_type': '当前计划任务仍使用主机资源底座，K8s 调度请先通过任务工作台下发'})
        validate_host_task_payload(attrs.get('task_type'), attrs.get('payload') or {})
        if attrs.get('task_type') == HostTask.TASK_RUN_PLAYBOOK:
            attrs['execution_mode'] = HostTask.EXECUTION_MODE_ANSIBLE
        return validate_schedule_definition(attrs)

class DeploymentApprovalNodeSerializer(serializers.ModelSerializer):
    approver_type_display = serializers.CharField(source='get_approver_type_display', read_only=True)
    approver_scope_display = serializers.CharField(read_only=True)

    class Meta:
        model = DeploymentApprovalNode
        fields = [
            'id',
            'name',
            'order',
            'approver_type',
            'approver_type_display',
            'approver_value',
            'approver_scope_display',
            'description',
        ]


class DeploymentApprovalStepSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    approver_type_display = serializers.CharField(source='get_approver_type_display', read_only=True)
    approver_scope_display = serializers.CharField(read_only=True)

    class Meta:
        model = DeploymentApprovalStep
        fields = [
            'id',
            'flow',
            'node_name',
            'node_order',
            'approver_type',
            'approver_type_display',
            'approver_value',
            'approver_scope_display',
            'status',
            'status_display',
            'is_current',
            'approver',
            'comment',
            'acted_at',
            'created_at',
        ]


class DeploymentApprovalFlowSerializer(serializers.ModelSerializer):
    environment_display = serializers.SerializerMethodField()
    scope_display = serializers.CharField(read_only=True)
    nodes = DeploymentApprovalNodeSerializer(many=True)
    node_count = serializers.SerializerMethodField()

    class Meta:
        model = DeploymentApprovalFlow
        fields = [
            'id',
            'name',
            'environment',
            'environment_display',
            'scope_display',
            'description',
            'is_active',
            'created_by',
            'node_count',
            'nodes',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['created_by', 'created_at', 'updated_at']

    def get_environment_display(self, obj):
        return obj.get_environment_display() if obj.environment else '全部环境'

    def get_node_count(self, obj):
        return obj.nodes.count()

    def validate_nodes(self, value):
        if not value:
            raise serializers.ValidationError('至少需要配置一个审批节点')
        orders = [item.get('order') for item in value]
        if len(set(orders)) != len(orders):
            raise serializers.ValidationError('审批节点顺序不能重复')
        for item in value:
            if not item.get('name'):
                raise serializers.ValidationError('审批节点名称不能为空')
        return value

    def _sync_active_flow(self, instance):
        if instance.is_active:
            DeploymentApprovalFlow.objects.filter(
                environment=instance.environment,
                is_active=True,
            ).exclude(pk=instance.pk).update(is_active=False)

    def _replace_nodes(self, instance, nodes):
        instance.nodes.all().delete()
        DeploymentApprovalNode.objects.bulk_create([
            DeploymentApprovalNode(
                flow=instance,
                name=item['name'],
                order=item['order'],
                approver_type=item.get('approver_type') or 'user',
                approver_value=item.get('approver_value', ''),
                description=item.get('description', ''),
            )
            for item in sorted(nodes, key=lambda data: (data['order'], data.get('name', '')))
        ])

    def create(self, validated_data):
        nodes = validated_data.pop('nodes', [])
        instance = super().create(validated_data)
        self._replace_nodes(instance, nodes)
        self._sync_active_flow(instance)
        return instance

    def update(self, instance, validated_data):
        nodes = validated_data.pop('nodes', None)
        instance = super().update(instance, validated_data)
        if nodes is not None:
            self._replace_nodes(instance, nodes)
        self._sync_active_flow(instance)
        return instance


class DeploymentSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    environment_display = serializers.CharField(source='get_environment_display', read_only=True)
    deploy_mode_display = serializers.CharField(source='get_deploy_mode_display', read_only=True)
    approval_status_display = serializers.CharField(source='get_approval_status_display', read_only=True)
    action_type_display = serializers.CharField(source='get_action_type_display', read_only=True)
    release_strategy_display = serializers.CharField(source='get_release_strategy_display', read_only=True)
    docker_host_name = serializers.CharField(source='docker_host.name', read_only=True, default='')
    docker_host_ip = serializers.CharField(source='docker_host.ip_address', read_only=True, default='')
    host_name = serializers.CharField(source='host.hostname', read_only=True, default='')
    host_ip = serializers.CharField(source='host.ip_address', read_only=True, default='')
    cluster_name = serializers.CharField(source='cluster.name', read_only=True, default='')
    target_display = serializers.CharField(read_only=True)
    strategy_summary = serializers.CharField(read_only=True)
    approval_progress_text = serializers.CharField(read_only=True)
    approval_flow_name = serializers.CharField(source='approval_flow.name', read_only=True, default='')
    approval_steps = DeploymentApprovalStepSerializer(many=True, read_only=True)
    current_approval_step = serializers.SerializerMethodField()
    previous_success_version = serializers.CharField(source='previous_success.version', read_only=True, default='')
    rollback_source_version = serializers.CharField(source='rollback_source.version', read_only=True, default='')
    rerun_source_version = serializers.CharField(source='rerun_source.version', read_only=True, default='')
    can_rollback = serializers.SerializerMethodField()
    can_advance_batch = serializers.SerializerMethodField()
    cmdb_item_id = serializers.SerializerMethodField()
    cmdb_item_name = serializers.SerializerMethodField()
    cmdb_item_status = serializers.SerializerMethodField()
    cmdb_targets = serializers.SerializerMethodField()

    class Meta:
        model = Deployment
        fields = [
            'id',
            'app_name',
            'business_line',
            'version',
            'image',
            'environment',
            'environment_display',
            'deploy_mode',
            'deploy_mode_display',
            'status',
            'status_display',
            'approval_status',
            'approval_status_display',
            'action_type',
            'action_type_display',
            'release_strategy',
            'release_strategy_display',
            'strategy_summary',
            'canary_percent',
            'batch_total',
            'batch_current',
            'batch_size',
            'strategy_config',
            'submitter',
            'deployer',
            'approver',
            'approval_comment',
            'change_summary',
            'description',
            'env_config',
            'deploy_log',
            'deploy_dir',
            'release_name',
            'namespace',
            'replicas',
            'container_port',
            'service_port',
            'docker_host',
            'docker_host_name',
            'docker_host_ip',
            'host',
            'host_name',
            'host_ip',
            'cluster',
            'cluster_name',
            'target_display',
            'approval_flow',
            'approval_flow_name',
            'approval_progress_text',
            'approval_steps',
            'current_approval_step',
            'previous_success',
            'previous_success_version',
            'rollback_source',
            'rollback_source_version',
            'rerun_source',
            'rerun_source_version',
            'approved_at',
            'executed_at',
            'finished_at',
            'execution_count',
            'is_current',
            'can_rollback',
            'can_advance_batch',
            'cmdb_item_id',
            'cmdb_item_name',
            'cmdb_item_status',
            'cmdb_targets',
            'deployed_at',
        ]
        read_only_fields = [
            'status',
            'approval_status',
            'action_type',
            'submitter',
            'deployer',
            'approver',
            'approval_comment',
            'deploy_log',
            'deploy_dir',
            'approval_flow',
            'previous_success',
            'rollback_source',
            'rerun_source',
            'approved_at',
            'executed_at',
            'finished_at',
            'execution_count',
            'is_current',
            'batch_current',
            'deployed_at',
        ]

    def get_can_rollback(self, obj):
        return bool(obj.is_current and obj.get_previous_successful_release())

    def get_can_advance_batch(self, obj):
        return bool(
            obj.release_strategy == 'batch'
            and obj.approval_status == 'approved'
            and obj.is_current
            and (obj.batch_current or 0) < (obj.batch_total or 1)
        )

    def get_current_approval_step(self, obj):
        step = obj.current_approval_step
        return DeploymentApprovalStepSerializer(step).data if step else None

    def _get_cmdb_item(self, obj):
        cached = getattr(obj, '_cmdb_item_cache', None)
        if cached is not None:
            return cached
        item = ConfigItem.objects.filter(
            attributes__source='app_release',
            attributes__deployment_id=obj.id,
        ).first()
        setattr(obj, '_cmdb_item_cache', item)
        return item

    def get_cmdb_item_id(self, obj):
        item = self._get_cmdb_item(obj)
        return item.id if item else None

    def get_cmdb_item_name(self, obj):
        item = self._get_cmdb_item(obj)
        return item.name if item else ''

    def get_cmdb_item_status(self, obj):
        item = self._get_cmdb_item(obj)
        return item.get_status_display() if item else ''

    def get_cmdb_targets(self, obj):
        item = self._get_cmdb_item(obj)
        if not item:
            return []
        return [
            relation.target.name
            for relation in CIRelation.objects.select_related('target').filter(source=item, relation_type='runs_on')
        ]

    def validate_strategy_config(self, value):
        if value in (None, ''):
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError('策略配置必须为 JSON 对象')
        return value

    def validate_env_config(self, value):
        if value in (None, ''):
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError('环境变量必须为 JSON 对象')
        return value

    def validate(self, attrs):
        business_line = (attrs.get('business_line') or getattr(self.instance, 'business_line', '') or '').strip()
        environment = attrs.get('environment') or getattr(self.instance, 'environment', '')
        deploy_mode = attrs.get('deploy_mode') or getattr(self.instance, 'deploy_mode', 'docker_compose')
        docker_host = attrs.get('docker_host', getattr(self.instance, 'docker_host', None))
        host = attrs.get('host', getattr(self.instance, 'host', None))
        cluster = attrs.get('cluster', getattr(self.instance, 'cluster', None))
        namespace = attrs.get('namespace', getattr(self.instance, 'namespace', ''))
        strategy = attrs.get('release_strategy') or getattr(self.instance, 'release_strategy', 'standard')
        canary_percent = attrs.get('canary_percent', getattr(self.instance, 'canary_percent', 10))
        batch_total = attrs.get('batch_total', getattr(self.instance, 'batch_total', 1))
        batch_size = attrs.get('batch_size', getattr(self.instance, 'batch_size', 1))

        if not business_line:
            raise serializers.ValidationError({'business_line': '请选择系统'})
        biz_node = ResourceNode.objects.filter(node_type='biz', name=business_line).first()
        if not biz_node:
            raise serializers.ValidationError({'business_line': '所选系统未在资源树中配置'})
        if not environment:
            raise serializers.ValidationError({'environment': '请选择环境'})
        if not ResourceNode.objects.filter(node_type='env', parent=biz_node, name=environment).exists():
            raise serializers.ValidationError({'environment': '所选环境未绑定到当前系统'})
        attrs['business_line'] = business_line

        if deploy_mode == 'docker_compose':
            docker_host = docker_host or self._resolve_docker_host_from_legacy(host)
            if not docker_host:
                raise serializers.ValidationError({'docker_host': 'Docker 环境模式必须选择 Docker 环境'})
            attrs['docker_host'] = docker_host
            attrs['host'] = None
            attrs['cluster'] = None
            attrs['namespace'] = ''
        else:
            if not cluster:
                raise serializers.ValidationError({'cluster': 'K8s 集群模式必须选择目标集群'})
            attrs['docker_host'] = None
            attrs['host'] = None
            attrs['namespace'] = (namespace or 'default').strip() or 'default'

        if strategy == 'canary':
            if canary_percent <= 0 or canary_percent > 100:
                raise serializers.ValidationError({'canary_percent': '灰度比例必须在 1-100 之间'})
            attrs['batch_total'] = 1
            attrs['batch_size'] = 1
        elif strategy == 'batch':
            if batch_total < 2:
                raise serializers.ValidationError({'batch_total': '批次发布至少需要 2 个批次'})
            if batch_size < 1:
                raise serializers.ValidationError({'batch_size': '单批规模必须大于 0'})
        else:
            attrs['canary_percent'] = 10
            attrs['batch_total'] = 1
            attrs['batch_size'] = 1

        image = attrs.get('image') or getattr(self.instance, 'image', '')
        app_name = attrs.get('app_name') or getattr(self.instance, 'app_name', '')
        version = attrs.get('version') or getattr(self.instance, 'version', '')
        if not image:
            attrs['image'] = f'{app_name}:{version}'
        return attrs

    def _resolve_docker_host_from_legacy(self, host):
        if not host:
            return None
        docker_host = DockerHost.objects.filter(ip_address=host.ip_address).order_by('id').first()
        if docker_host:
            return docker_host
        docker_host = DockerHost.objects.filter(name=host.hostname).order_by('id').first()
        if docker_host:
            return docker_host
        status_map = {
            'online': 'connected',
            'offline': 'disconnected',
            'warning': 'error',
        }
        return DockerHost.objects.create(
            name=host.hostname,
            ip_address=host.ip_address,
            ssh_port=getattr(host, 'ssh_port', 22) or 22,
            ssh_user=getattr(host, 'ssh_user', 'root') or 'root',
            ssh_password=getattr(host, 'ssh_password', '') or '',
            status=status_map.get(getattr(host, 'status', ''), 'disconnected'),
            description='由应用发布主机目标自动映射',
        )


class ApprovalActionSerializer(serializers.Serializer):
    comment = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')


class DeploymentActionSerializer(serializers.Serializer):
    change_summary = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')


class TransactionTicketSerializer(serializers.ModelSerializer):
    type_display = serializers.CharField(source='get_ticket_type_display', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    environment_display = serializers.CharField(source='get_environment_display', read_only=True)
    approval_flow_name = serializers.CharField(source='approval_flow.name', read_only=True, default='')

    class Meta:
        model = TransactionTicket
        fields = [
            'id',
            'title',
            'ticket_type',
            'type_display',
            'priority',
            'priority_display',
            'business_line',
            'environment',
            'environment_display',
            'approval_flow',
            'approval_flow_name',
            'owner',
            'applicant',
            'window',
            'description',
            'status',
            'status_display',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'applicant',
            'status',
            'created_at',
            'updated_at',
            'type_display',
            'priority_display',
            'status_display',
            'environment_display',
            'approval_flow_name',
        ]

    def validate(self, attrs):
        business_line = (attrs.get('business_line') if 'business_line' in attrs else getattr(self.instance, 'business_line', '')) or ''
        environment = (attrs.get('environment') if 'environment' in attrs else getattr(self.instance, 'environment', '')) or ''

        business_line = business_line.strip()
        if not business_line:
            raise serializers.ValidationError({'business_line': '请选择系统'})
        if not ResourceNode.objects.filter(node_type='biz', name=business_line).exists():
            raise serializers.ValidationError({'business_line': '所选系统未在资源树中配置'})

        if not environment:
            raise serializers.ValidationError({'environment': '请选择环境'})
        if not ResourceNode.objects.filter(node_type='env', parent__name=business_line, name=environment).exists():
            raise serializers.ValidationError({'environment': '所选环境未在当前系统下配置'})

        approval_flow = attrs.get('approval_flow') if 'approval_flow' in attrs else getattr(self.instance, 'approval_flow', None)
        if approval_flow and approval_flow.environment and approval_flow.environment != environment:
            raise serializers.ValidationError({'approval_flow': '所选审批流与当前环境不匹配'})

        attrs['business_line'] = business_line
        return attrs


class AlertUserLiteSerializer(serializers.ModelSerializer):
    display_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'display_name']

    def get_display_name(self, obj):
        full_name = f'{obj.first_name} {obj.last_name}'.strip()
        return full_name or obj.username


class AlertIntegrationSerializer(serializers.ModelSerializer):
    webhook_url = serializers.SerializerMethodField()

    class Meta:
        model = AlertIntegration
        fields = '__all__'

    def get_webhook_url(self, obj):
        request = self.context.get('request')
        path = f'/api/alerts/webhooks/{obj.provider}/{obj.token}/'
        return request.build_absolute_uri(path) if request else path


class AlertRecipientSerializer(serializers.ModelSerializer):
    user_detail = AlertUserLiteSerializer(source='user', read_only=True)

    class Meta:
        model = AlertRecipient
        fields = '__all__'


class AlertRecipientGroupSerializer(serializers.ModelSerializer):
    recipient_ids = serializers.PrimaryKeyRelatedField(queryset=AlertRecipient.objects.all(), many=True, write_only=True, required=False)
    user_ids = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), many=True, write_only=True, required=False)
    recipients = AlertRecipientSerializer(many=True, read_only=True)
    users = AlertUserLiteSerializer(many=True, read_only=True)

    class Meta:
        model = AlertRecipientGroup
        fields = [
            'id', 'name', 'description', 'is_enabled', 'created_at', 'updated_at',
            'recipient_ids', 'user_ids', 'recipients', 'users',
        ]

    def create(self, validated_data):
        recipient_ids = validated_data.pop('recipient_ids', [])
        user_ids = validated_data.pop('user_ids', [])
        instance = super().create(validated_data)
        instance.recipients.set(recipient_ids)
        instance.users.set(user_ids)
        return instance

    def update(self, instance, validated_data):
        recipient_ids = validated_data.pop('recipient_ids', None)
        user_ids = validated_data.pop('user_ids', None)
        instance = super().update(instance, validated_data)
        if recipient_ids is not None:
            instance.recipients.set(recipient_ids)
        if user_ids is not None:
            instance.users.set(user_ids)
        return instance


class AlertNotificationChannelSerializer(serializers.ModelSerializer):
    channel_type_display = serializers.CharField(source='get_channel_type_display', read_only=True)

    class Meta:
        model = AlertNotificationChannel
        fields = '__all__'


class AlertAggregationRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlertAggregationRule
        fields = '__all__'

    def validate_group_by(self, value):
        if value in (None, ''):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError('聚合维度必须是数组。')
        return value


class AlertInhibitionRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlertInhibitionRule
        fields = '__all__'


class AlertMuteRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlertMuteRule
        fields = '__all__'
        read_only_fields = ['created_by', 'created_at', 'updated_at']


class AlertEscalationPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = AlertEscalationPolicy
        fields = '__all__'


class AlertNotificationRuleSerializer(serializers.ModelSerializer):
    channel_ids = serializers.PrimaryKeyRelatedField(queryset=AlertNotificationChannel.objects.all(), many=True, write_only=True, required=False)
    recipient_ids = serializers.PrimaryKeyRelatedField(queryset=AlertRecipient.objects.all(), many=True, write_only=True, required=False)
    recipient_group_ids = serializers.PrimaryKeyRelatedField(queryset=AlertRecipientGroup.objects.all(), many=True, write_only=True, required=False)
    channels = AlertNotificationChannelSerializer(many=True, read_only=True)
    recipients = AlertRecipientSerializer(many=True, read_only=True)
    recipient_groups = AlertRecipientGroupSerializer(many=True, read_only=True)
    aggregation_rule_name = serializers.CharField(source='aggregation_rule.name', read_only=True, default='')
    escalation_policy_name = serializers.CharField(source='escalation_policy.name', read_only=True, default='')

    class Meta:
        model = AlertNotificationRule
        fields = [
            'id', 'name', 'is_enabled', 'matchers', 'min_level', 'aggregation_rule', 'aggregation_rule_name',
            'escalation_policy', 'escalation_policy_name', 'channels', 'recipients', 'recipient_groups',
            'channel_ids', 'recipient_ids', 'recipient_group_ids', 'notify_on_fire', 'notify_on_resolved',
            'notify_on_escalation', 'description', 'created_at', 'updated_at',
        ]

    def create(self, validated_data):
        channel_ids = validated_data.pop('channel_ids', [])
        recipient_ids = validated_data.pop('recipient_ids', [])
        recipient_group_ids = validated_data.pop('recipient_group_ids', [])
        instance = super().create(validated_data)
        instance.channels.set(channel_ids)
        instance.recipients.set(recipient_ids)
        instance.recipient_groups.set(recipient_group_ids)
        return instance

    def update(self, instance, validated_data):
        channel_ids = validated_data.pop('channel_ids', None)
        recipient_ids = validated_data.pop('recipient_ids', None)
        recipient_group_ids = validated_data.pop('recipient_group_ids', None)
        instance = super().update(instance, validated_data)
        if channel_ids is not None:
            instance.channels.set(channel_ids)
        if recipient_ids is not None:
            instance.recipients.set(recipient_ids)
        if recipient_group_ids is not None:
            instance.recipient_groups.set(recipient_group_ids)
        return instance


class AlertNotificationLogSerializer(serializers.ModelSerializer):
    channel_name = serializers.CharField(source='channel.name', read_only=True, default='')
    channel_type = serializers.CharField(source='channel.channel_type', read_only=True, default='')
    rule_name = serializers.CharField(source='rule.name', read_only=True, default='')
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = AlertNotificationLog
        fields = '__all__'


class AlertActionSerializer(serializers.ModelSerializer):
    action_display = serializers.CharField(source='get_action_display', read_only=True)

    class Meta:
        model = AlertAction
        fields = '__all__'


class AlertInteractionTokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlertInteractionToken
        fields = '__all__'


class AlertClaimSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlertClaim
        fields = ['id', 'claimant', 'claimed_at']


class AlertSerializer(serializers.ModelSerializer):
    level_display = serializers.CharField(source='get_level_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    source_type_display = serializers.CharField(source='get_source_type_display', read_only=True)
    host_name = serializers.CharField(source='host.hostname', read_only=True, default='')
    integration_name = serializers.CharField(source='integration.name', read_only=True, default='')
    claimed_by = serializers.SerializerMethodField()
    claimed_at = serializers.SerializerMethodField()
    claimants = serializers.SerializerMethodField()
    claimant_count = serializers.SerializerMethodField()
    current_user_claimed = serializers.SerializerMethodField()
    actions = AlertActionSerializer(many=True, read_only=True)
    recent_notifications = serializers.SerializerMethodField()

    class Meta:
        model = Alert
        fields = '__all__'

    def _claim_records(self, obj):
        records = getattr(obj, '_prefetched_objects_cache', {}).get('claim_records')
        if records is not None:
            return list(records)
        return list(obj.claim_records.all())

    def get_claimed_by(self, obj):
        names = [item.claimant for item in self._claim_records(obj)]
        return '、'.join(names)

    def get_claimed_at(self, obj):
        records = self._claim_records(obj)
        if not records:
            return None
        return records[0].claimed_at

    def get_claimants(self, obj):
        return AlertClaimSerializer(self._claim_records(obj), many=True).data

    def get_claimant_count(self, obj):
        return len(self._claim_records(obj))

    def get_current_user_claimed(self, obj):
        request = self.context.get('request')
        if not request or not request.user or not request.user.is_authenticated:
            return False
        username = request.user.username
        return any(item.claimant == username for item in self._claim_records(obj))

    def get_recent_notifications(self, obj):
        logs = obj.notification_logs.select_related('channel', 'rule').all()[:5]
        return AlertNotificationLogSerializer(logs, many=True).data


class LogEntrySerializer(serializers.ModelSerializer):
    level_display = serializers.CharField(source='get_level_display', read_only=True)
    host_name = serializers.CharField(source='host.hostname', read_only=True, default='')

    class Meta:
        model = LogEntry
        fields = '__all__'


class NginxEnvironmentSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = NginxEnvironment
        fields = '__all__'
        extra_kwargs = {
            'ssh_password': {'write_only': True},
        }


class NginxCertificateSerializer(serializers.ModelSerializer):
    environment_names = serializers.SerializerMethodField()

    class Meta:
        model = NginxCertificate
        fields = '__all__'
        extra_kwargs = {
            'domain': {'read_only': True},
            'expires_at': {'read_only': True},
            'cert_content': {'write_only': True},
            'key_content': {'write_only': True},
        }

    def get_environment_names(self, obj):
        return [{'id': item.id, 'name': item.name} for item in obj.environments.all()]


class NginxDomainSerializer(serializers.ModelSerializer):
    environment_name = serializers.CharField(source='environment.name', read_only=True)
    ssl_enabled = serializers.BooleanField(read_only=True)
    certificate_domain = serializers.CharField(source='certificate.domain', read_only=True, default=None)

    class Meta:
        model = NginxDomain
        fields = '__all__'


class NginxRouteSerializer(serializers.ModelSerializer):
    domain_name = serializers.CharField(source='nginx_domain.domain', read_only=True)
    environment_name = serializers.CharField(source='nginx_domain.environment.name', read_only=True)

    class Meta:
        model = NginxRoute
        fields = '__all__'
