from django.db import models


class ServiceTemplate(models.Model):
    """内置中间件服务模板"""

    CATEGORY_CHOICES = [
        ('database', '数据库'),
        ('cache', '缓存'),
        ('cicd', 'CI/CD'),
        ('monitoring', '监控与日志'),
        ('security', '安全运维'),
        ('devenv', '开发环境'),
        ('middleware', '中间件'),
    ]

    name = models.CharField('服务名称', max_length=64, unique=True)
    icon = models.CharField('图标标识', max_length=64, help_text='前端图标名或 emoji')
    category = models.CharField('分类', max_length=32, choices=CATEGORY_CHOICES)
    description = models.CharField('简介', max_length=256, default='')
    versions = models.JSONField('可用版本列表', default=list, help_text='如 ["8.0","5.7"]')
    docker_compose_template = models.TextField('docker-compose 模板', help_text='Jinja2 变量: {{version}}, {{port}}, {{password}} 等')
    env_schema = models.JSONField(
        '配置项定义', default=list,
        help_text='[{"key":"port","label":"端口","default":"3306","required":true}, ...]',
    )
    is_active = models.BooleanField('启用', default=True)
    sort_order = models.IntegerField('排序权重', default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = '服务模板'
        verbose_name_plural = '服务模板'
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name


class ServiceDeployment(models.Model):
    """服务部署实例"""

    STATUS_CHOICES = [
        ('pending', '待部署'),
        ('deploying', '部署中'),
        ('running', '运行中'),
        ('stopped', '已停止'),
        ('failed', '部署失败'),
        ('removing', '卸载中'),
    ]

    template = models.ForeignKey(ServiceTemplate, on_delete=models.CASCADE, verbose_name='服务模板')
    host = models.ForeignKey('ops.Host', on_delete=models.CASCADE, verbose_name='目标主机')
    version = models.CharField('部署版本', max_length=32)
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES, default='pending')
    env_config = models.JSONField('部署配置', default=dict, help_text='用户填写的参数键值对')
    deploy_log = models.TextField('部署日志', blank=True, default='')
    deployer = models.CharField('部署人', max_length=64, default='admin')
    deploy_dir = models.CharField('部署目录', max_length=256, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '服务部署'
        verbose_name_plural = '服务部署'
        ordering = ['-created_at']
        unique_together = [('template', 'host')]

    def __str__(self):
        return f'{self.template.name} @ {self.host.hostname}'
