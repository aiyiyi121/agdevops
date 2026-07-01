import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify


def generate_alert_token():
    return uuid.uuid4().hex


class Host(models.Model):
    ENV_CHOICES = [
        ('prod', '\u751f\u4ea7'),
        ('test', '\u6d4b\u8bd5'),
        ('dev', '\u5f00\u53d1'),
    ]

    STATUS_CHOICES = [
        ('online', '\u5728\u7ebf'),
        ('offline', '\u79bb\u7ebf'),
        ('warning', '\u544a\u8b66'),
    ]

    hostname = models.CharField('\u4e3b\u673a\u540d', max_length=128, unique=True)
    ip_address = models.GenericIPAddressField('IP \u5730\u5740')
    business_line = models.CharField('系统', max_length=50, blank=True, default='')
    environment = models.CharField('\u73af\u5883', max_length=20, choices=ENV_CHOICES, blank=True, default='')
    admin_user = models.CharField('\u8d1f\u8d23\u4eba', max_length=50, blank=True, default='')
    os_type = models.CharField('\u64cd\u4f5c\u7cfb\u7edf', max_length=64, default='Linux')
    description = models.CharField('\u63cf\u8ff0', max_length=200, blank=True, default='')
    status = models.CharField('\u72b6\u6001', max_length=16, choices=STATUS_CHOICES, default='online')
    cpu_usage = models.FloatField('CPU \u4f7f\u7528\u7387(%)', default=0)
    memory_usage = models.FloatField('\u5185\u5b58\u4f7f\u7528\u7387(%)', default=0)
    disk_usage = models.FloatField('\u78c1\u76d8\u4f7f\u7528\u7387(%)', default=0)
    ssh_port = models.IntegerField('SSH \u7aef\u53e3', default=22)
    ssh_user = models.CharField('SSH \u7528\u6237', max_length=64, default='root')
    ssh_password = models.CharField('SSH \u5bc6\u7801', max_length=256, blank=True, default='')
    created_at = models.DateTimeField('\u521b\u5efa\u65f6\u95f4', auto_now_add=True)
    updated_at = models.DateTimeField('\u66f4\u65b0\u65f6\u95f4', auto_now=True)

    class Meta:
        verbose_name = '\u4e3b\u673a'
        verbose_name_plural = '\u4e3b\u673a'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.hostname} ({self.ip_address})'


class TaskResourceGroup(models.Model):
    GROUP_ENVIRONMENT = 'environment'
    GROUP_SYSTEM = 'system'
    GROUP_TYPE_CHOICES = [
        (GROUP_ENVIRONMENT, '环境'),
        (GROUP_SYSTEM, '系统'),
    ]

    name = models.CharField('名称', max_length=80)
    code = models.SlugField('编码', max_length=80, blank=True, default='')
    group_type = models.CharField('节点类型', max_length=20, choices=GROUP_TYPE_CHOICES)
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='children',
        verbose_name='上级节点',
    )
    event_environment = models.ForeignKey(
        'eventwall.EventEnvironment',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='task_resource_groups',
        verbose_name='事件中心环境',
    )
    description = models.CharField('说明', max_length=255, blank=True, default='')
    sort_order = models.PositiveIntegerField('排序', default=100)
    created_by = models.CharField('创建人', max_length=64, blank=True, default='system')
    updated_by = models.CharField('更新人', max_length=64, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '任务资源分组'
        verbose_name_plural = '任务资源分组'
        ordering = ['group_type', 'sort_order', 'name', 'id']
        constraints = [
            models.UniqueConstraint(fields=['group_type', 'parent', 'name'], name='uniq_ops_task_resource_group_scope_name'),
        ]
        indexes = [
            models.Index(fields=['group_type', 'parent', 'sort_order']),
        ]

    def __str__(self):
        if self.parent_id:
            return f'{self.parent.name} / {self.name}'
        return self.name


class TaskResource(models.Model):
    RESOURCE_HOST = 'host'
    RESOURCE_K8S = 'k8s'
    RESOURCE_TYPE_CHOICES = [
        (RESOURCE_HOST, '主机'),
        (RESOURCE_K8S, 'K8s'),
    ]

    STATUS_ACTIVE = 'active'
    STATUS_INACTIVE = 'inactive'
    STATUS_WARNING = 'warning'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, '可用'),
        (STATUS_INACTIVE, '停用'),
        (STATUS_WARNING, '异常'),
    ]

    name = models.CharField('资源名称', max_length=128)
    resource_type = models.CharField('资源类型', max_length=16, choices=RESOURCE_TYPE_CHOICES, default=RESOURCE_HOST)
    environment = models.ForeignKey(
        TaskResourceGroup,
        on_delete=models.PROTECT,
        related_name='environment_resources',
        verbose_name='环境',
    )
    system = models.ForeignKey(
        TaskResourceGroup,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='system_resources',
        verbose_name='系统',
    )
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    ip_address = models.GenericIPAddressField('IP 地址', null=True, blank=True)
    ssh_port = models.PositiveIntegerField('SSH 端口', default=22)
    ssh_user = models.CharField('SSH 用户', max_length=64, blank=True, default='root')
    ssh_password = models.CharField('SSH 密码', max_length=256, blank=True, default='')
    cluster = models.ForeignKey('K8sCluster', on_delete=models.SET_NULL, null=True, blank=True, related_name='task_resources', verbose_name='K8s 集群')
    namespace = models.CharField('命名空间', max_length=128, blank=True, default='default')
    owner = models.CharField('负责人', max_length=64, blank=True, default='')
    description = models.CharField('说明', max_length=255, blank=True, default='')
    metadata = models.JSONField('扩展信息', default=dict, blank=True)
    created_by = models.CharField('创建人', max_length=64, blank=True, default='system')
    updated_by = models.CharField('更新人', max_length=64, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '任务执行资源'
        verbose_name_plural = '任务执行资源'
        ordering = ['environment__sort_order', 'system__sort_order', 'resource_type', 'name', 'id']
        indexes = [
            models.Index(fields=['resource_type', 'status']),
            models.Index(fields=['environment', 'system', 'resource_type']),
        ]

    def __str__(self):
        return f'{self.get_resource_type_display()} / {self.name}'


class HostTask(models.Model):
    TARGET_HOST = 'host'
    TARGET_K8S = 'k8s'
    TARGET_TYPE_CHOICES = [
        (TARGET_HOST, '主机资源'),
        (TARGET_K8S, 'K8s 资源'),
    ]

    TASK_CHECK_CONNECTION = 'check_connection'
    TASK_REFRESH_METRICS = 'refresh_metrics'
    TASK_RUN_COMMAND = 'run_command'
    TASK_SERVICE_STATUS = 'service_status'
    TASK_RUN_PLAYBOOK = 'run_playbook'
    TASK_K8S_RESTART_POD = 'k8s_restart_pod'
    TASK_K8S_POD_EXEC = 'k8s_pod_exec'
    TASK_K8S_SCALE_WORKLOAD = 'k8s_scale_workload'
    TASK_TYPE_CHOICES = [
        (TASK_CHECK_CONNECTION, 'SSH 连通性检查'),
        (TASK_REFRESH_METRICS, '主机指标刷新'),
        (TASK_RUN_COMMAND, '批量命令执行'),
        (TASK_RUN_PLAYBOOK, 'Ansible Playbook 执行'),
        (TASK_SERVICE_STATUS, '服务状态巡检'),
        (TASK_K8S_RESTART_POD, 'K8s Pod 重启'),
        (TASK_K8S_POD_EXEC, 'K8s Pod 命令执行'),
        (TASK_K8S_SCALE_WORKLOAD, 'K8s 工作负载伸缩'),
    ]

    STATUS_PENDING = 'pending'
    STATUS_RUNNING = 'running'
    STATUS_SUCCESS = 'success'
    STATUS_PARTIAL = 'partial'
    STATUS_FAILED = 'failed'
    STATUS_CANCELED = 'canceled'
    STATUS_CHOICES = [
        (STATUS_PENDING, '待执行'),
        (STATUS_RUNNING, '执行中'),
        (STATUS_SUCCESS, '执行成功'),
        (STATUS_PARTIAL, '部分成功'),
        (STATUS_FAILED, '执行失败'),
        (STATUS_CANCELED, '已取消'),
    ]

    LIFECYCLE_PENDING_CONFIRMATION = 'pending_confirmation'
    LIFECYCLE_PENDING_APPROVAL = 'pending_approval'
    LIFECYCLE_PENDING_EXECUTION = 'pending_execution'
    LIFECYCLE_RUNNING = 'running'
    LIFECYCLE_SUCCESS = 'success'
    LIFECYCLE_PARTIAL = 'partial'
    LIFECYCLE_FAILED = 'failed'
    LIFECYCLE_CANCELED = 'canceled'
    LIFECYCLE_CHOICES = [
        (LIFECYCLE_PENDING_CONFIRMATION, '待确认'),
        (LIFECYCLE_PENDING_APPROVAL, '待审批'),
        (LIFECYCLE_PENDING_EXECUTION, '待执行'),
        (LIFECYCLE_RUNNING, '执行中'),
        (LIFECYCLE_SUCCESS, '执行成功'),
        (LIFECYCLE_PARTIAL, '部分成功'),
        (LIFECYCLE_FAILED, '执行失败'),
        (LIFECYCLE_CANCELED, '已取消'),
    ]

    RISK_LOW = 'low'
    RISK_MEDIUM = 'medium'
    RISK_HIGH = 'high'
    RISK_CRITICAL = 'critical'
    RISK_CHOICES = [
        (RISK_LOW, '低'),
        (RISK_MEDIUM, '中'),
        (RISK_HIGH, '高'),
        (RISK_CRITICAL, '极高'),
    ]

    STRATEGY_CONTINUE = 'continue'
    STRATEGY_STOP_ON_ERROR = 'stop_on_error'
    STRATEGY_CHOICES = [
        (STRATEGY_CONTINUE, '失败继续'),
        (STRATEGY_STOP_ON_ERROR, '遇错停止'),
    ]

    EXECUTION_MODE_SSH = 'ssh'
    EXECUTION_MODE_ANSIBLE = 'ansible'
    EXECUTION_MODE_K8S_API = 'k8s_api'
    EXECUTION_MODE_CHOICES = [
        (EXECUTION_MODE_SSH, 'SSH'),
        (EXECUTION_MODE_ANSIBLE, 'Ansible'),
        (EXECUTION_MODE_K8S_API, 'K8s API'),
    ]

    TRIGGER_SOURCE_MANUAL = 'manual'
    TRIGGER_SOURCE_SCHEDULE = 'schedule'
    TRIGGER_SOURCE_AIOPS = 'aiops'
    TRIGGER_SOURCE_EVENT_CENTER = 'event_center'
    TRIGGER_SOURCE_API = 'api'
    TRIGGER_SOURCE_CHOICES = [
        (TRIGGER_SOURCE_MANUAL, '手动触发'),
        (TRIGGER_SOURCE_SCHEDULE, '定时触发'),
        (TRIGGER_SOURCE_AIOPS, 'AIOps 生成'),
        (TRIGGER_SOURCE_EVENT_CENTER, '事件中心触发'),
        (TRIGGER_SOURCE_API, 'API 触发'),
    ]

    name = models.CharField('任务名称', max_length=128)
    target_type = models.CharField('目标类型', max_length=16, choices=TARGET_TYPE_CHOICES, default=TARGET_HOST)
    task_type = models.CharField('任务类型', max_length=32, choices=TASK_TYPE_CHOICES)
    status = models.CharField('任务状态', max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    description = models.CharField('任务说明', max_length=255, blank=True, default='')
    payload = models.JSONField('任务载荷', default=dict, blank=True)
    selection_filters = models.JSONField('筛选条件', default=dict, blank=True)
    target_snapshot = models.JSONField('目标快照', default=list, blank=True)
    execution_mode = models.CharField('执行方式', max_length=16, choices=EXECUTION_MODE_CHOICES, default=EXECUTION_MODE_SSH)
    execution_strategy = models.CharField('执行策略', max_length=20, choices=STRATEGY_CHOICES, default=STRATEGY_CONTINUE)
    timeout_seconds = models.PositiveIntegerField('超时(秒)', default=15)
    target_count = models.PositiveIntegerField('目标数量', default=0)
    success_count = models.PositiveIntegerField('成功数量', default=0)
    failed_count = models.PositiveIntegerField('失败数量', default=0)
    skipped_count = models.PositiveIntegerField('跳过数量', default=0)
    cancel_requested = models.BooleanField('已请求取消', default=False)
    cancel_requested_by = models.CharField('取消发起人', max_length=64, blank=True, default='')
    cancel_requested_at = models.DateTimeField('取消时间', null=True, blank=True)
    schedule = models.ForeignKey('HostTaskSchedule', on_delete=models.SET_NULL, null=True, blank=True, related_name='generated_tasks', verbose_name='来源编排')
    trigger_source = models.CharField('触发来源', max_length=16, choices=TRIGGER_SOURCE_CHOICES, default=TRIGGER_SOURCE_MANUAL)
    lifecycle_status = models.CharField('生命周期状态', max_length=32, choices=LIFECYCLE_CHOICES, default=LIFECYCLE_PENDING_EXECUTION)
    risk_level = models.CharField('风险等级', max_length=16, choices=RISK_CHOICES, default=RISK_LOW)
    correlation_id = models.CharField('关联链路', max_length=128, blank=True, default='', db_index=True)
    source_context = models.JSONField('来源上下文', default=dict, blank=True)
    created_by = models.CharField('创建人', max_length=64, default='system')
    summary = models.CharField('执行摘要', max_length=255, blank=True, default='')
    started_at = models.DateTimeField('开始时间', null=True, blank=True)
    finished_at = models.DateTimeField('完成时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '主机任务'
        verbose_name_plural = '主机任务'
        ordering = ['-created_at', '-id']

    def __str__(self):
        return self.name


class HostTaskTemplate(models.Model):
    name = models.CharField('模板名称', max_length=128)
    target_type = models.CharField('目标类型', max_length=16, choices=HostTask.TARGET_TYPE_CHOICES, default=HostTask.TARGET_HOST)
    task_type = models.CharField('任务类型', max_length=32, choices=HostTask.TASK_TYPE_CHOICES)
    description = models.CharField('模板说明', max_length=255, blank=True, default='')
    payload = models.JSONField('模板载荷', default=dict, blank=True)
    execution_mode = models.CharField('执行方式', max_length=16, choices=HostTask.EXECUTION_MODE_CHOICES, default=HostTask.EXECUTION_MODE_SSH)
    execution_strategy = models.CharField('执行策略', max_length=20, choices=HostTask.STRATEGY_CHOICES, default=HostTask.STRATEGY_CONTINUE)
    timeout_seconds = models.PositiveIntegerField('超时(秒)', default=15)
    is_builtin = models.BooleanField('系统内置', default=False)
    created_by = models.CharField('创建人', max_length=64, blank=True, default='system')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '任务模板'
        verbose_name_plural = '任务模板'
        ordering = ['-is_builtin', 'name', '-id']

    def __str__(self):
        return self.name


class HostTaskSchedule(models.Model):
    SCHEDULE_TYPE_ONCE = 'once'
    SCHEDULE_TYPE_INTERVAL = 'interval'
    SCHEDULE_TYPE_CRON = 'cron'
    SCHEDULE_TYPE_CHOICES = [
        (SCHEDULE_TYPE_ONCE, '单次执行'),
        (SCHEDULE_TYPE_INTERVAL, '间隔执行'),
        (SCHEDULE_TYPE_CRON, 'Cron 表达式'),
    ]

    OVERLAP_SKIP = 'skip'
    OVERLAP_ALLOW = 'allow'
    OVERLAP_POLICY_CHOICES = [
        (OVERLAP_SKIP, '跳过重叠执行'),
        (OVERLAP_ALLOW, '允许重叠执行'),
    ]

    name = models.CharField('编排名称', max_length=128)
    description = models.CharField('编排说明', max_length=255, blank=True, default='')
    enabled = models.BooleanField('启用状态', default=True)
    task_type = models.CharField('任务类型', max_length=32, choices=HostTask.TASK_TYPE_CHOICES)
    payload = models.JSONField('任务载荷', default=dict, blank=True)
    selection_filters = models.JSONField('筛选条件', default=dict, blank=True)
    target_host_ids = models.JSONField('指定主机列表', default=list, blank=True)
    target_snapshot = models.JSONField('目标快照', default=list, blank=True)
    target_count = models.PositiveIntegerField('目标数量', default=0)
    execution_mode = models.CharField('执行方式', max_length=16, choices=HostTask.EXECUTION_MODE_CHOICES, default=HostTask.EXECUTION_MODE_SSH)
    execution_strategy = models.CharField('执行策略', max_length=20, choices=HostTask.STRATEGY_CHOICES, default=HostTask.STRATEGY_CONTINUE)
    timeout_seconds = models.PositiveIntegerField('超时(秒)', default=15)
    schedule_type = models.CharField('调度类型', max_length=16, choices=SCHEDULE_TYPE_CHOICES, default=SCHEDULE_TYPE_CRON)
    cron_expression = models.CharField('Cron 表达式', max_length=64, blank=True, default='')
    interval_seconds = models.PositiveIntegerField('间隔秒数', null=True, blank=True)
    run_at = models.DateTimeField('执行时间', null=True, blank=True)
    timezone = models.CharField('时区', max_length=64, default='Asia/Shanghai')
    overlap_policy = models.CharField('重叠策略', max_length=16, choices=OVERLAP_POLICY_CHOICES, default=OVERLAP_SKIP)
    next_run_at = models.DateTimeField('下次执行时间', null=True, blank=True)
    last_run_at = models.DateTimeField('上次执行时间', null=True, blank=True)
    last_status = models.CharField('上次状态', max_length=16, choices=HostTask.STATUS_CHOICES, blank=True, default='')
    consecutive_failures = models.PositiveIntegerField('连续失败次数', default=0)
    total_run_count = models.PositiveIntegerField('累计执行次数', default=0)
    last_error = models.CharField('最近错误', max_length=255, blank=True, default='')
    created_by = models.CharField('创建人', max_length=64, default='system')
    updated_by = models.CharField('更新人', max_length=64, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '定时编排'
        verbose_name_plural = '定时编排'
        ordering = ['-enabled', 'next_run_at', '-id']

    def __str__(self):
        return self.name


class HostTaskScheduleExecution(models.Model):
    TRIGGER_SCHEDULER = 'scheduler'
    TRIGGER_MANUAL = 'manual'
    TRIGGER_SOURCE_CHOICES = [
        (TRIGGER_SCHEDULER, '自动调度'),
        (TRIGGER_MANUAL, '手动执行'),
    ]

    schedule = models.ForeignKey(HostTaskSchedule, on_delete=models.CASCADE, related_name='executions', verbose_name='编排')
    host_task = models.OneToOneField(HostTask, on_delete=models.SET_NULL, null=True, blank=True, related_name='schedule_execution', verbose_name='关联任务')
    trigger_source = models.CharField('触发来源', max_length=16, choices=TRIGGER_SOURCE_CHOICES, default=TRIGGER_SCHEDULER)
    status = models.CharField('执行状态', max_length=16, choices=HostTask.STATUS_CHOICES, default=HostTask.STATUS_PENDING)
    summary = models.CharField('执行摘要', max_length=255, blank=True, default='')
    target_count = models.PositiveIntegerField('目标数量', default=0)
    success_count = models.PositiveIntegerField('成功数量', default=0)
    failed_count = models.PositiveIntegerField('失败数量', default=0)
    skipped_count = models.PositiveIntegerField('跳过数量', default=0)
    error_message = models.CharField('错误信息', max_length=255, blank=True, default='')
    requested_by = models.CharField('发起人', max_length=64, default='system')
    requested_at = models.DateTimeField('发起时间', auto_now_add=True)
    started_at = models.DateTimeField('开始时间', null=True, blank=True)
    finished_at = models.DateTimeField('完成时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '编排执行记录'
        verbose_name_plural = '编排执行记录'
        ordering = ['-requested_at', '-id']

    def __str__(self):
        return f'{self.schedule.name} / {self.requested_at:%Y-%m-%d %H:%M:%S}'


class HostTaskExecution(models.Model):
    STATUS_RUNNING = 'running'
    STATUS_SUCCESS = 'success'
    STATUS_FAILED = 'failed'
    STATUS_SKIPPED = 'skipped'
    STATUS_CHOICES = [
        (STATUS_RUNNING, '执行中'),
        ('success', '成功'),
        ('failed', '失败'),
        ('skipped', '跳过'),
    ]

    task = models.ForeignKey(HostTask, on_delete=models.CASCADE, related_name='executions', verbose_name='任务')
    target_type = models.CharField('目标类型', max_length=16, choices=HostTask.TARGET_TYPE_CHOICES, default=HostTask.TARGET_HOST)
    host = models.ForeignKey(Host, on_delete=models.SET_NULL, null=True, blank=True, related_name='task_executions', verbose_name='主机')
    host_name = models.CharField('主机名', max_length=128, default='')
    host_ip = models.CharField('主机 IP', max_length=128, blank=True, default='')
    target_id = models.CharField('目标 ID', max_length=128, blank=True, default='')
    target_name = models.CharField('目标名称', max_length=255, blank=True, default='')
    target_namespace = models.CharField('目标命名空间', max_length=128, blank=True, default='')
    target_kind = models.CharField('目标类型标识', max_length=64, blank=True, default='')
    status = models.CharField('执行状态', max_length=16, choices=STATUS_CHOICES, default='success')
    command = models.TextField('执行命令', blank=True, default='')
    output = models.TextField('执行输出', blank=True, default='')
    error_message = models.TextField('错误信息', blank=True, default='')
    duration_ms = models.PositiveIntegerField('耗时(毫秒)', default=0)
    started_at = models.DateTimeField('开始时间', null=True, blank=True)
    finished_at = models.DateTimeField('完成时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '主机执行记录'
        verbose_name_plural = '主机执行记录'
        ordering = ['id']

    def __str__(self):
        return f'{self.host_name} - {self.task.name}'

class Deployment(models.Model):
    DEPLOY_MODE_CHOICES = [
        ('docker_compose', 'Docker 环境'),
        ('k8s', 'K8s 集群'),
    ]
    STATUS_CHOICES = [
        ('pending', '待执行'),
        ('rejected', '已驳回'),
        ('deploying', '发布中'),
        ('running', '运行中'),
        ('stopped', '已停止'),
        ('failed', '发布失败'),
        ('removed', '已下线'),
    ]
    APPROVAL_STATUS_CHOICES = [
        ('pending', '待审批'),
        ('approved', '已通过'),
        ('rejected', '已拒绝'),
    ]
    ACTION_TYPE_CHOICES = [
        ('deploy', '应用发布'),
        ('rollback', '版本回滚'),
        ('rerun', '重新执行'),
    ]
    RELEASE_STRATEGY_CHOICES = [
        ('standard', '标准发布'),
        ('canary', '灰度发布'),
        ('batch', '批次发布'),
    ]
    ENV_CHOICES = [
        ('prod', '生产'),
        ('test', '测试'),
        ('dev', '开发'),
    ]

    app_name = models.CharField('应用名称', max_length=128)
    business_line = models.CharField('系统', max_length=50, blank=True, default='')
    version = models.CharField('版本号', max_length=64)
    image = models.CharField('镜像地址', max_length=255, blank=True, default='')
    environment = models.CharField('环境', max_length=32, choices=ENV_CHOICES, default='test')
    deploy_mode = models.CharField('发布模式', max_length=32, choices=DEPLOY_MODE_CHOICES, default='docker_compose')
    status = models.CharField('执行状态', max_length=16, choices=STATUS_CHOICES, default='pending')
    approval_status = models.CharField('审批状态', max_length=16, choices=APPROVAL_STATUS_CHOICES, default='pending')
    action_type = models.CharField('发布类型', max_length=16, choices=ACTION_TYPE_CHOICES, default='deploy')
    release_strategy = models.CharField('发布策略', max_length=16, choices=RELEASE_STRATEGY_CHOICES, default='standard')
    submitter = models.CharField('申请人', max_length=64, default='admin')
    deployer = models.CharField('执行人', max_length=64, blank=True, default='')
    approver = models.CharField('审批人', max_length=64, blank=True, default='')
    approval_comment = models.CharField('审批意见', max_length=255, blank=True, default='')
    change_summary = models.CharField('变更说明', max_length=255, blank=True, default='')
    description = models.TextField('描述', blank=True, default='')
    env_config = models.JSONField('环境变量', default=dict, blank=True)
    deploy_log = models.TextField('发布日志', blank=True, default='')
    deploy_dir = models.CharField('发布目录', max_length=256, blank=True, default='')
    release_name = models.CharField('发布名称', max_length=128, blank=True, default='')
    namespace = models.CharField('命名空间', max_length=128, blank=True, default='')
    replicas = models.PositiveIntegerField('副本数', default=1)
    container_port = models.PositiveIntegerField('容器端口', null=True, blank=True)
    service_port = models.PositiveIntegerField('服务端口', null=True, blank=True)
    canary_percent = models.PositiveIntegerField(
        '灰度比例',
        default=10,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
    )
    batch_total = models.PositiveIntegerField('批次总数', default=1)
    batch_current = models.PositiveIntegerField('当前批次', default=0)
    batch_size = models.PositiveIntegerField('单批规模', default=1)
    strategy_config = models.JSONField('策略配置', default=dict, blank=True)
    host = models.ForeignKey(Host, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='目标主机')
    docker_host = models.ForeignKey(
        'DockerHost',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='deployments',
        verbose_name='Docker 环境',
    )
    cluster = models.ForeignKey('K8sCluster', on_delete=models.SET_NULL, null=True, blank=True, verbose_name='目标集群')
    approval_flow = models.ForeignKey(
        'DeploymentApprovalFlow',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='deployments',
        verbose_name='审批流程',
    )
    previous_success = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='followup_releases',
        verbose_name='上一成功版本',
    )
    rollback_source = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='rollback_requests',
        verbose_name='回滚来源',
    )
    rerun_source = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='rerun_requests',
        verbose_name='重试来源',
    )
    approved_at = models.DateTimeField('审批时间', null=True, blank=True)
    executed_at = models.DateTimeField('执行时间', null=True, blank=True)
    finished_at = models.DateTimeField('完成时间', null=True, blank=True)
    execution_count = models.PositiveIntegerField('执行次数', default=0)
    is_current = models.BooleanField('当前生效版本', default=False)
    deployed_at = models.DateTimeField('发布时间', auto_now_add=True)

    class Meta:
        verbose_name = '应用发布'
        verbose_name_plural = '应用发布'
        ordering = ['-deployed_at']
        indexes = [
            models.Index(fields=['approval_status', 'status']),
            models.Index(fields=['business_line', 'app_name', 'environment', 'deployed_at']),
            models.Index(fields=['is_current', 'deploy_mode']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['business_line', 'app_name', 'environment', 'docker_host'],
                condition=Q(deploy_mode='docker_compose', is_current=True),
                name='uniq_ops_curr_biz_app_docker_host',
            ),
            models.UniqueConstraint(
                fields=['business_line', 'app_name', 'environment', 'cluster', 'namespace'],
                condition=Q(deploy_mode='k8s', is_current=True),
                name='uniq_ops_curr_biz_app_k8s',
            ),
        ]

    def __str__(self):
        return f'{self.app_name} v{self.version} -> {self.environment}'

    @property
    def docker_target(self):
        return self.docker_host or self.host

    @property
    def target_display(self):
        if self.deploy_mode == 'k8s' and self.cluster_id:
            return f'{self.cluster.name} / {self.namespace or "default"}'
        target = self.docker_target
        if target:
            return getattr(target, 'name', '') or getattr(target, 'hostname', '') or '-'
        return '-'

    @property
    def release_name_display(self):
        return self.release_name or slugify(self.app_name) or self.app_name

    @property
    def strategy_summary(self):
        if self.release_strategy == 'canary':
            return f'灰度发布 {self.canary_percent}%'
        if self.release_strategy == 'batch':
            current = min(self.batch_current or 0, self.batch_total or 1)
            return f'批次发布 {current}/{self.batch_total or 1} 批'
        return '标准发布'

    @property
    def approval_progress_text(self):
        steps = list(self.approval_steps.all())
        if not steps:
            return '默认审批'
        approved_count = sum(1 for step in steps if step.status == 'approved')
        return f'{approved_count}/{len(steps)} 节点已完成'

    @property
    def current_approval_step(self):
        current = self.approval_steps.filter(is_current=True).order_by('node_order').first()
        if current:
            return current
        return self.approval_steps.filter(status='pending').order_by('node_order').first()

    def same_target_queryset(self):
        queryset = Deployment.objects.filter(
            business_line=self.business_line,
            app_name=self.app_name,
            environment=self.environment,
            deploy_mode=self.deploy_mode,
        )
        if self.deploy_mode == 'k8s':
            return queryset.filter(cluster=self.cluster, namespace=self.namespace or 'default')
        if self.docker_host_id:
            return queryset.filter(docker_host=self.docker_host)
        if self.host_id:
            return queryset.filter(host=self.host)
        return queryset.filter(pk=self.pk)

    def get_previous_successful_release(self):
        return self.same_target_queryset().filter(
            approval_status='approved',
            execution_count__gt=0,
            status__in=('running', 'stopped', 'removed'),
        ).exclude(pk=self.pk).order_by('-executed_at', '-id').first()


class DeploymentApprovalFlow(models.Model):
    ENV_CHOICES = [('', '全部环境')] + Deployment.ENV_CHOICES

    name = models.CharField('流程名称', max_length=128)
    environment = models.CharField('适用环境', max_length=32, choices=ENV_CHOICES, blank=True, default='')
    description = models.CharField('描述', max_length=255, blank=True, default='')
    is_active = models.BooleanField('启用', default=True)
    created_by = models.CharField('维护人', max_length=64, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '发布审批流程'
        verbose_name_plural = '发布审批流程'
        ordering = ['environment', 'name', '-updated_at']

    def __str__(self):
        return self.name

    @property
    def scope_display(self):
        return self.get_environment_display() if self.environment else '全部环境'


class DeploymentApprovalNode(models.Model):
    APPROVER_TYPE_CHOICES = [
        ('user', '指定用户'),
        ('role', '指定角色'),
        ('group', '指定用户组'),
    ]

    flow = models.ForeignKey(
        DeploymentApprovalFlow,
        on_delete=models.CASCADE,
        related_name='nodes',
        verbose_name='所属流程',
    )
    name = models.CharField('节点名称', max_length=128)
    order = models.PositiveIntegerField('排序', default=1)
    approver_type = models.CharField('审批人类型', max_length=16, choices=APPROVER_TYPE_CHOICES, default='user')
    approver_value = models.CharField('审批人值', max_length=128, blank=True, default='')
    description = models.CharField('节点说明', max_length=255, blank=True, default='')

    class Meta:
        verbose_name = '审批流程节点'
        verbose_name_plural = '审批流程节点'
        ordering = ['order', 'id']
        constraints = [
            models.UniqueConstraint(fields=['flow', 'order'], name='uniq_ops_deploy_approval_flow_node_order'),
        ]

    def __str__(self):
        return f'{self.flow.name} - {self.name}'

    @property
    def approver_scope_display(self):
        return f'{self.get_approver_type_display()}: {self.approver_value or "-"}'


class DeploymentApprovalStep(models.Model):
    STEP_STATUS_CHOICES = [
        ('pending', '待审批'),
        ('approved', '已通过'),
        ('rejected', '已拒绝'),
    ]

    deployment = models.ForeignKey(
        Deployment,
        on_delete=models.CASCADE,
        related_name='approval_steps',
        verbose_name='发布单',
    )
    flow = models.ForeignKey(
        DeploymentApprovalFlow,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='steps',
        verbose_name='审批流程',
    )
    node_name = models.CharField('节点名称', max_length=128)
    node_order = models.PositiveIntegerField('节点排序', default=1)
    approver_type = models.CharField(
        '审批人类型',
        max_length=16,
        choices=DeploymentApprovalNode.APPROVER_TYPE_CHOICES,
        default='user',
    )
    approver_value = models.CharField('审批人值', max_length=128, blank=True, default='')
    status = models.CharField('节点状态', max_length=16, choices=STEP_STATUS_CHOICES, default='pending')
    is_current = models.BooleanField('当前节点', default=False)
    approver = models.CharField('审批人', max_length=64, blank=True, default='')
    comment = models.CharField('审批意见', max_length=255, blank=True, default='')
    acted_at = models.DateTimeField('处理时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '发布审批步骤'
        verbose_name_plural = '发布审批步骤'
        ordering = ['node_order', 'id']
        constraints = [
            models.UniqueConstraint(fields=['deployment', 'node_order'], name='uniq_ops_deploy_approval_step_order'),
        ]
        indexes = [
            models.Index(fields=['deployment', 'status', 'is_current']),
        ]

    def __str__(self):
        return f'#{self.deployment_id} - {self.node_name}'

    @property
    def approver_scope_display(self):
        return f'{self.get_approver_type_display()}: {self.approver_value or "-"}'


class Alert(models.Model):
    SOURCE_PROMETHEUS = 'prometheus'
    SOURCE_ZABBIX = 'zabbix'
    SOURCE_NIGHTINGALE = 'nightingale'
    SOURCE_ALIYUN = 'aliyun'
    SOURCE_GENERIC = 'generic'
    SOURCE_TYPE_CHOICES = [
        (SOURCE_PROMETHEUS, 'Prometheus Alertmanager'),
        (SOURCE_ZABBIX, 'Zabbix'),
        (SOURCE_NIGHTINGALE, '夜莺'),
        (SOURCE_ALIYUN, '阿里云监控'),
        (SOURCE_GENERIC, '通用 Webhook'),
    ]

    STATUS_ACTIVE = 'active'
    STATUS_RESOLVED = 'resolved'
    STATUS_CLOSED = 'closed'
    STATUS_MUTED = 'muted'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, '活跃'),
        (STATUS_RESOLVED, '已恢复'),
        (STATUS_CLOSED, '已关闭'),
        (STATUS_MUTED, '已屏蔽'),
    ]

    LEVEL_CHOICES = [
        ('critical', '严重'),
        ('warning', '警告'),
        ('info', '信息'),
    ]

    integration = models.ForeignKey('AlertIntegration', on_delete=models.SET_NULL, null=True, blank=True, related_name='alerts', verbose_name='接入源')
    title = models.CharField('告警标题', max_length=256)
    level = models.CharField('级别', max_length=16, choices=LEVEL_CHOICES, default='info')
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    source = models.CharField('来源', max_length=128)
    source_type = models.CharField('来源类型', max_length=32, choices=SOURCE_TYPE_CHOICES, default=SOURCE_GENERIC)
    external_id = models.CharField('外部事件 ID', max_length=128, blank=True, default='')
    fingerprint = models.CharField('指纹', max_length=128, blank=True, default='', db_index=True)
    group_key = models.CharField('聚合键', max_length=256, blank=True, default='', db_index=True)
    message = models.TextField('详情')
    is_acknowledged = models.BooleanField('已确认', default=False)
    acknowledged_by = models.CharField('确认人', max_length=64, blank=True, default='')
    acknowledged_at = models.DateTimeField('确认时间', null=True, blank=True)
    claimed_by = models.CharField('认领人', max_length=64, blank=True, default='')
    claimed_at = models.DateTimeField('认领时间', null=True, blank=True)
    host = models.ForeignKey(Host, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='关联主机')
    service = models.CharField('服务', max_length=128, blank=True, default='')
    environment = models.CharField('环境', max_length=64, blank=True, default='')
    cluster = models.CharField('集群', max_length=128, blank=True, default='')
    namespace = models.CharField('命名空间', max_length=128, blank=True, default='')
    region = models.CharField('地域', max_length=128, blank=True, default='')
    business_line = models.CharField('系统', max_length=128, blank=True, default='')
    resource_type = models.CharField('资源类型', max_length=64, blank=True, default='')
    resource = models.CharField('资源标识', max_length=256, blank=True, default='')
    metric_name = models.CharField('指标名', max_length=128, blank=True, default='')
    runbook_url = models.URLField('Runbook', max_length=500, blank=True, default='')
    labels = models.JSONField('标签', default=dict, blank=True)
    annotations = models.JSONField('注解', default=dict, blank=True)
    raw_payload = models.JSONField('原始载荷', default=dict, blank=True)
    starts_at = models.DateTimeField('触发时间', null=True, blank=True)
    ends_at = models.DateTimeField('恢复时间', null=True, blank=True)
    last_received_at = models.DateTimeField('最近接收时间', default=timezone.now)
    occurrence_count = models.PositiveIntegerField('出现次数', default=1)
    is_suppressed = models.BooleanField('已被抑制', default=False)
    suppressed_by = models.CharField('抑制来源', max_length=128, blank=True, default='')
    suppressed_until = models.DateTimeField('抑制截止时间', null=True, blank=True)
    mute_until = models.DateTimeField('屏蔽截止时间', null=True, blank=True)
    muted_by = models.CharField('屏蔽人', max_length=64, blank=True, default='')
    muted_reason = models.CharField('屏蔽原因', max_length=255, blank=True, default='')
    escalation_level = models.PositiveIntegerField('升级级别', default=0)
    escalated_at = models.DateTimeField('升级时间', null=True, blank=True)
    closed_at = models.DateTimeField('关闭时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '告警'
        verbose_name_plural = '告警'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'level']),
            models.Index(fields=['source_type', 'source']),
            models.Index(fields=['service', 'environment']),
            models.Index(fields=['cluster', 'namespace']),
            models.Index(fields=['resource_type', 'resource']),
            models.Index(fields=['is_acknowledged', 'created_at']),
        ]

    def __str__(self):
        return f'[{self.level}] {self.title}'


class AlertClaim(models.Model):
    alert = models.ForeignKey(Alert, on_delete=models.CASCADE, related_name='claim_records', verbose_name='告警')
    claimant = models.CharField('认领人', max_length=64)
    claimed_at = models.DateTimeField('认领时间', auto_now_add=True)

    class Meta:
        verbose_name = '告警认领记录'
        verbose_name_plural = '告警认领记录'
        ordering = ['claimed_at', 'id']
        constraints = [
            models.UniqueConstraint(fields=['alert', 'claimant'], name='uniq_ops_alert_claimant'),
        ]
        indexes = [
            models.Index(fields=['alert', 'claimant']),
        ]

    def __str__(self):
        return f'{self.alert_id}:{self.claimant}'


class AlertIntegration(models.Model):
    PROVIDER_CHOICES = Alert.SOURCE_TYPE_CHOICES

    name = models.CharField('接入源名称', max_length=128)
    provider = models.CharField('接入类型', max_length=32, choices=PROVIDER_CHOICES)
    token = models.CharField('接入令牌', max_length=64, unique=True, default=generate_alert_token)
    secret = models.CharField('签名密钥', max_length=255, blank=True, default='')
    is_enabled = models.BooleanField('启用', default=True)
    default_labels = models.JSONField('默认标签', default=dict, blank=True)
    description = models.CharField('说明', max_length=255, blank=True, default='')
    last_received_at = models.DateTimeField('最近接收时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '告警接入源'
        verbose_name_plural = '告警接入源'
        ordering = ['provider', 'name']

    def __str__(self):
        return f'{self.name} ({self.provider})'


class AlertRecipient(models.Model):
    name = models.CharField('姓名', max_length=64)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='alert_recipients', verbose_name='平台用户')
    phone = models.CharField('手机号', max_length=32, blank=True, default='')
    email = models.EmailField('邮箱', blank=True, default='')
    dingtalk_user_id = models.CharField('钉钉用户 ID', max_length=128, blank=True, default='')
    feishu_user_id = models.CharField('飞书用户 ID', max_length=128, blank=True, default='')
    wecom_user_id = models.CharField('企微用户 ID', max_length=128, blank=True, default='')
    is_enabled = models.BooleanField('启用', default=True)
    description = models.CharField('说明', max_length=255, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '告警接收人'
        verbose_name_plural = '告警接收人'
        ordering = ['name']

    def __str__(self):
        return self.name


class AlertRecipientGroup(models.Model):
    name = models.CharField('接收组名称', max_length=128, unique=True)
    description = models.CharField('说明', max_length=255, blank=True, default='')
    recipients = models.ManyToManyField(AlertRecipient, blank=True, related_name='groups', verbose_name='接收人')
    users = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name='alert_recipient_groups', verbose_name='平台用户')
    is_enabled = models.BooleanField('启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '告警接收组'
        verbose_name_plural = '告警接收组'
        ordering = ['name']

    def __str__(self):
        return self.name


class AlertNotificationChannel(models.Model):
    CHANNEL_SMS = 'sms'
    CHANNEL_VOICE = 'voice'
    CHANNEL_EMAIL = 'email'
    CHANNEL_DINGTALK = 'dingtalk'
    CHANNEL_FEISHU = 'feishu'
    CHANNEL_WECOM = 'wecom'
    CHANNEL_CHOICES = [
        (CHANNEL_SMS, '短信'),
        (CHANNEL_VOICE, '语音'),
        (CHANNEL_EMAIL, '邮件'),
        (CHANNEL_DINGTALK, '钉钉'),
        (CHANNEL_FEISHU, '飞书'),
        (CHANNEL_WECOM, '企微'),
    ]

    name = models.CharField('渠道名称', max_length=128)
    channel_type = models.CharField('渠道类型', max_length=32, choices=CHANNEL_CHOICES)
    is_enabled = models.BooleanField('启用', default=True)
    send_resolved = models.BooleanField('发送恢复通知', default=True)
    timeout_seconds = models.PositiveIntegerField('超时时间', default=8)
    config = models.JSONField('渠道配置', default=dict, blank=True)
    template_title = models.CharField('标题模板', max_length=255, blank=True, default='')
    template_body = models.TextField('内容模板', blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '告警通知渠道'
        verbose_name_plural = '告警通知渠道'
        ordering = ['channel_type', 'name']

    def __str__(self):
        return f'{self.name} ({self.channel_type})'


class AlertAggregationRule(models.Model):
    name = models.CharField('聚合规则名称', max_length=128)
    is_enabled = models.BooleanField('启用', default=True)
    matchers = models.JSONField('匹配条件', default=list, blank=True)
    group_by = models.JSONField('聚合维度', default=list, blank=True)
    window_minutes = models.PositiveIntegerField('聚合窗口分钟', default=5)
    repeat_interval_minutes = models.PositiveIntegerField('重复通知间隔分钟', default=30)
    description = models.CharField('说明', max_length=255, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '告警聚合规则'
        verbose_name_plural = '告警聚合规则'
        ordering = ['name']

    def __str__(self):
        return self.name


class AlertInhibitionRule(models.Model):
    name = models.CharField('抑制规则名称', max_length=128)
    is_enabled = models.BooleanField('启用', default=True)
    source_matchers = models.JSONField('源告警匹配', default=list, blank=True)
    target_matchers = models.JSONField('目标告警匹配', default=list, blank=True)
    equal_labels = models.JSONField('相同标签', default=list, blank=True)
    duration_minutes = models.PositiveIntegerField('抑制时长分钟', default=60)
    description = models.CharField('说明', max_length=255, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '告警抑制规则'
        verbose_name_plural = '告警抑制规则'
        ordering = ['name']

    def __str__(self):
        return self.name


class AlertMuteRule(models.Model):
    name = models.CharField('屏蔽规则名称', max_length=128)
    is_enabled = models.BooleanField('启用', default=True)
    matchers = models.JSONField('匹配条件', default=list, blank=True)
    starts_at = models.DateTimeField('开始时间', null=True, blank=True)
    ends_at = models.DateTimeField('结束时间', null=True, blank=True)
    reason = models.CharField('原因', max_length=255, blank=True, default='')
    created_by = models.CharField('创建人', max_length=64, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '告警屏蔽规则'
        verbose_name_plural = '告警屏蔽规则'
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class AlertEscalationPolicy(models.Model):
    name = models.CharField('升级策略名称', max_length=128)
    is_enabled = models.BooleanField('启用', default=True)
    matchers = models.JSONField('匹配条件', default=list, blank=True)
    levels = models.JSONField('升级层级', default=list, blank=True)
    repeat_interval_minutes = models.PositiveIntegerField('升级间隔分钟', default=30)
    description = models.CharField('说明', max_length=255, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '告警升级策略'
        verbose_name_plural = '告警升级策略'
        ordering = ['name']

    def __str__(self):
        return self.name


class AlertNotificationRule(models.Model):
    LEVEL_CHOICES = Alert.LEVEL_CHOICES

    name = models.CharField('通知规则名称', max_length=128)
    is_enabled = models.BooleanField('启用', default=True)
    matchers = models.JSONField('匹配条件', default=list, blank=True)
    min_level = models.CharField('最低级别', max_length=16, choices=LEVEL_CHOICES, blank=True, default='')
    aggregation_rule = models.ForeignKey(AlertAggregationRule, on_delete=models.SET_NULL, null=True, blank=True, related_name='notification_rules', verbose_name='聚合规则')
    escalation_policy = models.ForeignKey(AlertEscalationPolicy, on_delete=models.SET_NULL, null=True, blank=True, related_name='notification_rules', verbose_name='升级策略')
    channels = models.ManyToManyField(AlertNotificationChannel, blank=True, related_name='notification_rules', verbose_name='通知渠道')
    recipients = models.ManyToManyField(AlertRecipient, blank=True, related_name='notification_rules', verbose_name='接收人')
    recipient_groups = models.ManyToManyField(AlertRecipientGroup, blank=True, related_name='notification_rules', verbose_name='接收组')
    notify_on_fire = models.BooleanField('触发时通知', default=True)
    notify_on_resolved = models.BooleanField('恢复时通知', default=True)
    notify_on_escalation = models.BooleanField('升级时通知', default=True)
    description = models.CharField('说明', max_length=255, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '告警通知规则'
        verbose_name_plural = '告警通知规则'
        ordering = ['name']

    def __str__(self):
        return self.name


class AlertNotificationLog(models.Model):
    STATUS_SUCCESS = 'success'
    STATUS_SKIPPED = 'skipped'
    STATUS_ERROR = 'error'
    STATUS_CHOICES = [
        (STATUS_SUCCESS, '成功'),
        (STATUS_SKIPPED, '跳过'),
        (STATUS_ERROR, '失败'),
    ]

    alert = models.ForeignKey(Alert, on_delete=models.CASCADE, related_name='notification_logs', verbose_name='告警')
    rule = models.ForeignKey(AlertNotificationRule, on_delete=models.SET_NULL, null=True, blank=True, related_name='notification_logs', verbose_name='通知规则')
    channel = models.ForeignKey(AlertNotificationChannel, on_delete=models.SET_NULL, null=True, blank=True, related_name='notification_logs', verbose_name='通知渠道')
    action = models.CharField('通知动作', max_length=32, default='fire')
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES, default=STATUS_SUCCESS)
    recipient_summary = models.CharField('接收人', max_length=255, blank=True, default='')
    request_payload = models.JSONField('请求载荷', default=dict, blank=True)
    response_body = models.TextField('响应内容', blank=True, default='')
    error_message = models.TextField('错误信息', blank=True, default='')
    sent_at = models.DateTimeField('发送时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '告警通知记录'
        verbose_name_plural = '告警通知记录'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.alert_id} {self.action} {self.status}'


class AlertAction(models.Model):
    ACTION_WEBHOOK = 'webhook'
    ACTION_NOTIFY = 'notify'
    ACTION_ACKNOWLEDGE = 'acknowledge'
    ACTION_CLAIM = 'claim'
    ACTION_UNCLAIM = 'unclaim'
    ACTION_MUTE = 'mute'
    ACTION_ESCALATE = 'escalate'
    ACTION_RESOLVE = 'resolve'
    ACTION_CLOSE = 'close'
    ACTION_REOPEN = 'reopen'
    ACTION_COMMENT = 'comment'
    ACTION_CHOICES = [
        (ACTION_WEBHOOK, 'Webhook 接入'),
        (ACTION_NOTIFY, '发送通知'),
        (ACTION_ACKNOWLEDGE, '确认'),
        (ACTION_CLAIM, '认领'),
        (ACTION_UNCLAIM, '取消认领'),
        (ACTION_MUTE, '屏蔽'),
        (ACTION_ESCALATE, '升级'),
        (ACTION_RESOLVE, '恢复'),
        (ACTION_CLOSE, '关闭'),
        (ACTION_REOPEN, '重新打开'),
        (ACTION_COMMENT, '备注'),
    ]

    alert = models.ForeignKey(Alert, on_delete=models.CASCADE, related_name='actions', verbose_name='告警')
    action = models.CharField('动作', max_length=32, choices=ACTION_CHOICES)
    actor = models.CharField('操作人', max_length=128, blank=True, default='')
    note = models.CharField('说明', max_length=255, blank=True, default='')
    metadata = models.JSONField('元数据', default=dict, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '告警动作'
        verbose_name_plural = '告警动作'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.alert_id} {self.action}'


class AlertInteractionToken(models.Model):
    token = models.UUIDField('交互令牌', primary_key=True, default=uuid.uuid4, editable=False)
    alert = models.ForeignKey(Alert, on_delete=models.CASCADE, related_name='interaction_tokens', verbose_name='告警')
    action = models.CharField('动作', max_length=32, choices=AlertAction.ACTION_CHOICES)
    provider = models.CharField('来源渠道', max_length=32, blank=True, default='')
    expires_at = models.DateTimeField('过期时间')
    used_at = models.DateTimeField('使用时间', null=True, blank=True)
    metadata = models.JSONField('元数据', default=dict, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '告警卡片交互令牌'
        verbose_name_plural = '告警卡片交互令牌'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.alert_id} {self.action}'

    @property
    def is_available(self):
        return self.used_at is None and self.expires_at > timezone.now()


class LogEntry(models.Model):
    LEVEL_CHOICES = [
        ('error', 'ERROR'),
        ('warning', 'WARNING'),
        ('info', 'INFO'),
        ('debug', 'DEBUG'),
    ]

    level = models.CharField('级别', max_length=16, choices=LEVEL_CHOICES, default='info')
    service = models.CharField('服务名', max_length=128)
    message = models.TextField('日志内容')
    host = models.ForeignKey(Host, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='来源主机')
    timestamp = models.DateTimeField('时间', auto_now_add=True)

    class Meta:
        verbose_name = '日志'
        verbose_name_plural = '日志'
        ordering = ['-timestamp']

    def __str__(self):
        return f'[{self.level}] {self.service}: {self.message[:50]}'


class LogDataSource(models.Model):
    PROVIDER_CHOICES = [
        ('loki', 'Loki'),
        ('elk', 'ELK / Elasticsearch'),
        ('sls', '阿里云 SLS'),
    ]

    name = models.CharField('名称', max_length=128, unique=True)
    provider = models.CharField('日志类型', max_length=16, choices=PROVIDER_CHOICES)
    description = models.CharField('描述', max_length=255, blank=True, default='')
    config = models.JSONField('连接配置', default=dict, blank=True)
    is_enabled = models.BooleanField('启用', default=True)
    is_default = models.BooleanField('默认数据源', default=False)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '日志数据源'
        verbose_name_plural = '日志数据源'
        ordering = ['provider', 'name']

    def __str__(self):
        return f'{self.get_provider_display()} - {self.name}'


class TracingDataSource(models.Model):
    PROVIDER_CHOICES = [
        ('skywalking', 'SkyWalking'),
        ('tempo', 'Tempo / OpenTelemetry'),
        ('jaeger', 'Jaeger / OpenTelemetry'),
        ('zipkin', 'Zipkin / OpenTelemetry'),
    ]

    name = models.CharField('Tracing data source name', max_length=128, unique=True)
    provider = models.CharField('Tracing provider', max_length=16, choices=PROVIDER_CHOICES)
    description = models.CharField('Description', max_length=255, blank=True, default='')
    config = models.JSONField('Connection config', default=dict, blank=True)
    is_enabled = models.BooleanField('Enabled', default=True)
    is_default = models.BooleanField('Default data source', default=False)
    created_at = models.DateTimeField('Created at', auto_now_add=True)
    updated_at = models.DateTimeField('Updated at', auto_now=True)

    class Meta:
        verbose_name = 'Tracing data source'
        verbose_name_plural = 'Tracing data sources'
        ordering = ['provider', 'name']

    def __str__(self):
        return f'{self.get_provider_display()} - {self.name}'


class MetricDataSource(models.Model):
    PROVIDER_PROMETHEUS = 'prometheus'
    PROVIDER_CHOICES = [
        (PROVIDER_PROMETHEUS, 'Prometheus Like'),
    ]

    name = models.CharField('指标数据源名称', max_length=128, unique=True)
    provider = models.CharField('指标数据源类型', max_length=32, choices=PROVIDER_CHOICES, default=PROVIDER_PROMETHEUS)
    description = models.CharField('描述', max_length=255, blank=True, default='')
    environment = models.CharField('环境', max_length=32, blank=True, default='')
    cluster_name = models.CharField('集群标识', max_length=128, blank=True, default='')
    tsdb_type = models.CharField('TSDB 类型', max_length=32, blank=True, default='prometheus')
    config = models.JSONField('连接配置', default=dict, blank=True)
    is_enabled = models.BooleanField('启用', default=True)
    is_default = models.BooleanField('默认数据源', default=False)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '指标数据源'
        verbose_name_plural = '指标数据源'
        ordering = ['environment', '-is_default', 'name']
        indexes = [
            models.Index(fields=['environment', 'is_enabled'], name='ops_metric_ds_env_enabled_idx'),
            models.Index(fields=['provider', 'is_enabled'], name='ops_metric_ds_provider_idx'),
        ]

    def __str__(self):
        return f'{self.name} ({self.get_provider_display()})'


class ObservabilityDataSourceLink(models.Model):
    name = models.CharField('关联名称', max_length=128, unique=True)
    log_datasource = models.ForeignKey(
        LogDataSource,
        on_delete=models.CASCADE,
        related_name='trace_links',
        verbose_name='日志数据源',
    )
    tracing_datasource = models.ForeignKey(
        TracingDataSource,
        on_delete=models.CASCADE,
        related_name='log_links',
        verbose_name='链路数据源',
    )
    description = models.CharField('描述', max_length=255, blank=True, default='')
    is_enabled = models.BooleanField('启用', default=True)
    is_default = models.BooleanField('默认关联', default=False)
    log_to_trace_enabled = models.BooleanField('日志跳链路', default=True)
    trace_to_log_enabled = models.BooleanField('链路跳日志', default=True)
    log_to_grafana_enabled = models.BooleanField('日志跳看板', default=True)
    trace_to_grafana_enabled = models.BooleanField('链路跳看板', default=True)
    grafana_to_log_enabled = models.BooleanField('看板跳日志', default=True)
    grafana_to_trace_enabled = models.BooleanField('看板跳链路', default=True)
    trace_id_fields = models.JSONField('Trace ID 字段', default=list, blank=True)
    trace_id_regex = models.CharField('Trace ID 正则', max_length=255, blank=True, default='')
    log_query_template = models.TextField('日志查询模板', blank=True, default='')
    log_label_mappings = models.JSONField('日志标签映射', default=list, blank=True)
    grafana_dashboard_key = models.CharField('Grafana 看板 Key', max_length=128, blank=True, default='')
    grafana_variable_mappings = models.JSONField('Grafana 变量映射', default=list, blank=True)
    span_start_shift = models.CharField('Span 开始偏移', max_length=16, blank=True, default='-5m')
    span_end_shift = models.CharField('Span 结束偏移', max_length=16, blank=True, default='5m')
    window_minutes = models.PositiveIntegerField('默认查询窗口分钟', default=10)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '可观测数据源关联'
        verbose_name_plural = '可观测数据源关联'
        ordering = ['-is_default', 'name']
        unique_together = ('log_datasource', 'tracing_datasource')

    def __str__(self):
        return f'{self.log_datasource.name} -> {self.tracing_datasource.name}'


class GrafanaSetting(models.Model):
    name = models.CharField('配置名称', max_length=64, default='default', unique=True)
    enabled = models.BooleanField('启用', default=True)
    url = models.CharField('Grafana URL', max_length=255, blank=True, default='')
    default_path = models.CharField('默认看板路径', max_length=255, blank=True, default='')
    folders = models.JSONField('目录配置', default=list, blank=True)
    dashboards = models.JSONField('看板配置', default=list, blank=True)
    updated_by = models.CharField('更新人', max_length=64, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = 'Grafana 配置'
        verbose_name_plural = 'Grafana 配置'

    def __str__(self):
        return self.name


class K8sCluster(models.Model):
    STATUS_CHOICES = [
        ('connected', '已连接'),
        ('disconnected', '未连接'),
        ('error', '异常'),
    ]

    name = models.CharField('集群名称', max_length=128, unique=True)
    api_server = models.CharField('API Server', max_length=256, blank=True, default='')
    kubeconfig = models.TextField('KubeConfig', help_text='YAML 格式的 kubeconfig 内容')
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES, default='disconnected')
    description = models.CharField('描述', max_length=256, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = 'K8s 集群'
        verbose_name_plural = 'K8s 集群'
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class K8sConfigRevision(models.Model):
    ACTION_CHOICES = [
        ('update', 'Update Snapshot'),
        ('rollback', 'Rollback Snapshot'),
    ]

    cluster = models.ForeignKey(K8sCluster, on_delete=models.CASCADE, related_name='config_revisions')
    resource_type = models.CharField(max_length=32)
    namespace = models.CharField(max_length=128)
    resource_name = models.CharField(max_length=255)
    secret_type = models.CharField(max_length=128, blank=True, default='')
    content = models.TextField()
    operator = models.CharField(max_length=64, blank=True, default='')
    action = models.CharField(max_length=32, choices=ACTION_CHOICES, default='update')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'K8s config revision'
        verbose_name_plural = 'K8s config revisions'
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['cluster', 'resource_type', 'namespace', 'resource_name']),
        ]

    def __str__(self):
        return f'{self.cluster.name}:{self.resource_type}/{self.namespace}/{self.resource_name}'


class DockerHost(models.Model):
    STATUS_CHOICES = [
        ('connected', '已连接'),
        ('disconnected', '未连接'),
        ('error', '异常'),
    ]

    name = models.CharField('环境名称', max_length=128, unique=True)
    ip_address = models.GenericIPAddressField('IP 地址')
    ssh_port = models.IntegerField('SSH 端口', default=22)
    ssh_user = models.CharField('SSH 用户', max_length=64, default='root')
    ssh_password = models.CharField('SSH 密码', max_length=256, blank=True, default='')
    docker_api_version = models.CharField('Docker API 版本', max_length=16, blank=True, default='')
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES, default='disconnected')
    description = models.CharField('描述', max_length=256, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = 'Docker 环境'
        verbose_name_plural = 'Docker 环境'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.ip_address})'


class NginxEnvironment(models.Model):
    STATUS_CHOICES = [
        ('connected', '已连接'),
        ('disconnected', '未连接'),
        ('error', '异常'),
    ]

    name = models.CharField('环境名称', max_length=128, unique=True)
    ip_address = models.GenericIPAddressField('IP 地址')
    ssh_port = models.IntegerField('SSH 端口', default=22)
    ssh_user = models.CharField('SSH 用户', max_length=64, default='root')
    ssh_password = models.CharField('SSH 密码', max_length=256, blank=True, default='')
    nginx_path = models.CharField('Nginx 路径', max_length=256, default='/etc/nginx')
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES, default='disconnected')
    description = models.CharField('描述', max_length=256, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = 'Nginx 环境'
        verbose_name_plural = 'Nginx 环境'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.ip_address})'


class NginxCertificate(models.Model):
    domain = models.CharField('证书域名', max_length=256, help_text='证书对应的域名')
    cert_content = models.TextField('证书内容 (PEM)', blank=True, default='')
    key_content = models.TextField('私钥内容 (KEY)', blank=True, default='')
    environments = models.ManyToManyField(
        NginxEnvironment,
        blank=True,
        verbose_name='关联环境',
        related_name='certificates',
    )
    expires_at = models.DateTimeField('过期时间', null=True, blank=True)
    description = models.CharField('描述', max_length=256, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = 'Nginx 证书'
        verbose_name_plural = 'Nginx 证书'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.domain}'

    @property
    def cert_filename(self):
        safe = self.domain.replace('*', '_wc_').replace('.', '_')
        return f'{safe}.pem'

    @property
    def key_filename(self):
        safe = self.domain.replace('*', '_wc_').replace('.', '_')
        return f'{safe}.key'


class NginxDomain(models.Model):
    environment = models.ForeignKey(
        NginxEnvironment,
        on_delete=models.CASCADE,
        verbose_name='所属环境',
        related_name='domains',
    )
    domain = models.CharField('域名/IP', max_length=256, help_text='填写域名或 IP 地址')
    listen_port = models.IntegerField('监听端口', default=80)
    ssl_port = models.IntegerField('SSL 端口', default=443)
    certificate = models.ForeignKey(
        NginxCertificate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='关联证书',
        related_name='linked_domains',
    )
    enabled = models.BooleanField('启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = 'Nginx 域名'
        verbose_name_plural = 'Nginx 域名'
        ordering = ['-created_at']
        unique_together = ('environment', 'domain', 'listen_port')

    def __str__(self):
        return f'{self.domain}:{self.listen_port} ({self.environment.name})'

    @property
    def ssl_enabled(self):
        return self.certificate is not None and self.certificate_id is not None

    @property
    def conf_filename(self):
        safe = self.domain.replace('*', '_wc_').replace('.', '_')
        return f'{safe}_{self.listen_port}.conf'


class NginxRoute(models.Model):
    nginx_domain = models.ForeignKey(
        NginxDomain,
        on_delete=models.CASCADE,
        verbose_name='所属域名',
        related_name='routes',
    )
    location = models.CharField('Location 路径', max_length=256, default='/')
    upstream_servers = models.TextField(
        '后端地址',
        blank=True,
        default='',
        help_text='每行一个后端地址，如 http://127.0.0.1:8080',
    )
    redirect_url = models.CharField('重定向地址', max_length=512, blank=True, default='')
    redirect_code = models.IntegerField('重定向状态码', default=301)
    custom_headers = models.TextField(
        '自定义 Header (JSON)',
        blank=True,
        default='',
        help_text='[{"name":"X-Custom","value":"val"}]',
    )
    proxy_set_headers = models.TextField(
        'proxy_set_header (JSON)',
        blank=True,
        default='',
        help_text='[{"name":"Host","value":"$host"}]',
    )
    client_max_body_size = models.CharField('上传大小限制', max_length=32, blank=True, default='10m')
    extra_directives = models.TextField(
        '额外指令',
        blank=True,
        default='',
        help_text='原始 Nginx 指令，每行一条',
    )
    enabled = models.BooleanField('是否启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = 'Nginx 路由'
        verbose_name_plural = 'Nginx 路由'
        ordering = ['-created_at']
        unique_together = ('nginx_domain', 'location')

    def __str__(self):
        return f'{self.nginx_domain.domain}{self.location}'


class TransactionTicket(models.Model):
    TYPE_CHANGE = 'change'
    TYPE_INSPECTION = 'inspection'
    TYPE_ACCESS = 'access'
    TYPE_INCIDENT = 'incident'
    TYPE_CHOICES = [
        (TYPE_CHANGE, '变更执行'),
        (TYPE_INSPECTION, '巡检任务'),
        (TYPE_ACCESS, '权限开通'),
        (TYPE_INCIDENT, '故障处理'),
    ]

    PRIORITY_HIGH = 'high'
    PRIORITY_MEDIUM = 'medium'
    PRIORITY_LOW = 'low'
    PRIORITY_CHOICES = [
        (PRIORITY_HIGH, '高'),
        (PRIORITY_MEDIUM, '中'),
        (PRIORITY_LOW, '低'),
    ]

    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_PROCESSING = 'processing'
    STATUS_DONE = 'done'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [
        (STATUS_PENDING, '待审批'),
        (STATUS_APPROVED, '已通过'),
        (STATUS_PROCESSING, '处理中'),
        (STATUS_DONE, '已完成'),
        (STATUS_REJECTED, '已驳回'),
    ]

    ENV_CHOICES = Deployment.ENV_CHOICES

    title = models.CharField('工单标题', max_length=200)
    ticket_type = models.CharField('事务类型', max_length=32, choices=TYPE_CHOICES, default=TYPE_CHANGE)
    priority = models.CharField('优先级', max_length=16, choices=PRIORITY_CHOICES, default=PRIORITY_MEDIUM)
    business_line = models.CharField('系统', max_length=50, blank=True, default='')
    environment = models.CharField('环境', max_length=32, choices=ENV_CHOICES, blank=True, default='')
    approval_flow = models.ForeignKey(
        'DeploymentApprovalFlow',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transaction_tickets',
        verbose_name='审批流',
    )
    owner = models.CharField('处理人', max_length=64, blank=True, default='')
    applicant = models.CharField('申请人', max_length=64, default='system')
    window = models.CharField('执行窗口', max_length=128, blank=True, default='')
    description = models.TextField('说明', blank=True, default='')
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '事务工单'
        verbose_name_plural = '事务工单'
        ordering = ['-updated_at', '-id']
        indexes = [
            models.Index(fields=['status', 'priority', '-updated_at']),
            models.Index(fields=['business_line', 'environment']),
        ]

    def __str__(self):
        return self.title
