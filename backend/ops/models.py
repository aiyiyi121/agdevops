from django.db import models


class Host(models.Model):
    STATUS_CHOICES = [
        ('online', '在线'),
        ('offline', '离线'),
        ('warning', '告警'),
    ]

    hostname = models.CharField('主机名', max_length=128, unique=True)
    ip_address = models.GenericIPAddressField('IP 地址')
    os_type = models.CharField('操作系统', max_length=64, default='Linux')
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES, default='online')
    cpu_usage = models.FloatField('CPU 使用率 (%)', default=0)
    memory_usage = models.FloatField('内存使用率 (%)', default=0)
    disk_usage = models.FloatField('磁盘使用率 (%)', default=0)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '主机'
        verbose_name_plural = '主机'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.hostname} ({self.ip_address})'


class Deployment(models.Model):
    STATUS_CHOICES = [
        ('success', '成功'),
        ('failed', '失败'),
        ('running', '部署中'),
        ('pending', '待部署'),
        ('rollback', '已回滚'),
    ]
    ENV_CHOICES = [
        ('production', '生产'),
        ('staging', '预发布'),
        ('testing', '测试'),
        ('development', '开发'),
    ]

    app_name = models.CharField('应用名称', max_length=128)
    version = models.CharField('版本号', max_length=64)
    environment = models.CharField('环境', max_length=32, choices=ENV_CHOICES, default='testing')
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES, default='pending')
    deployer = models.CharField('部署人', max_length=64, default='admin')
    description = models.TextField('描述', blank=True, default='')
    host = models.ForeignKey(Host, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='部署主机')
    deployed_at = models.DateTimeField('部署时间', auto_now_add=True)

    class Meta:
        verbose_name = '部署记录'
        verbose_name_plural = '部署记录'
        ordering = ['-deployed_at']

    def __str__(self):
        return f'{self.app_name} v{self.version} -> {self.environment}'


class Alert(models.Model):
    LEVEL_CHOICES = [
        ('critical', '严重'),
        ('warning', '警告'),
        ('info', '信息'),
    ]

    title = models.CharField('告警标题', max_length=256)
    level = models.CharField('级别', max_length=16, choices=LEVEL_CHOICES, default='info')
    source = models.CharField('来源', max_length=128)
    message = models.TextField('详情')
    is_acknowledged = models.BooleanField('已确认', default=False)
    host = models.ForeignKey(Host, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='关联主机')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '告警'
        verbose_name_plural = '告警'
        ordering = ['-created_at']

    def __str__(self):
        return f'[{self.level}] {self.title}'


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
