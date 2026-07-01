import hashlib
import secrets

from django.db import models
from django.utils import timezone


class EventRecord(models.Model):
    RESULT_SUCCESS = 'success'
    RESULT_FAILED = 'failed'
    RESULT_PARTIAL = 'partial'
    RESULT_PENDING = 'pending'
    RESULT_REJECTED = 'rejected'

    RESULT_CHOICES = [
        (RESULT_SUCCESS, '成功'),
        (RESULT_FAILED, '失败'),
        (RESULT_PARTIAL, '部分成功'),
        (RESULT_PENDING, '待处理'),
        (RESULT_REJECTED, '已拒绝'),
    ]

    SEVERITY_INFO = 'info'
    SEVERITY_WARNING = 'warning'
    SEVERITY_DANGER = 'danger'

    SEVERITY_CHOICES = [
        (SEVERITY_INFO, '信息'),
        (SEVERITY_WARNING, '提示'),
        (SEVERITY_DANGER, '高风险'),
    ]

    SOURCE_HTTP = 'http'
    SOURCE_ASYNC = 'async'
    SOURCE_SCHEDULER = 'scheduler'
    SOURCE_SYSTEM = 'system'
    SOURCE_SEED = 'seed'
    SOURCE_WEBSOCKET = 'websocket'
    SOURCE_EXTERNAL = 'external'

    SOURCE_CHOICES = [
        (SOURCE_HTTP, 'HTTP'),
        (SOURCE_ASYNC, '异步任务'),
        (SOURCE_SCHEDULER, '调度器'),
        (SOURCE_SYSTEM, '系统'),
        (SOURCE_SEED, '演示数据'),
        (SOURCE_WEBSOCKET, 'WebSocket'),
        (SOURCE_EXTERNAL, 'External'),
    ]

    ACTOR_USER = 'user'
    ACTOR_SYSTEM = 'system'

    ACTOR_TYPE_CHOICES = [
        (ACTOR_USER, '用户'),
        (ACTOR_SYSTEM, '系统'),
    ]

    occurred_at = models.DateTimeField('发生时间', default=timezone.now, db_index=True)
    module = models.CharField('模块', max_length=32, db_index=True)
    category = models.CharField('分类', max_length=32, db_index=True)
    action = models.CharField('动作', max_length=32, db_index=True)
    result = models.CharField('结果', max_length=16, choices=RESULT_CHOICES, default=RESULT_SUCCESS, db_index=True)
    severity = models.CharField('风险级别', max_length=16, choices=SEVERITY_CHOICES, default=SEVERITY_INFO)
    title = models.CharField('事件标题', max_length=255)
    summary = models.CharField('事件摘要', max_length=255, blank=True, default='')
    detail = models.TextField('详情', blank=True, default='')
    actor_type = models.CharField('操作者类型', max_length=16, choices=ACTOR_TYPE_CHOICES, default=ACTOR_USER)
    actor_username = models.CharField('操作者', max_length=64, blank=True, default='', db_index=True)
    actor_display = models.CharField('操作者展示名', max_length=128, blank=True, default='')
    source_type = models.CharField('来源类型', max_length=16, choices=SOURCE_CHOICES, default=SOURCE_HTTP)
    request_method = models.CharField('请求方法', max_length=12, blank=True, default='')
    source_path = models.CharField('来源路径', max_length=255, blank=True, default='')
    ip_address = models.CharField('IP 地址', max_length=64, blank=True, default='')
    correlation_id = models.CharField('关联链路', max_length=128, blank=True, default='', db_index=True)
    parent_event = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        related_name='children',
        on_delete=models.SET_NULL,
        verbose_name='父事件',
    )
    resource_module = models.CharField('资源模块', max_length=32, blank=True, default='')
    resource_type = models.CharField('资源类型', max_length=64, blank=True, default='', db_index=True)
    resource_id = models.CharField('资源 ID', max_length=64, blank=True, default='', db_index=True)
    resource_name = models.CharField('资源名称', max_length=255, blank=True, default='', db_index=True)
    business_line = models.CharField('系统', max_length=64, blank=True, default='')
    environment = models.CharField('环境', max_length=32, blank=True, default='')
    tags = models.JSONField('标签', default=list, blank=True)
    related_resources = models.JSONField('关联资源', default=list, blank=True)
    changes = models.JSONField('变更内容', default=dict, blank=True)
    metadata = models.JSONField('元数据', default=dict, blank=True)
    is_demo = models.BooleanField('演示数据', default=False)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    application = models.CharField('Application', max_length=128, blank=True, default='', db_index=True)

    class Meta:
        verbose_name = '事件记录'
        verbose_name_plural = '事件记录'
        ordering = ['-occurred_at', '-id']
        indexes = [
            models.Index(fields=['module', 'occurred_at'], name='eventwall_e_module__482151_idx'),
            models.Index(fields=['module', 'result', 'occurred_at'], name='eventwall_e_module__7ab027_idx'),
            models.Index(fields=['resource_type', 'resource_id', 'occurred_at'], name='eventwall_e_resourc_0fd175_idx'),
            models.Index(fields=['actor_username', 'occurred_at'], name='eventwall_e_actor_u_85ce0f_idx'),
        ]

    def __str__(self):
        return f'[{self.module}] {self.title}'


def build_event_source_token_hash(token):
    return hashlib.sha256(str(token or '').encode('utf-8')).hexdigest()


class EventSource(models.Model):
    KIND_BUILTIN = 'builtin'
    KIND_EXTERNAL = 'external'
    KIND_CHOICES = [
        (KIND_BUILTIN, '平台内置'),
        (KIND_EXTERNAL, '外部接入'),
    ]

    TYPE_BUILTIN_WORKORDER = 'builtin_workorder'
    TYPE_BUILTIN_TASK = 'builtin_task'
    TYPE_BUILTIN_K8S = 'builtin_k8s'
    TYPE_JIRA = 'jira'
    TYPE_JENKINS = 'jenkins'
    TYPE_ARGOCD = 'argocd'
    TYPE_GITLAB = 'gitlab'
    TYPE_CUSTOM = 'custom'
    TYPE_CHOICES = [
        (TYPE_BUILTIN_WORKORDER, '工单系统'),
        (TYPE_BUILTIN_TASK, '任务中心'),
        (TYPE_BUILTIN_K8S, 'K8s 事件'),
        (TYPE_JIRA, 'Jira'),
        (TYPE_JENKINS, 'Jenkins'),
        (TYPE_ARGOCD, 'ArgoCD'),
        (TYPE_GITLAB, 'GitLab'),
        (TYPE_CUSTOM, '自定义事件源'),
    ]

    STATUS_HEALTHY = 'healthy'
    STATUS_WARNING = 'warning'
    STATUS_DISABLED = 'disabled'
    STATUS_NOT_CONFIGURED = 'not_configured'
    STATUS_CHOICES = [
        (STATUS_HEALTHY, '健康'),
        (STATUS_WARNING, '待关注'),
        (STATUS_DISABLED, '已停用'),
        (STATUS_NOT_CONFIGURED, '未配置'),
    ]

    AUTH_NONE = 'none'
    AUTH_TOKEN = 'token'
    AUTH_BASIC = 'basic'
    AUTH_WEBHOOK = 'webhook'
    AUTH_CHOICES = [
        (AUTH_NONE, '无需认证'),
        (AUTH_TOKEN, 'Token'),
        (AUTH_BASIC, 'Basic Auth'),
        (AUTH_WEBHOOK, 'Webhook Token'),
    ]

    code = models.SlugField('接入类型', max_length=64, unique=True)
    name = models.CharField('事件源名称', max_length=128)
    source_kind = models.CharField('事件源类别', max_length=16, choices=KIND_CHOICES)
    source_type = models.CharField('事件源类型', max_length=32, choices=TYPE_CHOICES)
    description = models.CharField('说明', max_length=255, blank=True, default='')
    enabled = models.BooleanField('启用状态', default=False)
    status = models.CharField('健康状态', max_length=32, choices=STATUS_CHOICES, default=STATUS_NOT_CONFIGURED)
    endpoint_url = models.URLField('外部地址', max_length=512, blank=True, default='')
    auth_type = models.CharField('认证方式', max_length=16, choices=AUTH_CHOICES, default=AUTH_WEBHOOK)
    token_hash = models.CharField('接入令牌哈希', max_length=64, blank=True, default='')
    token_preview = models.CharField('令牌预览', max_length=24, blank=True, default='')
    config = models.JSONField('采集配置', default=dict, blank=True)
    field_mapping = models.JSONField('字段映射', default=dict, blank=True)
    last_sync_at = models.DateTimeField('最近同步时间', null=True, blank=True)
    last_event_at = models.DateTimeField('最近事件时间', null=True, blank=True)
    last_error = models.CharField('最近错误', max_length=255, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '事件源'
        verbose_name_plural = '事件源'
        ordering = ['source_kind', 'source_type', 'code']
        indexes = [
            models.Index(fields=['source_kind', 'source_type'], name='eventwall_e_source__b65c96_idx'),
            models.Index(fields=['enabled', 'status'], name='eventwall_e_enabled_985ed8_idx'),
        ]

    def __str__(self):
        return self.name

    def issue_token(self):
        token = secrets.token_urlsafe(32)
        self.token_hash = build_event_source_token_hash(token)
        self.token_preview = f'{token[:8]}...{token[-4:]}'
        return token

    def verify_token(self, token):
        if not self.token_hash or not token:
            return False
        return secrets.compare_digest(self.token_hash, build_event_source_token_hash(token))


class EventEnvironment(models.Model):
    code = models.CharField('环境标识', max_length=64, unique=True)
    name = models.CharField('环境名称', max_length=128)
    aliases = models.JSONField('环境别名', default=list, blank=True)
    description = models.CharField('说明', max_length=255, blank=True, default='')
    enabled = models.BooleanField('启用状态', default=True, db_index=True)
    sort_order = models.PositiveIntegerField('排序', default=100)
    last_seen_at = models.DateTimeField('最近事件时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '事件中心环境'
        verbose_name_plural = '事件中心环境'
        ordering = ['sort_order', 'code']
        indexes = [
            models.Index(fields=['enabled', 'sort_order'], name='eventwall_env_enabled_sort_idx'),
        ]

    def __str__(self):
        return self.name or self.code

    def save(self, *args, **kwargs):
        self.code = str(self.code or '').strip()
        self.name = str(self.name or self.code).strip()
        self.aliases = self.normalized_aliases()
        super().save(*args, **kwargs)

    def normalized_aliases(self):
        values = []
        seen = {str(self.code or '').strip().lower(), str(self.name or '').strip().lower()}
        for item in self.aliases or []:
            value = str(item or '').strip()
            key = value.lower()
            if not value or key in seen:
                continue
            seen.add(key)
            values.append(value)
        return values
