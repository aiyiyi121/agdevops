from rest_framework import serializers
from .models import ServiceTemplate, ServiceDeployment


class ServiceTemplateSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(source='get_category_display', read_only=True)

    class Meta:
        model = ServiceTemplate
        fields = [
            'id', 'name', 'icon', 'category', 'category_display',
            'description', 'versions', 'env_schema', 'is_active', 'sort_order',
        ]


class ServiceDeploymentSerializer(serializers.ModelSerializer):
    template_name = serializers.CharField(source='template.name', read_only=True)
    template_icon = serializers.CharField(source='template.icon', read_only=True)
    host_name = serializers.CharField(source='host.hostname', read_only=True)
    host_ip = serializers.CharField(source='host.ip_address', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = ServiceDeployment
        fields = [
            'id', 'template', 'template_name', 'template_icon',
            'host', 'host_name', 'host_ip', 'version',
            'status', 'status_display', 'env_config', 'deploy_log',
            'deployer', 'deploy_dir', 'created_at', 'updated_at',
        ]
        read_only_fields = ['status', 'deploy_log', 'deploy_dir']


class DeployRequestSerializer(serializers.Serializer):
    """部署请求"""
    template_id = serializers.IntegerField()
    host_id = serializers.IntegerField()
    version = serializers.CharField(max_length=32)
    env_config = serializers.DictField(required=False, default=dict)
    deployer = serializers.CharField(max_length=64, default='admin')
