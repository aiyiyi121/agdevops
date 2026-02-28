from rest_framework import serializers
from .models import DataSource, SqlOrder, QueryOrder, SqlCheckResult


class DataSourceSerializer(serializers.ModelSerializer):
    status_label = serializers.SerializerMethodField()

    class Meta:
        model = DataSource
        fields = '__all__'
        extra_kwargs = {
            'password': {'write_only': True},
        }

    def get_status_label(self, obj):
        return '启用' if obj.is_active else '停用'


class SqlCheckResultSerializer(serializers.ModelSerializer):
    level_display = serializers.CharField(source='get_level_display', read_only=True)

    class Meta:
        model = SqlCheckResult
        fields = '__all__'


class SqlOrderSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    sql_type_display = serializers.CharField(source='get_sql_type_display', read_only=True)
    datasource_name = serializers.CharField(source='datasource.name', read_only=True)
    check_results = SqlCheckResultSerializer(many=True, read_only=True)

    class Meta:
        model = SqlOrder
        fields = '__all__'


class QueryOrderSerializer(serializers.ModelSerializer):
    datasource_name = serializers.CharField(source='datasource.name', read_only=True)

    class Meta:
        model = QueryOrder
        fields = '__all__'
