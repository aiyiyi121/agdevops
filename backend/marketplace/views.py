import threading
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view
from rest_framework.response import Response

from .models import ServiceTemplate, ServiceDeployment
from .serializers import (
    ServiceTemplateSerializer,
    ServiceDeploymentSerializer,
    DeployRequestSerializer,
)
from . import deployer


class ServiceTemplateViewSet(viewsets.ReadOnlyModelViewSet):
    """服务模板 — 只读列表 + 详情"""
    queryset = ServiceTemplate.objects.filter(is_active=True)
    serializer_class = ServiceTemplateSerializer
    pagination_class = None  # 模板数量少，不分页


class ServiceDeploymentViewSet(viewsets.ModelViewSet):
    """服务部署实例"""
    queryset = ServiceDeployment.objects.select_related('template', 'host')
    serializer_class = ServiceDeploymentSerializer

    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        """停止服务"""
        dep = self.get_object()
        deployer.stop_service(dep)
        return Response(ServiceDeploymentSerializer(dep).data)

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        """启动已停止的服务"""
        dep = self.get_object()
        deployer.start_service(dep)
        return Response(ServiceDeploymentSerializer(dep).data)

    @action(detail=True, methods=['post'])
    def remove(self, request, pk=None):
        """卸载服务"""
        dep = self.get_object()
        result = deployer.remove_service(dep)
        if result is None:
            return Response({'detail': '服务已卸载'}, status=status.HTTP_204_NO_CONTENT)
        return Response(ServiceDeploymentSerializer(result).data)

    @action(detail=True, methods=['get'])
    def logs(self, request, pk=None):
        """获取容器日志"""
        dep = self.get_object()
        tail = int(request.query_params.get('tail', 100))
        log_text = deployer.get_service_logs(dep, tail=tail)
        return Response({'logs': log_text})


@api_view(['POST'])
def deploy_service_view(request):
    """发起部署"""
    ser = DeployRequestSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    data = ser.validated_data

    try:
        template = ServiceTemplate.objects.get(pk=data['template_id'])
    except ServiceTemplate.DoesNotExist:
        return Response({'detail': '模板不存在'}, status=status.HTTP_404_NOT_FOUND)

    from ops.models import Host
    try:
        host = Host.objects.get(pk=data['host_id'])
    except Host.DoesNotExist:
        return Response({'detail': '主机不存在'}, status=status.HTTP_404_NOT_FOUND)

    # 检查是否已部署
    if ServiceDeployment.objects.filter(template=template, host=host).exists():
        return Response({'detail': f'{template.name} 已在 {host.hostname} 上部署'}, status=status.HTTP_400_BAD_REQUEST)

    dep = ServiceDeployment.objects.create(
        template=template,
        host=host,
        version=data['version'],
        env_config=data.get('env_config', {}),
        deployer=data.get('deployer', 'admin'),
    )

    # 后台线程执行部署
    thread = threading.Thread(target=deployer.deploy_service, args=(dep,), daemon=True)
    thread.start()

    return Response(ServiceDeploymentSerializer(dep).data, status=status.HTTP_201_CREATED)
