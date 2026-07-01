from rest_framework import serializers

from .models import EventEnvironment, EventRecord, EventSource


class EventRecordSerializer(serializers.ModelSerializer):
    result_display = serializers.CharField(source='get_result_display', read_only=True)
    severity_display = serializers.CharField(source='get_severity_display', read_only=True)
    source_type_display = serializers.CharField(source='get_source_type_display', read_only=True)
    resource_key = serializers.SerializerMethodField()
    related_count = serializers.SerializerMethodField()
    system_name = serializers.CharField(source='business_line', read_only=True)

    class Meta:
        model = EventRecord
        fields = [
            'id',
            'occurred_at',
            'module',
            'category',
            'action',
            'result',
            'result_display',
            'severity',
            'severity_display',
            'title',
            'summary',
            'detail',
            'actor_type',
            'actor_username',
            'actor_display',
            'source_type',
            'source_type_display',
            'request_method',
            'source_path',
            'ip_address',
            'correlation_id',
            'parent_event',
            'resource_module',
            'resource_type',
            'resource_id',
            'resource_name',
            'resource_key',
            'system_name',
            'business_line',
            'environment',
            'application',
            'tags',
            'related_resources',
            'related_count',
            'changes',
            'metadata',
            'is_demo',
        ]

    def get_resource_key(self, obj):
        if obj.resource_type and obj.resource_id:
            return f'{obj.resource_type}:{obj.resource_id}'
        return ''

    def get_related_count(self, obj):
        return len(obj.related_resources or [])


class EventSourceSerializer(serializers.ModelSerializer):
    source_kind_display = serializers.CharField(source='get_source_kind_display', read_only=True)
    source_type_display = serializers.CharField(source='get_source_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    auth_type_display = serializers.CharField(source='get_auth_type_display', read_only=True)
    webhook_path = serializers.SerializerMethodField()
    recent_event_count = serializers.SerializerMethodField()

    class Meta:
        model = EventSource
        fields = [
            'id',
            'code',
            'name',
            'source_kind',
            'source_kind_display',
            'source_type',
            'source_type_display',
            'description',
            'enabled',
            'status',
            'status_display',
            'endpoint_url',
            'auth_type',
            'auth_type_display',
            'token_preview',
            'config',
            'field_mapping',
            'last_sync_at',
            'last_event_at',
            'last_error',
            'webhook_path',
            'recent_event_count',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'token_preview',
            'last_sync_at',
            'last_event_at',
            'last_error',
            'created_at',
            'updated_at',
        ]

    def get_webhook_path(self, obj):
        if obj.source_kind != EventSource.KIND_EXTERNAL:
            return ''
        return f'/api/event-sources/{obj.code}/ingest/'

    def get_recent_event_count(self, obj):
        counts = self.context.get('recent_event_counts') or {}
        return counts.get(obj.code, 0)


class EventSourceTokenSerializer(serializers.Serializer):
    token = serializers.CharField(read_only=True)
    token_preview = serializers.CharField(read_only=True)


class EventSourceIngestSerializer(serializers.Serializer):
    event_id = serializers.CharField(max_length=128, required=False, allow_blank=True)
    occurred_at = serializers.DateTimeField(required=False)
    title = serializers.CharField(max_length=255)
    summary = serializers.CharField(max_length=255, required=False, allow_blank=True)
    detail = serializers.CharField(required=False, allow_blank=True)
    event_category = serializers.CharField(max_length=64, required=False, allow_blank=True)
    event_type = serializers.CharField(max_length=64, required=False, allow_blank=True)
    action = serializers.CharField(max_length=64, required=False, allow_blank=True)
    result = serializers.ChoiceField(choices=EventRecord.RESULT_CHOICES, required=False, default=EventRecord.RESULT_SUCCESS)
    severity = serializers.ChoiceField(choices=EventRecord.SEVERITY_CHOICES, required=False, default=EventRecord.SEVERITY_INFO)
    actor = serializers.CharField(max_length=64, required=False, allow_blank=True)
    system_name = serializers.CharField(max_length=64, required=False, allow_blank=True)
    business_line = serializers.CharField(max_length=64, required=False, allow_blank=True)
    environment = serializers.CharField(max_length=32, required=False, allow_blank=True)
    application = serializers.CharField(max_length=128, required=False, allow_blank=True)
    resource_type = serializers.CharField(max_length=64, required=False, allow_blank=True)
    resource_id = serializers.CharField(max_length=64, required=False, allow_blank=True)
    resource_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    correlation_id = serializers.CharField(max_length=128, required=False, allow_blank=True)
    tags = serializers.ListField(child=serializers.CharField(max_length=64), required=False)
    related_resources = serializers.ListField(child=serializers.DictField(), required=False)
    changes = serializers.DictField(required=False)
    metadata = serializers.DictField(required=False)


class EventEnvironmentSerializer(serializers.ModelSerializer):
    event_count = serializers.SerializerMethodField()

    class Meta:
        model = EventEnvironment
        fields = [
            'id',
            'code',
            'name',
            'aliases',
            'description',
            'enabled',
            'sort_order',
            'last_seen_at',
            'event_count',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['last_seen_at', 'event_count', 'created_at', 'updated_at']

    def validate_code(self, value):
        value = str(value or '').strip()
        if not value:
            raise serializers.ValidationError('请填写环境标识。')
        return value

    def validate_name(self, value):
        value = str(value or '').strip()
        if not value:
            raise serializers.ValidationError('请填写环境名称。')
        return value

    def validate_aliases(self, value):
        if value in (None, ''):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError('环境别名必须是数组。')
        aliases = []
        seen = set()
        for item in value:
            alias = str(item or '').strip()
            key = alias.lower()
            if alias and key not in seen:
                seen.add(key)
                aliases.append(alias)
        return aliases

    def get_event_count(self, obj):
        counts = self.context.get('environment_event_counts') or {}
        return counts.get(obj.code, 0)
