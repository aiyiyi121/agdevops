from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import EventEnvironment, EventRecord, EventSource
from .services import record_event
from .views import _ensure_default_event_sources, _ensure_hourly_sample_demo_events


class EventSourceTests(TestCase):
    def test_event_environment_alias_normalizes_internal_events(self):
        EventEnvironment.objects.create(code='prod', name='生产环境', aliases=['production', '生产'])

        event = record_event(
            module='ops',
            category='execution',
            action='run_task',
            title='内部任务事件',
            resource_type='host_task',
            environment='production',
        )

        self.assertEqual(event.environment, 'prod')
        self.assertEqual(event.metadata['environment_raw'], 'production')
        self.assertTrue(event.metadata['environment_matched'])

    def test_internal_event_keeps_unmatched_environment(self):
        EventEnvironment.objects.create(code='prod', name='生产环境')

        event = record_event(
            module='ops',
            category='execution',
            action='run_task',
            title='内部任务事件',
            resource_type='host_task',
            environment='sandbox',
        )

        self.assertEqual(event.environment, 'sandbox')
        self.assertTrue(event.metadata['environment_unmatched'])

    def test_filter_options_use_configured_event_environments(self):
        user = get_user_model().objects.create_superuser(username='env-admin', password='pass')
        EventEnvironment.objects.all().delete()
        EventEnvironment.objects.create(code='prod', name='生产环境', aliases=['production'], sort_order=10)
        EventRecord.objects.create(
            module='ops',
            category='execution',
            action='run_task',
            result=EventRecord.RESULT_SUCCESS,
            severity=EventRecord.SEVERITY_INFO,
            title='内部任务事件',
            resource_type='host_task',
            environment='sandbox',
        )

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get('/api/events/filter_options/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['environments'], ['prod'])
        self.assertEqual(response.data['environment_options'][0]['name'], '生产环境')
        self.assertIn('sandbox', response.data['event_environments'])

    def test_external_ingest_rejects_unknown_configured_environment(self):
        EventEnvironment.objects.create(code='prod', name='生产环境')
        _ensure_default_event_sources()
        source = EventSource.objects.get(code='custom')
        token = source.issue_token()
        source.enabled = True
        source.status = EventSource.STATUS_HEALTHY
        source.save(update_fields=['token_hash', 'token_preview', 'enabled', 'status', 'updated_at'])

        response = APIClient().post(
            '/api/event-sources/custom/ingest/',
            {
                'event_id': 'bad-env-001',
                'event_category': 'ops_transaction',
                'title': '未知环境事件',
                'environment': 'sandbox',
            },
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {token}',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('environment', response.data)

    def test_external_ingest_accepts_environment_alias(self):
        EventEnvironment.objects.create(code='prod', name='生产环境', aliases=['production'])
        _ensure_default_event_sources()
        source = EventSource.objects.get(code='custom')
        token = source.issue_token()
        source.enabled = True
        source.status = EventSource.STATUS_HEALTHY
        source.save(update_fields=['token_hash', 'token_preview', 'enabled', 'status', 'updated_at'])

        response = APIClient().post(
            '/api/event-sources/custom/ingest/',
            {
                'event_id': 'good-env-001',
                'event_category': 'ops_transaction',
                'title': '别名环境事件',
                'environment': 'production',
            },
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {token}',
        )

        self.assertEqual(response.status_code, 201)
        event = EventRecord.objects.get(metadata__external_event_id='good-env-001')
        self.assertEqual(event.environment, 'prod')

    def test_default_event_sources_include_builtin_and_external_sources(self):
        _ensure_default_event_sources()

        self.assertEqual(EventSource.objects.exclude(code='builtin-k8s').count(), 7)
        self.assertTrue(EventSource.objects.filter(code='builtin-workorder', source_kind=EventSource.KIND_BUILTIN).exists())
        self.assertTrue(EventSource.objects.filter(code='builtin-task-center', source_kind=EventSource.KIND_BUILTIN).exists())
        self.assertFalse(EventSource.objects.filter(code='builtin-k8s', enabled=True).exists())
        self.assertTrue(EventSource.objects.filter(code='jira', source_kind=EventSource.KIND_EXTERNAL).exists())
        self.assertTrue(EventSource.objects.filter(code='jenkins', source_kind=EventSource.KIND_EXTERNAL).exists())
        self.assertTrue(EventSource.objects.filter(code='argocd', source_kind=EventSource.KIND_EXTERNAL).exists())
        self.assertTrue(EventSource.objects.filter(code='gitlab', source_kind=EventSource.KIND_EXTERNAL).exists())
        self.assertTrue(EventSource.objects.filter(code='custom', source_kind=EventSource.KIND_EXTERNAL).exists())

    def test_hourly_sample_demo_events_are_generated_idempotently(self):
        _ensure_hourly_sample_demo_events(hours=4)
        first_count = EventRecord.objects.filter(metadata__hourly_demo_environment='电商测试环境-k3s').count()
        _ensure_hourly_sample_demo_events(hours=4)
        second_count = EventRecord.objects.filter(metadata__hourly_demo_environment='电商测试环境-k3s').count()

        self.assertEqual(first_count, second_count)
        self.assertGreaterEqual(first_count, 8)
        allowed_categories = {'db_change', 'config_change', 'ops_transaction', 'task_center'}
        by_hour = {}
        for event in EventRecord.objects.filter(metadata__hourly_demo_environment='电商测试环境-k3s'):
            self.assertEqual(event.environment, 'ecommerce-test')
            self.assertEqual(event.business_line, '电商')
            self.assertEqual(event.application, '')
            self.assertIn(event.metadata['event_category'], allowed_categories)
            if event.metadata['event_category'] == 'db_change':
                self.assertIn('table', event.metadata)
            by_hour.setdefault(event.metadata['hourly_demo_hour'], 0)
            by_hour[event.metadata['hourly_demo_hour']] += 1
        self.assertTrue(all(count in {2, 3} for count in by_hour.values()))

    def test_ingest_spec_uses_type_placeholder(self):
        user = get_user_model().objects.create_superuser(username='spec-admin', password='pass')

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get('/api/event-sources/ingest_spec/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['endpoint_template'], '/api/event-sources/{type}/ingest/')

    def test_external_ingest_records_event_with_source_metadata(self):
        _ensure_default_event_sources()
        source = EventSource.objects.get(code='custom')
        token = source.issue_token()
        source.enabled = True
        source.status = EventSource.STATUS_HEALTHY
        source.save(update_fields=['token_hash', 'token_preview', 'enabled', 'status', 'updated_at'])

        response = APIClient().post(
            '/api/event-sources/custom/ingest/',
            {
                'event_id': 'unit-001',
                'event_category': 'application_release',
                'title': '自研系统变更事件',
                'summary': '自研系统推送变更事件',
                'result': EventRecord.RESULT_SUCCESS,
                'severity': EventRecord.SEVERITY_INFO,
                'system_name': '交易',
                'environment': 'ecommerce-test',
                'application': 'payment-api',
            },
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {token}',
        )

        self.assertEqual(response.status_code, 201)
        event = EventRecord.objects.get(metadata__event_source_code='custom', metadata__external_event_id='unit-001')
        self.assertEqual(event.title, '自研系统变更事件')
        self.assertEqual(event.source_type, EventRecord.SOURCE_EXTERNAL)
        self.assertEqual(event.business_line, '交易')
        self.assertEqual(event.application, 'payment-api')

    def test_external_ingest_deduplicates_by_event_id_per_source(self):
        _ensure_default_event_sources()
        source = EventSource.objects.get(code='custom')
        token = source.issue_token()
        source.enabled = True
        source.status = EventSource.STATUS_HEALTHY
        source.save(update_fields=['token_hash', 'token_preview', 'enabled', 'status', 'updated_at'])
        payload = {
            'event_id': 'repeat-001',
            'event_category': 'ops_transaction',
            'title': '重复外部事件',
            'result': EventRecord.RESULT_FAILED,
            'severity': EventRecord.SEVERITY_WARNING,
            'environment': 'ecommerce-test',
        }

        client = APIClient()
        first_response = client.post(
            '/api/event-sources/custom/ingest/',
            payload,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {token}',
        )
        second_response = client.post(
            '/api/event-sources/custom/ingest/',
            payload,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {token}',
        )

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 200)
        self.assertTrue(second_response.data['deduplicated'])
        self.assertEqual(EventRecord.objects.filter(metadata__event_source_code='custom', metadata__external_event_id='repeat-001').count(), 1)

    def test_external_ingest_accepts_task_center_category(self):
        _ensure_default_event_sources()
        source = EventSource.objects.get(code='custom')
        token = source.issue_token()
        source.enabled = True
        source.status = EventSource.STATUS_HEALTHY
        source.save(update_fields=['token_hash', 'token_preview', 'enabled', 'status', 'updated_at'])

        response = APIClient().post(
            '/api/event-sources/custom/ingest/',
            {
                'event_id': 'external-task-001',
                'event_category': 'task_center',
                'title': '外部自动化任务执行失败',
                'event_type': 'automation_task',
                'action': 'run_task',
                'result': EventRecord.RESULT_FAILED,
                'severity': EventRecord.SEVERITY_DANGER,
                'resource_type': 'automation_task',
                'resource_id': 'task-001',
                'resource_name': '批量巡检任务',
                'environment': 'ecommerce-test',
            },
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {token}',
        )

        self.assertEqual(response.status_code, 201)
        event = EventRecord.objects.get(metadata__event_source_code='custom', metadata__external_event_id='external-task-001')
        self.assertEqual(event.metadata['event_category'], 'task_center')
        self.assertEqual(event.metadata['event_category_label'], '任务调度')

    def test_external_ingest_requires_event_category_without_source_default(self):
        _ensure_default_event_sources()
        source = EventSource.objects.get(code='custom')
        token = source.issue_token()
        source.enabled = True
        source.status = EventSource.STATUS_HEALTHY
        source.save(update_fields=['token_hash', 'token_preview', 'enabled', 'status', 'updated_at'])

        response = APIClient().post(
            '/api/event-sources/custom/ingest/',
            {'event_id': 'missing-category', 'title': '缺少分类', 'environment': 'ecommerce-test'},
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {token}',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('event_category', response.data)

    def test_pipeline_events_are_classified_as_application_release(self):
        _ensure_default_event_sources()
        source = EventSource.objects.get(code='gitlab')
        token = source.issue_token()
        source.enabled = True
        source.status = EventSource.STATUS_HEALTHY
        source.save(update_fields=['token_hash', 'token_preview', 'enabled', 'status', 'updated_at'])

        response = APIClient().post(
            '/api/event-sources/gitlab/ingest/',
            {
                'checkout_sha': 'pipe-001',
                'object_kind': 'pipeline',
                'event_name': 'pipeline',
                'project': {'id': 1, 'name': 'payment-api', 'path_with_namespace': 'trade/payment-api'},
                'user_username': 'release-bot',
                'environment': 'ecommerce-test',
            },
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {token}',
        )

        self.assertEqual(response.status_code, 201)
        event = EventRecord.objects.get(metadata__event_source_code='gitlab', metadata__external_event_id='pipe-001')
        self.assertEqual(event.action, 'pipeline')
        self.assertEqual(event.metadata['event_category'], 'application_release')
        self.assertEqual(event.metadata['event_category_source'], 'traits')

    def test_jenkins_events_preserve_environment_and_service(self):
        _ensure_default_event_sources()
        source = EventSource.objects.get(code='jenkins')
        token = source.issue_token()
        source.enabled = True
        source.status = EventSource.STATUS_HEALTHY
        source.save(update_fields=['token_hash', 'token_preview', 'enabled', 'status', 'updated_at'])

        response = APIClient().post(
            '/api/event-sources/jenkins/ingest/',
            {
                'job_name': 'gateway-release',
                'build_number': '42',
                'phase': 'deploy',
                'status': 'success',
                'message': 'gateway release succeeded',
                'user': 'jenkins',
                'service': 'gateway',
                'system_name': '交易',
                'environment': '电商测试环境-k3s',
            },
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {token}',
        )

        self.assertEqual(response.status_code, 201)
        event = EventRecord.objects.get(metadata__event_source_code='jenkins', metadata__external_event_id='gateway-release#42')
        self.assertEqual(event.environment, 'ecommerce-test')
        self.assertEqual(event.business_line, '交易')
        self.assertEqual(event.application, 'gateway')

    def test_deployment_approval_flow_is_classified_as_application_release(self):
        user = get_user_model().objects.create_superuser(username='flow-admin', password='pass')
        now = timezone.now()
        EventRecord.objects.create(
            occurred_at=now - timedelta(minutes=5),
            module='ops',
            category='resource_change',
            action='create',
            result=EventRecord.RESULT_SUCCESS,
            severity=EventRecord.SEVERITY_INFO,
            title='创建发布审批流',
            resource_type='deployment_approval_flow',
            resource_id='1',
            resource_name='生产发布审批',
        )

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get('/api/events/analysis_wall/', {'fault_at': now.isoformat(), 'lookback_minutes': 60, 'after_minutes': 10})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['events'][0]['event_category']['key'], 'application_release')
        self.assertEqual(response.data['category_sections'][0]['count'], 1)

    def test_analysis_wall_groups_events_by_source_and_returns_suspects(self):
        user = get_user_model().objects.create_superuser(username='analysis-admin', password='pass')
        now = timezone.now()
        EventRecord.objects.create(
            occurred_at=now - timedelta(minutes=20),
            module='ops',
            category='execution',
            action='deploy',
            result=EventRecord.RESULT_FAILED,
            severity=EventRecord.SEVERITY_DANGER,
            title='发布失败',
            summary='payment-api 发布失败',
            resource_type='deployment',
            resource_id='1',
            resource_name='payment-api',
            business_line='trade',
            environment='prod',
            application='payment-api',
            correlation_id='payment-api:deploy:1',
        )

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get('/api/events/analysis_wall/', {'fault_at': now.isoformat(), 'lookback_minutes': 60, 'after_minutes': 10})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['summary']['total'], 1)
        self.assertEqual(response.data['summary']['suspects'], 1)
        self.assertEqual(response.data['summary']['scope_count'], 1)
        self.assertEqual(response.data['affected_scopes'][0]['application'], 'payment-api')
        self.assertEqual(response.data['lanes'][0]['source']['code'], 'builtin-workorder')
        self.assertEqual(response.data['suspects'][0]['title'], '发布失败')
        self.assertEqual(response.data['events'][0]['event_category']['key'], 'application_release')
        self.assertEqual(response.data['category_sections'][0]['key'], 'application_release')
        self.assertEqual(response.data['category_sections'][0]['count'], 1)
        self.assertTrue(response.data['recommendations'])

    def test_external_event_source_can_be_deleted(self):
        _ensure_default_event_sources()
        source = EventSource.objects.create(
            code='internal-release',
            name='内部发布平台',
            source_kind=EventSource.KIND_EXTERNAL,
            source_type=EventSource.TYPE_CUSTOM,
            enabled=True,
            status=EventSource.STATUS_HEALTHY,
            auth_type=EventSource.AUTH_WEBHOOK,
        )
        user = get_user_model().objects.create_superuser(username='source-admin', password='pass')

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.delete(f'/api/event-sources/{source.code}/')

        self.assertEqual(response.status_code, 204)
        self.assertFalse(EventSource.objects.filter(code=source.code).exists())

    def test_builtin_event_source_cannot_be_deleted(self):
        _ensure_default_event_sources()
        user = get_user_model().objects.create_superuser(username='builtin-source-admin', password='pass')

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.delete('/api/event-sources/builtin-workorder/')

        self.assertEqual(response.status_code, 400)
        self.assertTrue(EventSource.objects.filter(code='builtin-workorder').exists())

    def test_default_external_event_source_can_be_deleted_and_is_not_recreated(self):
        _ensure_default_event_sources()
        user = get_user_model().objects.create_superuser(username='default-source-admin', password='pass')

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.delete('/api/event-sources/jenkins/')
        list_response = client.get('/api/event-sources/')

        self.assertEqual(response.status_code, 204)
        self.assertFalse(EventSource.objects.filter(code='jenkins').exists())
        self.assertNotIn('jenkins', [item['code'] for item in list_response.data['results']])

    def test_default_external_event_source_can_be_renamed(self):
        _ensure_default_event_sources()
        user = get_user_model().objects.create_superuser(username='rename-source-admin', password='pass')

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.patch(
            '/api/event-sources/jenkins/',
            {'code': 'jenkins-prod', 'name': '生产 Jenkins'},
            format='json',
        )
        list_response = client.get('/api/event-sources/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['code'], 'jenkins-prod')
        self.assertEqual(response.data['name'], '生产 Jenkins')
        self.assertFalse(EventSource.objects.filter(code='jenkins').exists())
        self.assertTrue(EventSource.objects.filter(code='jenkins-prod', name='生产 Jenkins').exists())
        self.assertNotIn('jenkins', [item['code'] for item in list_response.data['results']])

    def test_analysis_wall_excludes_internal_operations_outside_workorders_and_tasks(self):
        user = get_user_model().objects.create_superuser(username='analysis-filter-admin', password='pass')
        now = timezone.now()
        EventRecord.objects.create(
            occurred_at=now - timedelta(minutes=20),
            module='ops',
            category='execution',
            action='refresh_info',
            result=EventRecord.RESULT_FAILED,
            severity=EventRecord.SEVERITY_WARNING,
            title='刷新主机信息失败',
            resource_type='host',
            resource_id='1',
            resource_name='host-01',
        )
        EventRecord.objects.create(
            occurred_at=now - timedelta(minutes=10),
            module='ops',
            category='execution',
            action='create_task',
            result=EventRecord.RESULT_FAILED,
            severity=EventRecord.SEVERITY_DANGER,
            title='任务中心执行失败',
            resource_type='host_task',
            resource_id='2',
            resource_name='批量巡检',
        )

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get('/api/events/analysis_wall/', {'fault_at': now.isoformat(), 'lookback_minutes': 60, 'after_minutes': 10})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['summary']['total'], 1)
        self.assertEqual(response.data['events'][0]['title'], '任务中心执行失败')
        self.assertEqual(response.data['events'][0]['event_category']['key'], 'task_center')
        self.assertEqual(response.data['lanes'][0]['source']['code'], 'builtin-task-center')

    def test_operation_audit_excludes_external_ingest_events(self):
        user = get_user_model().objects.create_superuser(username='audit-admin', password='pass')
        now = timezone.now()
        EventRecord.objects.create(
            occurred_at=now,
            module='rbac',
            category='resource_change',
            action='update_user',
            result=EventRecord.RESULT_SUCCESS,
            severity=EventRecord.SEVERITY_INFO,
            title='更新用户',
            resource_type='user',
            resource_id='1',
            source_type=EventRecord.SOURCE_HTTP,
        )
        EventRecord.objects.create(
            occurred_at=now,
            module='eventwall',
            category='external_event',
            action='ingest',
            result=EventRecord.RESULT_SUCCESS,
            severity=EventRecord.SEVERITY_INFO,
            title='外部流水线事件',
            source_type=EventRecord.SOURCE_EXTERNAL,
        )

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get('/api/events/operation_audit/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['title'], '更新用户')

    def test_prune_operation_audit_deletes_records_before_cutoff_only(self):
        user = get_user_model().objects.create_superuser(username='audit-cleaner', password='pass')
        now = timezone.now()
        old_event = EventRecord.objects.create(
            occurred_at=now - timedelta(days=10),
            module='rbac',
            category='resource_change',
            action='update_user',
            result=EventRecord.RESULT_SUCCESS,
            severity=EventRecord.SEVERITY_INFO,
            title='旧操作',
            source_type=EventRecord.SOURCE_HTTP,
        )
        recent_event = EventRecord.objects.create(
            occurred_at=now - timedelta(hours=1),
            module='rbac',
            category='resource_change',
            action='update_user',
            result=EventRecord.RESULT_SUCCESS,
            severity=EventRecord.SEVERITY_INFO,
            title='新操作',
            source_type=EventRecord.SOURCE_HTTP,
        )
        external_event = EventRecord.objects.create(
            occurred_at=now - timedelta(days=10),
            module='eventwall',
            category='external_event',
            action='ingest',
            result=EventRecord.RESULT_SUCCESS,
            severity=EventRecord.SEVERITY_INFO,
            title='外部事件',
            source_type=EventRecord.SOURCE_EXTERNAL,
        )

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.post('/api/events/prune_operation_audit/', {'before_at': (now - timedelta(days=1)).isoformat()}, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['deleted'], 1)
        self.assertFalse(EventRecord.objects.filter(id=old_event.id).exists())
        self.assertTrue(EventRecord.objects.filter(id=recent_event.id).exists())
        self.assertTrue(EventRecord.objects.filter(id=external_event.id).exists())

    def test_event_api_exposes_system_name_and_filter_options(self):
        user = get_user_model().objects.create_superuser(username='system-name-admin', password='pass')
        EventRecord.objects.create(
            module='eventwall',
            category='external_event',
            action='deploy',
            result=EventRecord.RESULT_SUCCESS,
            severity=EventRecord.SEVERITY_INFO,
            title='system-name-check',
            summary='system-name-check',
            business_line='trade',
            environment='prod',
            application='payment-api',
        )

        client = APIClient()
        client.force_authenticate(user=user)

        list_response = client.get('/api/events/', {'system_name': 'trade'})
        self.assertEqual(list_response.status_code, 200)
        first = list_response.data['results'][0]
        self.assertEqual(first['system_name'], 'trade')

        filter_response = client.get('/api/events/filter_options/', {'system_name': 'trade'})
        self.assertEqual(filter_response.status_code, 200)
        self.assertIn('system_names', filter_response.data)
        self.assertIn('trade', filter_response.data['system_names'])
