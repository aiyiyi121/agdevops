from django.db import models
from django.utils import timezone


class DataSource(models.Model):
    """MySQL 数据源"""
    name = models.CharField('名称', max_length=128, unique=True)
    host = models.CharField('主机地址', max_length=256)
    port = models.PositiveIntegerField('端口', default=3306)
    user = models.CharField('用户名', max_length=128)
    password = models.CharField('密码', max_length=512)
    charset = models.CharField('字符集', max_length=32, default='utf8mb4')
    remark = models.TextField('备注', blank=True, default='')
    is_active = models.BooleanField('启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '数据源'
        verbose_name_plural = '数据源'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.host}:{self.port})'


class SqlOrder(models.Model):
    """SQL 工单"""
    STATUS_CHOICES = [
        ('pending', '待审核'),
        ('approved', '已通过'),
        ('rejected', '已驳回'),
        ('executing', '执行中'),
        ('executed', '已执行'),
        ('failed', '执行失败'),
    ]
    SQL_TYPE_CHOICES = [
        ('DDL', 'DDL'),
        ('DML', 'DML'),
    ]

    title = models.CharField('工单标题', max_length=256)
    datasource = models.ForeignKey(
        DataSource, on_delete=models.PROTECT, verbose_name='数据源',
    )
    database = models.CharField('目标数据库', max_length=128)
    sql_type = models.CharField(
        'SQL 类型', max_length=8, choices=SQL_TYPE_CHOICES, default='DML',
    )
    sql_content = models.TextField('SQL 内容')
    status = models.CharField(
        '状态', max_length=16, choices=STATUS_CHOICES, default='pending',
    )
    submitter = models.CharField('提交人', max_length=64, default='admin')
    reviewer = models.CharField('审核人', max_length=64, blank=True, default='')
    review_comment = models.TextField('审核备注', blank=True, default='')
    reviewed_at = models.DateTimeField('审核时间', null=True, blank=True)
    execute_log = models.TextField('执行日志', blank=True, default='')
    affected_rows = models.IntegerField('影响行数', null=True, blank=True)
    duration_ms = models.IntegerField('耗时(ms)', null=True, blank=True)
    executed_at = models.DateTimeField('执行时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = 'SQL 工单'
        verbose_name_plural = 'SQL 工单'
        ordering = ['-created_at']

    def __str__(self):
        return f'[{self.get_status_display()}] {self.title}'


class QueryOrder(models.Model):
    """查询工单"""
    datasource = models.ForeignKey(
        DataSource, on_delete=models.PROTECT, verbose_name='数据源',
    )
    database = models.CharField('目标数据库', max_length=128)
    sql_content = models.TextField('SQL 内容')
    submitter = models.CharField('提交人', max_length=64, default='admin')
    result_count = models.IntegerField('结果行数', null=True, blank=True)
    duration_ms = models.IntegerField('耗时(ms)', null=True, blank=True)
    created_at = models.DateTimeField('查询时间', auto_now_add=True)

    class Meta:
        verbose_name = '查询记录'
        verbose_name_plural = '查询记录'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.submitter} @ {self.datasource.name}/{self.database}'


class SqlCheckResult(models.Model):
    """SQL 检查结果"""
    LEVEL_CHOICES = [
        ('error', '错误'),
        ('warning', '警告'),
        ('info', '建议'),
    ]

    order = models.ForeignKey(
        SqlOrder, on_delete=models.CASCADE, related_name='check_results',
        verbose_name='关联工单',
    )
    level = models.CharField('级别', max_length=16, choices=LEVEL_CHOICES)
    rule_name = models.CharField('规则名', max_length=128)
    message = models.TextField('检查信息')
    line_no = models.IntegerField('行号', null=True, blank=True)

    class Meta:
        verbose_name = 'SQL 检查结果'
        verbose_name_plural = 'SQL 检查结果'

    def __str__(self):
        return f'[{self.level}] {self.rule_name}: {self.message[:50]}'
