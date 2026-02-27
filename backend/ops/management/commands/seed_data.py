import random
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from ops.models import Host, Deployment, Alert, LogEntry


class Command(BaseCommand):
    help = '生成 Mock 演示数据'

    def handle(self, *args, **options):
        self.stdout.write('正在清除旧数据...')
        Host.objects.all().delete()
        Deployment.objects.all().delete()
        Alert.objects.all().delete()
        LogEntry.objects.all().delete()

        self.stdout.write('正在生成主机数据...')
        hosts = []
        host_configs = [
            ('web-server-01', '192.168.1.10', 'CentOS 7.9'),
            ('web-server-02', '192.168.1.11', 'CentOS 7.9'),
            ('app-server-01', '192.168.1.20', 'Ubuntu 22.04'),
            ('app-server-02', '192.168.1.21', 'Ubuntu 22.04'),
            ('db-master', '192.168.1.30', 'CentOS 8'),
            ('db-slave-01', '192.168.1.31', 'CentOS 8'),
            ('redis-01', '192.168.1.40', 'Ubuntu 20.04'),
            ('redis-02', '192.168.1.41', 'Ubuntu 20.04'),
            ('nginx-lb-01', '192.168.1.50', 'Debian 11'),
            ('monitor-01', '192.168.1.60', 'Ubuntu 22.04'),
            ('k8s-master', '10.0.1.10', 'Ubuntu 22.04'),
            ('k8s-worker-01', '10.0.1.11', 'Ubuntu 22.04'),
            ('k8s-worker-02', '10.0.1.12', 'Ubuntu 22.04'),
            ('es-node-01', '192.168.2.10', 'CentOS 7.9'),
            ('mq-broker-01', '192.168.2.20', 'Debian 12'),
        ]
        for hostname, ip, os_type in host_configs:
            host = Host.objects.create(
                hostname=hostname,
                ip_address=ip,
                os_type=os_type,
                status=random.choices(['online', 'offline', 'warning'], weights=[80, 10, 10])[0],
                cpu_usage=round(random.uniform(5, 95), 1),
                memory_usage=round(random.uniform(20, 90), 1),
                disk_usage=round(random.uniform(10, 85), 1),
            )
            hosts.append(host)

        self.stdout.write('正在生成部署记录...')
        apps = [
            ('user-service', 'v2.'),
            ('order-service', 'v3.'),
            ('payment-service', 'v1.'),
            ('gateway', 'v4.'),
            ('admin-panel', 'v1.'),
            ('notification-service', 'v2.'),
        ]
        envs = ['production', 'staging', 'testing', 'development']
        deploy_statuses = ['success', 'success', 'success', 'failed', 'running', 'rollback']
        for i in range(30):
            app_name, version_prefix = random.choice(apps)
            version = f'{version_prefix}{random.randint(0,9)}.{random.randint(0,20)}'
            Deployment.objects.create(
                app_name=app_name,
                version=version,
                environment=random.choice(envs),
                status=random.choice(deploy_statuses),
                deployer=random.choice(['admin', 'devops-bot', 'zhangsan', 'lisi', 'wangwu']),
                description=f'{app_name} {version} 部署',
                host=random.choice(hosts),
            )

        self.stdout.write('正在生成告警数据...')
        alert_templates = [
            ('CPU 使用率超过阈值', 'critical', 'Prometheus', 'CPU 使用率持续 5 分钟超过 90%'),
            ('内存使用率过高', 'warning', 'Prometheus', '内存使用率超过 80%'),
            ('磁盘空间不足', 'critical', 'Zabbix', '磁盘使用率超过 95%，请及时清理'),
            ('服务响应超时', 'warning', 'APM', '服务平均响应时间超过 3 秒'),
            ('数据库连接池满', 'critical', 'MySQL Monitor', '连接池使用率 100%'),
            ('SSL 证书即将过期', 'info', 'CertBot', 'SSL 证书将在 7 天后过期'),
            ('容器重启次数异常', 'warning', 'Kubernetes', 'Pod 在 1 小时内重启超过 5 次'),
            ('网络延迟升高', 'info', 'PingMonitor', '网络延迟超过 200ms'),
        ]
        for i in range(20):
            template = random.choice(alert_templates)
            Alert.objects.create(
                title=template[0],
                level=template[1],
                source=template[2],
                message=template[3],
                is_acknowledged=random.choice([True, False, False]),
                host=random.choice(hosts),
            )

        self.stdout.write('正在生成日志数据...')
        services = ['user-service', 'order-service', 'gateway', 'nginx', 'mysql', 'redis']
        log_messages = {
            'error': [
                'Connection refused to database',
                'NullPointerException at line 42',
                'Out of memory error',
                'Permission denied: /var/log/app.log',
                'Timeout while waiting for response',
            ],
            'warning': [
                'Slow query detected: 2.5s',
                'High memory usage: 85%',
                'Retry attempt 3/5 for API call',
                'Deprecated API version used',
                'Connection pool reaching limit',
            ],
            'info': [
                'Service started successfully',
                'Request processed in 120ms',
                'Configuration reloaded',
                'Health check passed',
                'Scheduled task completed',
            ],
            'debug': [
                'Entering function processOrder()',
                'Cache hit for key: user_123',
                'Query executed: SELECT * FROM users',
                'WebSocket connection established',
            ],
        }
        for i in range(50):
            level = random.choices(['error', 'warning', 'info', 'debug'], weights=[10, 20, 50, 20])[0]
            LogEntry.objects.create(
                level=level,
                service=random.choice(services),
                message=random.choice(log_messages[level]),
                host=random.choice(hosts),
            )

        self.stdout.write(self.style.SUCCESS(
            f'✅ 数据生成完成: '
            f'{Host.objects.count()} 主机, '
            f'{Deployment.objects.count()} 部署记录, '
            f'{Alert.objects.count()} 告警, '
            f'{LogEntry.objects.count()} 日志'
        ))
