from rest_framework import serializers

from .models import (
    AIOpsAgentConfig,
    AIOpsChatMessage,
    AIOpsChatSession,
    AIOpsExternalTask,
    AIOpsKnowledgeEnvironment,
    AIOpsMCPServer,
    AIOpsModelInvocation,
    AIOpsModelProvider,
    AIOpsPendingAction,
    AIOpsRunbook,
    AIOpsRunbookVersion,
    AIOpsReviewKnowledge,
    AIOpsSkill,
    AIOpsToolInvocation,
)
from .services import _validate_mcp_stdio_command
from .services import _ensure_task_draft_title, _is_generic_task_title, get_model_provider_setup_hint


class AIOpsModelProviderSerializer(serializers.ModelSerializer):
    api_key = serializers.CharField(write_only=True, required=False, allow_blank=True)
    has_api_key = serializers.BooleanField(read_only=True)
    runtime_ready = serializers.SerializerMethodField()
    setup_hint = serializers.SerializerMethodField()

    class Meta:
        model = AIOpsModelProvider
        fields = [
            'id', 'name', 'provider_type', 'base_url', 'provider_preset', 'api_key', 'has_api_key', 'default_model', 'backup_model',
            'temperature', 'max_tokens', 'timeout_seconds', 'is_enabled', 'runtime_ready', 'setup_hint',
            'price_currency', 'input_token_price_per_1m', 'output_token_price_per_1m',
            'last_test_status', 'last_test_message',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['runtime_ready', 'setup_hint', 'last_test_status', 'last_test_message', 'created_at', 'updated_at', 'has_api_key']

    def create(self, validated_data):
        api_key = validated_data.pop('api_key', '')
        instance = super().create(validated_data)
        if api_key:
            instance.set_api_key(api_key)
            instance.save(update_fields=['api_key_encrypted'])
        return instance

    def update(self, instance, validated_data):
        api_key = validated_data.pop('api_key', None)
        instance = super().update(instance, validated_data)
        if api_key is not None:
            instance.set_api_key(api_key)
            instance.save(update_fields=['api_key_encrypted'])
        return instance

    def get_runtime_ready(self, obj):
        return bool(obj.is_enabled and not get_model_provider_setup_hint(obj))

    def get_setup_hint(self, obj):
        return get_model_provider_setup_hint(obj)


class AIOpsModelProviderLiteSerializer(serializers.ModelSerializer):
    runtime_ready = serializers.SerializerMethodField()
    setup_hint = serializers.SerializerMethodField()

    class Meta:
        model = AIOpsModelProvider
        fields = ['id', 'name', 'provider_type', 'default_model', 'is_enabled', 'runtime_ready', 'setup_hint']

    def get_runtime_ready(self, obj):
        return bool(obj.is_enabled and not get_model_provider_setup_hint(obj))

    def get_setup_hint(self, obj):
        return get_model_provider_setup_hint(obj)


class AIOpsAgentConfigSerializer(serializers.ModelSerializer):
    default_provider_id = serializers.PrimaryKeyRelatedField(
        queryset=AIOpsModelProvider.objects.all(),
        source='default_provider',
        write_only=True,
        allow_null=True,
        required=False,
    )
    default_provider = AIOpsModelProviderLiteSerializer(read_only=True)

    class Meta:
        model = AIOpsAgentConfig
        fields = [
            'id', 'name', 'default_provider', 'default_provider_id', 'system_prompt', 'welcome_message',
            'suggested_questions', 'is_enabled', 'allow_action_execution', 'require_confirmation', 'show_evidence',
            'allow_analysis', 'enabled_mcp_server_ids', 'enabled_skill_ids', 'max_history_messages',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']


class AIOpsMCPServerSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIOpsMCPServer
        fields = '__all__'
        read_only_fields = ['is_builtin']

    def validate(self, attrs):
        server_type = attrs.get('server_type') or getattr(self.instance, 'server_type', '')
        if server_type != AIOpsMCPServer.SERVER_STDIO:
            return attrs
        endpoint = attrs.get('endpoint_or_command')
        if endpoint is None and self.instance:
            endpoint = self.instance.endpoint_or_command
        try:
            _validate_mcp_stdio_command(endpoint or '')
        except ValueError as exc:
            raise serializers.ValidationError({'endpoint_or_command': str(exc)}) from exc
        auth_config = attrs.get('auth_config')
        if auth_config is None and self.instance:
            auth_config = self.instance.auth_config
        explicit_env = (auth_config or {}).get('env') or {}
        blocked_keys = {'PATH', 'PATHEXT', 'PYTHONPATH', 'LD_PRELOAD', 'DYLD_INSERT_LIBRARIES'}
        invalid_keys = [str(key) for key in explicit_env if str(key).upper() in blocked_keys]
        if invalid_keys:
            raise serializers.ValidationError({'auth_config': f'禁止设置受保护的环境变量：{", ".join(invalid_keys)}'})
        return attrs

    def update(self, instance, validated_data):
        if instance.is_builtin:
            validated_data.pop('name', None)
            validated_data.pop('server_type', None)
        return super().update(instance, validated_data)


class AIOpsSkillSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIOpsSkill
        fields = '__all__'
        read_only_fields = ['is_builtin']

    def validate(self, attrs):
        list_fields = [
            'allowed_role_codes',
            'applicable_actions',
            'examples',
            'builtin_tools',
            'recommended_tools',
        ]
        for field in list_fields:
            if field not in attrs:
                continue
            value = attrs.get(field)
            if value in (None, ''):
                attrs[field] = []
                continue
            if not isinstance(value, list):
                raise serializers.ValidationError({field: '必须为数组'})
            normalized = []
            for item in value:
                normalized_item = str(item or '').strip()
                if normalized_item and normalized_item not in normalized:
                    normalized.append(normalized_item)
            attrs[field] = normalized

        if 'output_contract' in attrs:
            value = attrs.get('output_contract')
            if value in (None, ''):
                attrs['output_contract'] = {}
            elif not isinstance(value, dict):
                raise serializers.ValidationError({'output_contract': '必须为对象'})

        if 'max_iterations' in attrs and attrs.get('max_iterations') is None:
            attrs['max_iterations'] = 0
        return attrs

    def update(self, instance, validated_data):
        if instance.is_builtin:
            validated_data.pop('slug', None)
            validated_data.pop('source_type', None)
        return super().update(instance, validated_data)


class AIOpsKnowledgeEnvironmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIOpsKnowledgeEnvironment
        fields = [
            'id', 'name', 'aliases', 'description', 'event_environments', 'grafana_folder_keys',
            'metric_datasource_ids', 'log_datasource_ids', 'tracing_datasource_ids', 'observability_link_ids', 'alert_environments',
            'k8s_cluster_ids', 'k8s_namespaces', 'docker_host_ids',
            'task_resource_environment_ids',
            'is_default', 'is_enabled', 'created_by', 'updated_by', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_by', 'updated_by', 'created_at', 'updated_at']

    def validate_name(self, value):
        value = (value or '').strip()
        if not value:
            raise serializers.ValidationError('请填写知识图谱环境名')
        return value

    def validate(self, attrs):
        list_fields = [
            'aliases',
            'event_environments',
            'grafana_folder_keys',
            'metric_datasource_ids',
            'log_datasource_ids',
            'tracing_datasource_ids',
            'observability_link_ids',
            'alert_environments',
            'k8s_cluster_ids',
            'docker_host_ids',
            'task_resource_environment_ids',
        ]
        for field in list_fields:
            if field not in attrs:
                continue
            value = attrs.get(field)
            if value in (None, ''):
                attrs[field] = []
                continue
            if not isinstance(value, list):
                raise serializers.ValidationError({field: '必须为数组'})
            normalized = []
            for item in value:
                if field.endswith('_ids'):
                    try:
                        normalized_item = int(item)
                    except (TypeError, ValueError):
                        continue
                else:
                    normalized_item = str(item or '').strip()
                if normalized_item and normalized_item not in normalized:
                    normalized.append(normalized_item)
            attrs[field] = normalized

        if 'k8s_namespaces' in attrs:
            value = attrs.get('k8s_namespaces')
            if value in (None, ''):
                attrs['k8s_namespaces'] = {}
            elif not isinstance(value, dict):
                raise serializers.ValidationError({'k8s_namespaces': '必须为对象'})
            else:
                normalized = {}
                for cluster_id, namespaces in value.items():
                    try:
                        normalized_cluster_id = str(int(cluster_id))
                    except (TypeError, ValueError):
                        continue
                    if not isinstance(namespaces, list):
                        continue
                    normalized_namespaces = []
                    for namespace in namespaces:
                        namespace = str(namespace or '').strip()
                        if namespace and namespace not in normalized_namespaces:
                            normalized_namespaces.append(namespace)
                    if normalized_namespaces:
                        normalized[normalized_cluster_id] = normalized_namespaces
                attrs['k8s_namespaces'] = normalized

        instance = self.instance
        association_fields = [field for field in list_fields if field != 'aliases']
        has_association = any(
            attrs.get(field, getattr(instance, field, [])) for field in association_fields
        )
        if not has_association:
            raise serializers.ValidationError('??????????????????????????K8s ???Docker ???????????')
        is_default = attrs.get('is_default', getattr(instance, 'is_default', False))
        is_enabled = attrs.get('is_enabled', getattr(instance, 'is_enabled', True))
        if is_default and not is_enabled:
            raise serializers.ValidationError({'is_default': '停用图谱不能设为默认'})
        return attrs


class AIOpsPendingActionSerializer(serializers.ModelSerializer):
    risk_level_display = serializers.CharField(source='get_risk_level_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = AIOpsPendingAction
        fields = [
            'id', 'action_type', 'title', 'risk_level', 'risk_level_display', 'status', 'status_display',
            'action_payload', 'result_payload', 'confirmed_by', 'confirmed_at', 'created_at', 'updated_at',
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        payload = data.get('action_payload')
        if instance.action_type != AIOpsPendingAction.ACTION_EXECUTE_HOST_TASK or not isinstance(payload, dict):
            return data
        normalized_payload = _ensure_task_draft_title(payload)
        if normalized_payload.get('name') and (not data.get('title') or _is_generic_task_title(data.get('title'))):
            data['title'] = normalized_payload['name']
        data['action_payload'] = normalized_payload
        return data


class AIOpsChatMessageSerializer(serializers.ModelSerializer):
    pending_action = serializers.SerializerMethodField()
    blocks = serializers.SerializerMethodField()

    class Meta:
        model = AIOpsChatMessage
        fields = ['id', 'role', 'message_type', 'content', 'citations', 'tool_calls', 'metadata', 'blocks', 'pending_action', 'created_at']

    def get_pending_action(self, obj):
        action = obj.pending_actions.order_by('-id').first()
        return AIOpsPendingActionSerializer(action).data if action else None

    def get_blocks(self, obj):
        metadata = obj.metadata or {}
        blocks = metadata.get('response_blocks') or metadata.get('blocks') or []
        return blocks if isinstance(blocks, list) else []


class AIOpsChatSessionSerializer(serializers.ModelSerializer):
    latest_message = serializers.SerializerMethodField()

    class Meta:
        model = AIOpsChatSession
        fields = ['id', 'title', 'status', 'context', 'last_message_at', 'created_at', 'updated_at', 'latest_message']

    def get_latest_message(self, obj):
        message = obj.messages.order_by('-created_at', '-id').first()
        if not message:
            return None
        return {
            'role': message.role,
            'content': message.content[:120],
            'created_at': message.created_at,
        }


class _AIOpsAuditTraceMixin:
    def _empty_skill_trace(self):
        return {'enabled_count': 0, 'matched_count': 0, 'called_count': 0, 'tool_matched_count': 0, 'items': []}

    def _normalize_text_list(self, values):
        normalized = []
        for item in values or []:
            value = str(item or '').strip()
            if value and value not in normalized:
                normalized.append(value)
        return normalized

    def _trace_skill_cache(self):
        if hasattr(self, '_aiops_trace_skill_cache'):
            return getattr(self, '_aiops_trace_skill_cache')
        skills = list(AIOpsSkill.objects.filter(is_enabled=True).order_by('is_builtin', 'name', 'id'))
        setattr(self, '_aiops_trace_skill_cache', skills)
        return skills

    def _skill_trace_item(self, skill, *, status='matched', hit_reason='legacy_inferred', action_code='', used_tools=None):
        declared_tools = self._normalize_text_list([
            *(getattr(skill, 'builtin_tools', None) or []),
            *(getattr(skill, 'recommended_tools', None) or []),
        ])
        return {
            'id': getattr(skill, 'id', None),
            'name': getattr(skill, 'name', '') or getattr(skill, 'slug', ''),
            'slug': getattr(skill, 'slug', ''),
            'category': getattr(skill, 'category', '') or '',
            'risk_level': getattr(skill, 'risk_level', '') or '',
            'status': status,
            'hit_reason': hit_reason,
            'action_code': action_code,
            'applicable_actions': list(getattr(skill, 'applicable_actions', None) or []),
            'declared_tools': declared_tools,
            'used_tools': self._normalize_text_list(used_tools or []),
        }

    def _normalize_skill_trace(self, trace):
        if not isinstance(trace, dict):
            return None
        items = trace.get('items') if isinstance(trace.get('items'), list) else []
        enabled_count = trace.get('enabled_count') or len(items)
        matched_count = trace.get('matched_count') or sum(
            1
            for item in items
            if isinstance(item, dict) and (item.get('status') != 'available' or item.get('used_tools'))
        )
        if not enabled_count and not matched_count and not items:
            return None
        return {
            'enabled_count': enabled_count,
            'matched_count': matched_count,
            'called_count': trace.get('called_count') or 0,
            'tool_matched_count': trace.get('tool_matched_count') or sum(
                1 for item in items if isinstance(item, dict) and item.get('used_tools')
            ),
            'items': items,
        }

    def _infer_legacy_skill_trace(self, message, metadata):
        if not message or not isinstance(metadata, dict):
            return self._empty_skill_trace()
        selected_action = metadata.get('selected_action')
        action_trace = metadata.get('action_trace')
        action_source = selected_action if isinstance(selected_action, dict) and selected_action else action_trace
        action_source = action_source if isinstance(action_source, dict) else {}
        action_code = action_source.get('code') or ''
        action_skill_slugs = set(self._normalize_text_list(action_source.get('skills') or []))
        tool_calls = self._normalize_text_list(message.tool_calls or [])
        has_action_context = bool(action_code or action_skill_slugs)
        items = []
        seen_slugs = set()

        for skill in self._trace_skill_cache():
            skill_slug = getattr(skill, 'slug', '')
            declared_tools = self._normalize_text_list([
                *(getattr(skill, 'builtin_tools', None) or []),
                *(getattr(skill, 'recommended_tools', None) or []),
            ])
            used_tools = [name for name in tool_calls if name in declared_tools]
            if action_skill_slugs:
                action_hit = skill_slug in action_skill_slugs
            else:
                action_hit = bool(action_code and action_code in set(getattr(skill, 'applicable_actions', None) or []))
            if has_action_context and not action_hit:
                continue
            if not has_action_context and not used_tools:
                continue
            seen_slugs.add(skill_slug)
            items.append(self._skill_trace_item(
                skill,
                status='matched',
                hit_reason='legacy_action_router' if action_hit else 'legacy_tool_dependency',
                action_code=action_code if action_hit else '',
                used_tools=used_tools,
            ))

        for slug in sorted(action_skill_slugs - seen_slugs):
            items.append({
                'id': None,
                'name': slug,
                'slug': slug,
                'category': '',
                'risk_level': '',
                'status': 'matched',
                'hit_reason': 'legacy_action_router',
                'action_code': action_code,
                'applicable_actions': [action_code] if action_code else [],
                'declared_tools': [],
                'used_tools': [],
            })

        if not items:
            return self._empty_skill_trace()
        return {
            'enabled_count': len(items),
            'matched_count': len(items),
            'called_count': 0,
            'tool_matched_count': sum(1 for item in items if item.get('used_tools')),
            'items': items[:16],
            'inferred': True,
        }

    def _skill_trace_for_message(self, message):
        metadata = message.metadata if message else {}
        trace = metadata.get('skill_trace') if isinstance(metadata, dict) else None
        normalized = self._normalize_skill_trace(trace)
        if normalized:
            return normalized
        return self._infer_legacy_skill_trace(message, metadata)

    def _action_trace_for_message(self, message):
        metadata = message.metadata if message else {}
        if not isinstance(metadata, dict):
            return {}
        trace = metadata.get('action_trace')
        if isinstance(trace, dict) and trace:
            normalized_trace = dict(trace)
            if not normalized_trace.get('code') and (
                'generate_host_task' in (message.tool_calls or [])
                or normalized_trace.get('draft_generated')
                or isinstance(normalized_trace.get('pending_action'), dict)
            ):
                normalized_trace.update({
                    'hit': True,
                    'code': 'host_task.generate',
                    'display_name': '任务生成',
                    'risk_level': normalized_trace.get('risk_level') or 'draft',
                    'risk_level_display': normalized_trace.get('risk_level_display') or '草稿',
                    'status': normalized_trace.get('status') or 'matched',
                    'skills': normalized_trace.get('skills') or ['sx-task-template-selection', 'answer-formatter'],
                    'allowed_tools': normalized_trace.get('allowed_tools') or ['query_task_resources', 'generate_host_task', 'query_knowledge_graph'],
                    'inferred': True,
                })
            return normalized_trace
        selected_action = metadata.get('selected_action')
        if isinstance(selected_action, dict) and selected_action:
            return {
                'hit': True,
                'code': selected_action.get('code') or '',
                'display_name': selected_action.get('display_name') or selected_action.get('code') or '',
                'risk_level': selected_action.get('risk_level') or '',
                'risk_level_display': selected_action.get('risk_level_display') or '',
                'status': 'matched',
                'skills': selected_action.get('skills') or [],
                'allowed_tools': selected_action.get('allowed_tools') or [],
            }
        if message and 'generate_host_task' in (message.tool_calls or []):
            return {
                'hit': True,
                'code': 'host_task.generate',
                'display_name': '任务生成',
                'risk_level': 'draft',
                'risk_level_display': '草稿',
                'status': 'matched',
                'skills': ['sx-task-template-selection', 'answer-formatter'],
                'allowed_tools': ['query_task_resources', 'generate_host_task', 'query_knowledge_graph'],
                'inferred': True,
            }
        return {}


class AIOpsAuditTraceReader(_AIOpsAuditTraceMixin):
    pass


class AIOpsAuditSessionSerializer(_AIOpsAuditTraceMixin, serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    message_count = serializers.IntegerField(read_only=True)
    tool_invocation_count = serializers.IntegerField(read_only=True)
    pending_action_count = serializers.IntegerField(read_only=True)
    latest_message = serializers.SerializerMethodField()
    skill_trace = serializers.SerializerMethodField()
    action_trace = serializers.SerializerMethodField()

    class Meta:
        model = AIOpsChatSession
        fields = [
            'id', 'title', 'status', 'username', 'message_count', 'tool_invocation_count',
            'pending_action_count', 'latest_message', 'skill_trace', 'action_trace',
            'last_message_at', 'created_at', 'updated_at',
        ]

    def _latest_audit_message(self, obj):
        if hasattr(obj, '_latest_audit_message'):
            return getattr(obj, '_latest_audit_message')
        message = obj.messages.filter(role=AIOpsChatMessage.ROLE_ASSISTANT).order_by('-created_at', '-id').first()
        setattr(obj, '_latest_audit_message', message)
        return message

    def get_latest_message(self, obj):
        message = self._latest_audit_message(obj)
        if not message:
            return None
        return {
            'id': message.id,
            'role': message.role,
            'message_type': message.message_type,
            'content': message.content[:160],
            'tool_calls': message.tool_calls or [],
            'created_at': message.created_at,
        }

    def get_skill_trace(self, obj):
        return self._skill_trace_for_message(self._latest_audit_message(obj))

    def get_action_trace(self, obj):
        return self._action_trace_for_message(self._latest_audit_message(obj))


class AIOpsChatInputSerializer(serializers.Serializer):
    content = serializers.CharField(max_length=4000)
    analysis_only = serializers.BooleanField(required=False, default=False)
    page_context = serializers.JSONField(required=False, default=dict)


class AIOpsCreateSessionSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=128, required=False, allow_blank=True, default='')
    page_context = serializers.JSONField(required=False, default=dict)


class AIOpsToolInvocationSerializer(_AIOpsAuditTraceMixin, serializers.ModelSerializer):
    session_title = serializers.CharField(source='session.title', read_only=True)
    username = serializers.CharField(source='session.user.username', read_only=True)
    skill_trace = serializers.SerializerMethodField()
    action_trace = serializers.SerializerMethodField()

    class Meta:
        model = AIOpsToolInvocation
        fields = [
            'id', 'session', 'session_title', 'username', 'message', 'tool_name', 'status', 'latency_ms',
            'request_payload', 'response_summary', 'skill_trace', 'action_trace', 'created_at',
        ]

    def _trace_message(self, obj):
        if hasattr(obj, '_audit_trace_message'):
            return getattr(obj, '_audit_trace_message')
        message = None
        if obj.message_id:
            message = obj.session.messages.filter(
                role=AIOpsChatMessage.ROLE_ASSISTANT,
                id__gt=obj.message_id,
            ).order_by('id').first()
        if not message and obj.created_at:
            message = obj.session.messages.filter(
                role=AIOpsChatMessage.ROLE_ASSISTANT,
                created_at__gte=obj.created_at,
            ).order_by('created_at', 'id').first()
        if not message:
            message = obj.session.messages.filter(role=AIOpsChatMessage.ROLE_ASSISTANT).order_by('-created_at', '-id').first()
        setattr(obj, '_audit_trace_message', message)
        return message

    def get_skill_trace(self, obj):
        return self._skill_trace_for_message(self._trace_message(obj))

    def get_action_trace(self, obj):
        return self._action_trace_for_message(self._trace_message(obj))


class AIOpsModelInvocationSerializer(serializers.ModelSerializer):
    provider_name = serializers.CharField(source='provider.name', read_only=True)
    session_title = serializers.CharField(source='session.title', read_only=True)
    purpose_display = serializers.CharField(source='get_purpose_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = AIOpsModelInvocation
        fields = [
            'id', 'provider', 'provider_name', 'session', 'session_title', 'message', 'username',
            'purpose', 'purpose_display', 'requested_model', 'resolved_model', 'status', 'status_display',
            'latency_ms', 'prompt_tokens', 'completion_tokens', 'total_tokens', 'estimated_cost_usd', 'estimated_cost_currency',
            'request_summary', 'response_summary', 'created_at',
        ]


class AIOpsExternalTaskSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = AIOpsExternalTask
        fields = [
            'id', 'public_id', 'source_agent', 'title', 'action_code', 'agent_mode', 'status', 'status_display',
            'input_payload', 'plan_steps', 'orchestration_state', 'agent_results', 'react_trace',
            'result_payload', 'error_message', 'created_by', 'created_by_username',
            'created_at', 'updated_at', 'completed_at', 'canceled_at',
        ]
        read_only_fields = [
            'id', 'public_id', 'agent_mode', 'status', 'status_display', 'plan_steps',
            'orchestration_state', 'agent_results', 'react_trace', 'result_payload',
            'error_message', 'created_by', 'created_by_username', 'created_at', 'updated_at',
            'completed_at', 'canceled_at',
        ]

    def validate(self, attrs):
        input_payload = attrs.get('input_payload')
        if input_payload in (None, ''):
            attrs['input_payload'] = {}
        elif not isinstance(input_payload, dict):
            raise serializers.ValidationError({'input_payload': '必须为对象'})
        return attrs


class AIOpsRunbookSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    version_count = serializers.SerializerMethodField()

    class Meta:
        model = AIOpsRunbook
        fields = [
            'id', 'title', 'slug', 'environment', 'service', 'status', 'status_display', 'version',
            'version_count', 'content', 'evidence', 'tags', 'source_refs', 'source_task', 'source_session',
            'created_by', 'updated_by', 'published_at', 'archived_at', 'created_at', 'updated_at',
        ]
        read_only_fields = ['version', 'version_count', 'created_by', 'updated_by', 'published_at', 'archived_at', 'created_at', 'updated_at']

    def validate(self, attrs):
        for field in ['evidence', 'tags', 'source_refs']:
            if field not in attrs:
                continue
            value = attrs.get(field)
            if value in (None, ''):
                attrs[field] = []
            elif not isinstance(value, list):
                raise serializers.ValidationError({field: '必须为数组'})
        return attrs

    def get_version_count(self, obj):
        annotated = getattr(obj, 'version_count', None)
        if annotated is not None:
            return annotated
        return obj.versions.count() if getattr(obj, 'id', None) else 0


class AIOpsRunbookVersionSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = AIOpsRunbookVersion
        fields = [
            'id', 'runbook', 'version', 'status', 'status_display', 'title', 'content',
            'evidence', 'tags', 'source_refs', 'change_note', 'created_by', 'created_at',
        ]
        read_only_fields = fields


class AIOpsReviewKnowledgeSerializer(serializers.ModelSerializer):
    source_type_display = serializers.CharField(source='get_source_type_display', read_only=True)

    class Meta:
        model = AIOpsReviewKnowledge
        fields = [
            'id', 'slug', 'title', 'summary', 'environment', 'service', 'source_type', 'source_type_display',
            'evidence', 'tags', 'source_refs', 'source_session', 'source_task', 'source_runbook',
            'created_by', 'updated_by', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_by', 'updated_by', 'created_at', 'updated_at']

    def validate(self, attrs):
        for field in ['evidence', 'tags', 'source_refs']:
            if field not in attrs:
                continue
            value = attrs.get(field)
            if value in (None, ''):
                attrs[field] = []
            elif not isinstance(value, list):
                raise serializers.ValidationError({field: '必须为数组'})
        return attrs
