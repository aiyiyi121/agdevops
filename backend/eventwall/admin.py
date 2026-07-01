from django.contrib import admin

from .models import EventEnvironment, EventRecord, EventSource


@admin.register(EventRecord)
class EventRecordAdmin(admin.ModelAdmin):
    list_display = (
        'occurred_at',
        'module',
        'action',
        'result',
        'actor_username',
        'resource_type',
        'resource_name',
        'title',
    )
    list_filter = ('module', 'category', 'action', 'result', 'severity', 'source_type', 'is_demo')
    search_fields = ('title', 'summary', 'actor_username', 'resource_name', 'correlation_id')


@admin.register(EventSource)
class EventSourceAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'source_kind', 'source_type', 'enabled', 'status', 'last_event_at')
    list_filter = ('source_kind', 'source_type', 'enabled', 'status')
    search_fields = ('code', 'name', 'description')


@admin.register(EventEnvironment)
class EventEnvironmentAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'enabled', 'sort_order', 'last_seen_at')
    list_filter = ('enabled',)
    search_fields = ('code', 'name', 'description')

