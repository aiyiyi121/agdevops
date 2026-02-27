from rest_framework import viewsets, status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.db.models import Count, Avg
from .models import Host, Deployment, Alert, LogEntry
from .serializers import (
    HostSerializer, DeploymentSerializer,
    AlertSerializer, LogEntrySerializer,
)


class HostViewSet(viewsets.ModelViewSet):
    """主机管理"""
    queryset = Host.objects.all()
    serializer_class = HostSerializer
    search_fields = ['hostname', 'ip_address']


class DeploymentViewSet(viewsets.ModelViewSet):
    """部署管理"""
    queryset = Deployment.objects.select_related('host').all()
    serializer_class = DeploymentSerializer
    search_fields = ['app_name', 'version', 'deployer']


class AlertViewSet(viewsets.ModelViewSet):
    """告警管理"""
    queryset = Alert.objects.select_related('host').all()
    serializer_class = AlertSerializer
    search_fields = ['title', 'source', 'message']


class LogEntryViewSet(viewsets.ModelViewSet):
    """日志管理"""
    queryset = LogEntry.objects.select_related('host').all()
    serializer_class = LogEntrySerializer
    search_fields = ['service', 'message']


@api_view(['GET'])
def dashboard_stats(request):
    """仪表盘统计数据"""
    host_total = Host.objects.count()
    host_status = dict(Host.objects.values_list('status').annotate(count=Count('id')).values_list('status', 'count'))
    host_avg = Host.objects.aggregate(
        avg_cpu=Avg('cpu_usage'),
        avg_memory=Avg('memory_usage'),
        avg_disk=Avg('disk_usage'),
    )

    deploy_total = Deployment.objects.count()
    deploy_status = dict(
        Deployment.objects.values_list('status').annotate(count=Count('id')).values_list('status', 'count')
    )

    alert_total = Alert.objects.count()
    alert_unacked = Alert.objects.filter(is_acknowledged=False).count()
    alert_levels = dict(
        Alert.objects.values_list('level').annotate(count=Count('id')).values_list('level', 'count')
    )

    recent_deploys = DeploymentSerializer(
        Deployment.objects.select_related('host').all()[:10], many=True
    ).data

    recent_alerts = AlertSerializer(
        Alert.objects.select_related('host').filter(is_acknowledged=False)[:10], many=True
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
            'success': deploy_status.get('success', 0),
            'failed': deploy_status.get('failed', 0),
            'running': deploy_status.get('running', 0),
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
