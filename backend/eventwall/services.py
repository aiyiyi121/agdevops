import json
import logging
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from django.db import models
from django.db.utils import OperationalError, ProgrammingError
from django.utils import timezone

from .models import EventEnvironment, EventRecord

logger = logging.getLogger(__name__)

MASK = '***'
SENSITIVE_KEYWORDS = {
    'password',
    'secret',
    'token',
    'access_key',
    'private_key',
    'cert_content',
    'key_content',
    'ssh_password',
    'kubeconfig',
}

RESOURCE_NAME_FIELDS = (
    'name',
    'title',
    'code',
    'username',
    'hostname',
    'domain',
    'app_name',
    'service_name',
    'group',
)


def _is_sensitive_key(key):
    lowered = str(key or '').lower()
    return any(token in lowered for token in SENSITIVE_KEYWORDS)


def sanitize_value(value, key=''):
    if _is_sensitive_key(key):
        return MASK
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, models.Model):
        return str(value.pk)
    if isinstance(value, dict):
        return {str(k): sanitize_value(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_value(item, key) for item in value]
    if isinstance(value, tuple):
        return [sanitize_value(item, key) for item in value]
    return value


def summarize_sql(value):
    sql = str(value or '').strip()
    if not sql:
        return ''
    normalized = ' '.join(sql.split())
    return normalized[:160]


def snapshot_instance(instance, exclude_fields=None):
    exclude_fields = set(exclude_fields or [])
    data = {}
    for field in instance._meta.fields:
        if field.name in exclude_fields:
            continue
        raw = getattr(instance, field.name)
        if field.is_relation:
            data[field.name] = getattr(instance, f'{field.name}_id')
            continue
        if field.name == 'sql_content':
            data[field.name] = summarize_sql(raw)
            continue
        data[field.name] = sanitize_value(raw, field.name)
    return data


def diff_snapshots(before, after):
    changes = {}
    keys = sorted(set(before.keys()) | set(after.keys()))
    for key in keys:
        if before.get(key) == after.get(key):
            continue
        changes[key] = {
            'before': before.get(key),
            'after': after.get(key),
        }
    return changes


def infer_resource_name(instance, custom_fields=None):
    for field_name in custom_fields or RESOURCE_NAME_FIELDS:
        value = getattr(instance, field_name, '')
        if value:
            return str(value)
    return str(instance)


def infer_application_name(instance):
    for field_name in ('app_name', 'application', 'database', 'release_name'):
        value = getattr(instance, field_name, '')
        if value:
            return str(value)
    template = getattr(instance, 'template', None)
    if getattr(template, 'name', ''):
        return str(template.name)
    return ''


def build_resource(module, resource_type, resource_id='', resource_name='', **extra):
    payload = {
        'module': module,
        'type': resource_type,
        'id': str(resource_id or ''),
        'name': str(resource_name or ''),
    }
    payload.update({key: value for key, value in extra.items() if value not in (None, '', [], {})})
    return payload


def build_correlation_id(prefix, resource_id='', fallback=''):
    base = str(resource_id or fallback or uuid4().hex[:12])
    return f'{prefix}:{base}'


def build_request_context(request=None):
    if not request:
        return {
            'actor_type': EventRecord.ACTOR_SYSTEM,
            'source_type': EventRecord.SOURCE_SYSTEM,
            'actor_username': 'system',
            'actor_display': 'System',
            'request_method': '',
            'source_path': '',
            'ip_address': '',
        }
    username = getattr(getattr(request, 'user', None), 'username', '') or 'anonymous'
    display_name = username
    if getattr(request.user, 'first_name', '') or getattr(request.user, 'last_name', ''):
        display_name = f'{request.user.first_name}{request.user.last_name}'.strip() or username
    ip = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or request.META.get('REMOTE_ADDR', '')
    source_type = getattr(request, '_eventwall_source_type', EventRecord.SOURCE_HTTP)
    return {
        'actor_type': EventRecord.ACTOR_USER,
        'source_type': source_type,
        'actor_username': username,
        'actor_display': display_name,
        'request_method': getattr(request, 'method', ''),
        'source_path': getattr(request, 'path', ''),
        'ip_address': ip,
    }


def record_event(
    *,
    module,
    category,
    action,
    title,
    summary='',
    detail='',
    result=EventRecord.RESULT_SUCCESS,
    severity=EventRecord.SEVERITY_INFO,
    request=None,
    actor_username='',
    actor_display='',
    actor_type='',
    source_type='',
    request_method='',
    source_path='',
    ip_address='',
    resource_module='',
    resource_type='',
    resource_id='',
    resource_name='',
    business_line='',
    environment='',
    application='',
    tags=None,
    related_resources=None,
    changes=None,
    metadata=None,
    correlation_id='',
    parent_event=None,
    is_demo=False,
    occurred_at=None,
):
    if result == EventRecord.RESULT_REJECTED:
        return None
    try:
        context = build_request_context(request)
        event_metadata = dict(metadata or {})
        environment_resolution = resolve_event_environment(environment, strict=False)
        normalized_environment = environment_resolution['code']
        if environment:
            event_metadata.setdefault('environment_raw', environment_resolution['raw'])
            event_metadata['environment_matched'] = environment_resolution['matched']
            if environment_resolution['matched']:
                event_metadata.setdefault('environment_name', environment_resolution['name'])
            else:
                event_metadata['environment_unmatched'] = True
        payload = EventRecord.objects.create(
            occurred_at=occurred_at or timezone.now(),
            module=module,
            category=category,
            action=action,
            result=result,
            severity=severity,
            title=title,
            summary=summary or title,
            detail=detail,
            actor_type=actor_type or context['actor_type'],
            actor_username=actor_username or context['actor_username'],
            actor_display=actor_display or context['actor_display'],
            source_type=source_type or context['source_type'],
            request_method=request_method or context['request_method'],
            source_path=source_path or context['source_path'],
            ip_address=ip_address or context['ip_address'],
            correlation_id=correlation_id,
            parent_event=parent_event,
            resource_module=resource_module or module,
            resource_type=resource_type,
            resource_id=str(resource_id or ''),
            resource_name=resource_name,
            business_line=business_line,
            environment=normalized_environment,
            application=application,
            tags=sanitize_value(tags or [], 'tags'),
            related_resources=sanitize_value(related_resources or [], 'related_resources'),
            changes=sanitize_value(changes or {}, 'changes'),
            metadata=sanitize_value(event_metadata, 'metadata'),
            is_demo=is_demo,
        )
        if normalized_environment and environment_resolution['matched']:
            touch_event_environment(normalized_environment, payload.occurred_at)
        return payload
    except Exception:
        logger.exception('record_event failed: %s %s', module, title)
        return None


def record_model_event(
    *,
    request,
    module,
    resource_type,
    resource_label,
    instance,
    action,
    before=None,
    after=None,
    category='resource_change',
    result=EventRecord.RESULT_SUCCESS,
    severity=EventRecord.SEVERITY_INFO,
    related_resources=None,
    metadata=None,
    tags=None,
    correlation_id='',
    name_fields=None,
    application='',
):
    resource_name = infer_resource_name(instance, custom_fields=name_fields)
    if action == 'create':
        title = f'创建{resource_label}'
        summary = f'{resource_label} {resource_name} 已创建'
    elif action == 'delete':
        title = f'删除{resource_label}'
        summary = f'{resource_label} {resource_name} 已删除'
    else:
        title = f'更新{resource_label}'
        changes = diff_snapshots(before or {}, after or {})
        summary = f'{resource_label} {resource_name} 已更新'
        if changes:
            summary = f'{summary}，变更字段 {len(changes)} 个'
    changes = diff_snapshots(before or {}, after or {}) if action == 'update' else {}
    return record_event(
        request=request,
        module=module,
        category=category,
        action=action,
        result=result,
        severity=severity,
        title=title,
        summary=summary,
        resource_type=resource_type,
        resource_id=instance.pk,
        resource_name=resource_name,
        business_line=getattr(instance, 'business_line', '') or '',
        environment=getattr(instance, 'environment', '') or '',
        application=application or infer_application_name(instance),
        related_resources=related_resources or [],
        changes=changes,
        metadata=metadata or {},
        tags=tags or [],
        correlation_id=correlation_id or build_correlation_id(resource_type, instance.pk),
    )


def build_json_preview(payload):
    try:
        text = json.dumps(sanitize_value(payload or {}, 'payload'), ensure_ascii=False)
    except TypeError:
        text = str(payload)
    return text[:200]


def _normalize_environment_key(value):
    return str(value or '').strip().lower()


def resolve_event_environment(value, *, strict=False):
    raw_value = str(value or '').strip()
    if not raw_value:
        return {
            'ok': not strict,
            'code': '',
            'name': '',
            'raw': '',
            'matched': False,
            'detail': '环境不能为空。' if strict else '',
        }

    try:
        environments = list(EventEnvironment.objects.filter(enabled=True))
    except (OperationalError, ProgrammingError):
        return {
            'ok': not strict,
            'code': raw_value,
            'name': raw_value,
            'raw': raw_value,
            'matched': False,
            'detail': '事件中心环境表尚未完成迁移。' if strict else '',
        }
    if not environments:
        return {
            'ok': not strict,
            'code': raw_value,
            'name': raw_value,
            'raw': raw_value,
            'matched': False,
            'detail': '事件中心尚未配置可用环境。' if strict else '',
        }

    target = _normalize_environment_key(raw_value)
    for environment in environments:
        candidates = [environment.code, environment.name, *(environment.aliases or [])]
        if target in {_normalize_environment_key(item) for item in candidates if item}:
            return {
                'ok': True,
                'code': environment.code,
                'name': environment.name,
                'raw': raw_value,
                'matched': True,
                'detail': '',
            }

    return {
        'ok': False,
        'code': raw_value,
        'name': raw_value,
        'raw': raw_value,
        'matched': False,
        'detail': f'环境 `{raw_value}` 未在事件中心环境中配置。',
    }


def touch_event_environment(code, occurred_at=None):
    if not code:
        return
    try:
        EventEnvironment.objects.filter(code=code).update(last_seen_at=occurred_at or timezone.now())
    except (OperationalError, ProgrammingError):
        return
