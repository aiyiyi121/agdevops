from rest_framework import serializers
from .models import Host, Deployment, Alert, LogEntry


class HostSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Host
        fields = '__all__'


class DeploymentSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    environment_display = serializers.CharField(source='get_environment_display', read_only=True)
    host_name = serializers.CharField(source='host.hostname', read_only=True, default='')

    class Meta:
        model = Deployment
        fields = '__all__'


class AlertSerializer(serializers.ModelSerializer):
    level_display = serializers.CharField(source='get_level_display', read_only=True)
    host_name = serializers.CharField(source='host.hostname', read_only=True, default='')

    class Meta:
        model = Alert
        fields = '__all__'


class LogEntrySerializer(serializers.ModelSerializer):
    level_display = serializers.CharField(source='get_level_display', read_only=True)
    host_name = serializers.CharField(source='host.hostname', read_only=True, default='')

    class Meta:
        model = LogEntry
        fields = '__all__'
