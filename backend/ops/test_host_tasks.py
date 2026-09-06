from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from aiops.models import AIOpsChatMessage, AIOpsChatSession, AIOpsPendingAction
from eventwall.models import EventEnvironment, EventRecord
from ops.host_tasks import AnsibleControllerError, _validate_remote_command, build_host_target_snapshot, execute_k8s_task, normalize_host_execution_targets, record_task_center_event
from ops.models import Host, HostTask, HostTaskExecution, HostTaskTemplate, K8sCluster, TaskResource, TaskResourceGroup
from rbac.models import Role
from rbac.services import ensure_builtin_rbac


class HostTaskApiTests(TestCase):
    def setUp(self):
        ensure_builtin_rbac()
        self.client = APIClient()
        self.user = get_user_model().objects.create_user('task-admin', password='Admin@123456')
        role = Role.objects.get(code='ops-admin')
        role.users.add(self.user)
        self.client.force_authenticate(user=self.user)
        self.host = Host.objects.create(
            hostname='app-01',
            ip_address='10.10.10.10',
            business_line='payment',
            environment='prod',
            status='online',
            ssh_user='root',
            ssh_password='secret',
        )

    def test_remote_command_rejects_shell_chaining(self):
        task = HostTask(task_type=HostTask.TASK_RUN_COMMAND, payload={})
        with self.assertRaises(ValueError):
            _validate_remote_command(task, 'id; whoami')

    def test_task_resource_group_can_bind_event_environment(self):
        event_environment = EventEnvironment.objects.create(code='ecommerce-task-test', name='电商任务测试环境')

        response = self.client.post(
            '/api/task-resource-groups/',
            {
                'name': '任务测试环境',
                'code': 'task-test',
                'group_type': TaskResourceGroup.GROUP_ENVIRONMENT,
                'event_environment': event_environment.id,
                'sort_order': 10,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload['event_environment'], event_environment.id)
        self.assertEqual(payload['event_environment_code'], 'ecommerce-task-test')
        self.assertEqual(payload['event_environment_name'], '电商任务测试环境')

        tree_response = self.client.get('/api/task-resource-groups/tree/')
        self.assertEqual(tree_response.status_code, 200)
        tree_item = next(item for item in tree_response.json() if item['id'] == payload['id'])
        self.assertEqual(tree_item['event_environment'], event_environment.id)
        self.assertEqual(tree_item['event_environment_code'], 'ecommerce-task-test')

    def test_task_center_event_uses_bound_event_environment(self):
        event_environment = EventEnvironment.objects.create(code='ecommerce-task-prod', name='电商任务生产环境')
        task_environment = TaskResourceGroup.objects.create(
            name='任务生产环境',
            group_type=TaskResourceGroup.GROUP_ENVIRONMENT,
            event_environment=event_environment,
        )
        resource = TaskResource.objects.create(
            name='app-prod-01',
            resource_type=TaskResource.RESOURCE_HOST,
            environment=task_environment,
            status=TaskResource.STATUS_ACTIVE,
            ip_address='10.2.1.10',
        )
        targets = normalize_host_execution_targets([resource])
        task = HostTask.objects.create(
            name='restart-app',
            task_type=HostTask.TASK_RUN_COMMAND,
            status=HostTask.STATUS_SUCCESS,
            target_count=1,
            target_snapshot=build_host_target_snapshot(targets),
            created_by=self.user.username,
            correlation_id='task-center:test-bound-event-environment',
        )

        event = record_task_center_event(task, 'task_finished', '任务中心执行完成')

        self.assertIsNotNone(event)
        self.assertEqual(event.environment, 'ecommerce-task-prod')
        self.assertEqual(event.metadata['environment_name'], '电商任务生产环境')
        self.assertTrue(EventRecord.objects.filter(environment='ecommerce-task-prod').exists())

    def _mock_client(self, outputs):
        client = MagicMock()

        def exec_command(command, timeout=None):
            stdout = MagicMock()
            stderr = MagicMock()
            stdout.channel.recv_exit_status.return_value = outputs[command]['exit_status']
            stdout.read.return_value = outputs[command].get('stdout', '').encode('utf-8')
            stderr.read.return_value = outputs[command].get('stderr', '').encode('utf-8')
            return None, stdout, stderr

        client.exec_command.side_effect = exec_command
        return client

    def _finished_executions(self, payload):
        return [item for item in payload['executions'] if item['status'] != HostTaskExecution.STATUS_RUNNING]

    @patch('ops.host_tasks.open_ssh_client')
    def test_run_command_task_records_successful_execution(self, mock_open_ssh_client):
        mock_open_ssh_client.return_value = self._mock_client({
            'uptime': {'exit_status': 0, 'stdout': '10:00 up 12 days, load average: 0.10'},
        })

        response = self.client.post(
            '/api/host-tasks/',
            {
                'name': 'batch-load-check',
                'task_type': 'run_command',
                'host_ids': [self.host.id],
                'payload': {'command': 'uptime'},
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload['status'], 'success')
        self.assertEqual(payload['execution_mode'], HostTask.EXECUTION_MODE_SSH)
        self.assertEqual(payload['success_count'], 1)
        self.assertEqual(payload['executions'][0]['status'], 'success')
        self.assertIn('load average', payload['executions'][0]['output'])

    @patch('ops.host_tasks.allow_ansible_fallback_to_ssh', return_value=True)
    @patch('ops.host_tasks.is_ansible_available', return_value=True)
    @patch('ops.host_tasks.execute_ansible_command')
    @patch('ops.host_tasks.open_ssh_client')
    def test_ansible_mode_falls_back_to_ssh_when_controller_unavailable(self, mock_open_ssh_client, mock_execute_ansible_command, _mock_available, _mock_allow_fallback):
        mock_execute_ansible_command.side_effect = AnsibleControllerError('ansible controller unavailable')
        mock_open_ssh_client.return_value = self._mock_client({
            'uptime': {'exit_status': 0, 'stdout': 'fallback-ok'},
        })

        response = self.client.post(
            '/api/host-tasks/',
            {
                'name': 'ansible-fallback-demo',
                'task_type': 'run_command',
                'execution_mode': HostTask.EXECUTION_MODE_ANSIBLE,
                'host_ids': [self.host.id],
                'payload': {'command': 'uptime'},
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload['status'], 'success')
        self.assertEqual(payload['execution_mode'], HostTask.EXECUTION_MODE_ANSIBLE)
        self.assertEqual(payload['success_count'], 1)
        self.assertIn('Ansible', payload['summary'])
        self.assertIn('SSH', payload['summary'])
        self.assertEqual(len(payload['executions']), 1)
        self.assertEqual(payload['executions'][0]['status'], HostTaskExecution.STATUS_SUCCESS)
        self.assertEqual(payload['executions'][0]['output'], 'fallback-ok')
        self.assertEqual(HostTaskExecution.objects.filter(task_id=payload['id']).count(), 1)
        self.assertFalse(
            HostTaskExecution.objects.filter(task_id=payload['id'], status=HostTaskExecution.STATUS_RUNNING).exists()
        )

    @patch('ops.host_tasks.is_ansible_playbook_available', return_value=True)
    @patch('ops.host_tasks.execute_ansible_playbook')
    def test_run_playbook_task_executes_with_ansible_mode(self, mock_execute_ansible_playbook, _mock_available):
        mock_execute_ansible_playbook.return_value = ('PLAY [targets]\\nTASK [ping]\\nok: [app-01]', '')

        response = self.client.post(
            '/api/host-tasks/',
            {
                'name': 'playbook-smoke-check',
                'task_type': HostTask.TASK_RUN_PLAYBOOK,
                'execution_mode': HostTask.EXECUTION_MODE_SSH,
                'host_ids': [self.host.id],
                'payload': {
                    'playbook_name': 'smoke-check.yml',
                    'playbook_content': '- hosts: targets\\n  gather_facts: false\\n  tasks:\\n    - name: ping\\n      ping:',
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload['status'], 'success')
        self.assertEqual(payload['execution_mode'], HostTask.EXECUTION_MODE_ANSIBLE)
        self.assertEqual(payload['executions'][0]['command'], 'ansible-playbook smoke-check.yml')
        self.assertIn('PLAY [targets]', payload['executions'][0]['output'])

    @patch('ops.host_tasks.is_ansible_playbook_available', return_value=True)
    @patch('ops.host_tasks.execute_ansible_playbook')
    def test_run_playbook_formats_debug_summary_output(self, mock_execute_ansible_playbook, _mock_available):
        mock_execute_ansible_playbook.return_value = (
            'TASK [Summarize]\n'
            'ok: [app-01] => {\n'
            '    "msg": [\n'
            '        "Uptime: 10:00 up 6 days",\n'
            '        "CPU/MEM:\\nCPU(s): 4\\nMem: 14Gi",\n'
            '        "DF:\\nFilesystem Size Used Avail Use% Mounted on\\ntmpfs 15G 12K 15G 1% /var/lib/kubelet/pods/abc\\n/dev/vda3 79G 17G 59G 22% /"\n'
            '    ]\n'
            '}',
            '',
        )

        response = self.client.post(
            '/api/host-tasks/',
            {
                'name': 'playbook-summary-format',
                'task_type': HostTask.TASK_RUN_PLAYBOOK,
                'host_ids': [self.host.id],
                'payload': {
                    'playbook_name': 'summary.yml',
                    'playbook_content': '- hosts: targets\\n  gather_facts: false\\n  tasks: []',
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        output = response.json()['executions'][0]['output']
        self.assertIn('Uptime: 10:00 up 6 days', output)
        self.assertIn('/dev/vda3 79G 17G 59G 22% /', output)
        self.assertNotIn('/var/lib/kubelet/pods/abc', output)
        self.assertNotIn('"msg": [', output)

    @patch('ops.host_tasks.allow_ansible_fallback_to_ssh', return_value=True)
    @patch('ops.host_tasks.is_ansible_playbook_available', return_value=True)
    @patch('ops.host_tasks.execute_ansible_playbook')
    @patch('ops.host_tasks.open_ssh_client')
    def test_run_playbook_does_not_fallback_to_ssh(self, mock_open_ssh_client, mock_execute_ansible_playbook, _mock_available, _mock_allow_fallback):
        mock_execute_ansible_playbook.side_effect = AnsibleControllerError('playbook controller unavailable')

        response = self.client.post(
            '/api/host-tasks/',
            {
                'name': 'playbook-no-fallback',
                'task_type': HostTask.TASK_RUN_PLAYBOOK,
                'host_ids': [self.host.id],
                'payload': {
                    'playbook_name': 'deploy.yml',
                    'playbook_content': '- hosts: targets\\n  gather_facts: false\\n  tasks: []',
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload['status'], 'failed')
        self.assertEqual(payload['failed_count'], 1)
        self.assertEqual(payload['execution_mode'], HostTask.EXECUTION_MODE_ANSIBLE)
        self.assertNotIn('SSH', payload['summary'])
        mock_open_ssh_client.assert_not_called()

    @patch('ops.host_tasks.is_ansible_playbook_available', return_value=False)
    def test_run_playbook_reports_missing_controller_with_actionable_message(self, _mock_available):
        response = self.client.post(
            '/api/host-tasks/',
            {
                'name': 'playbook-missing-controller',
                'task_type': HostTask.TASK_RUN_PLAYBOOK,
                'host_ids': [self.host.id],
                'payload': {
                    'playbook_name': 'inspect.yml',
                    'playbook_content': '- hosts: targets\n  gather_facts: false\n  tasks: []',
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload['status'], 'failed')
        error_message = self._finished_executions(payload)[0]['error_message']
        self.assertIn('ansible-playbook', error_message)
        self.assertIn('HOST_TASK_ANSIBLE_PLAYBOOK_BINARY', error_message)

    @patch('ops.host_tasks.open_ssh_client')
    def test_task_resource_execution_exposes_target_name(self, mock_open_ssh_client):
        mock_open_ssh_client.return_value = self._mock_client({
            'uptime': {'exit_status': 0, 'stdout': 'resource-ok'},
        })
        env = TaskResourceGroup.objects.create(name='ecommerce-test', group_type=TaskResourceGroup.GROUP_ENVIRONMENT)
        resource = TaskResource.objects.create(
            name='tf-k3s-single-node',
            resource_type=TaskResource.RESOURCE_HOST,
            environment=env,
            status=TaskResource.STATUS_ACTIVE,
            ip_address='203.0.113.176',
            ssh_user='root',
            ssh_password='secret',
        )

        response = self.client.post(
            '/api/host-tasks/',
            {
                'name': 'resource-target-command',
                'task_type': HostTask.TASK_RUN_COMMAND,
                'execution_mode': HostTask.EXECUTION_MODE_SSH,
                'resource_ids': [resource.id],
                'payload': {'command': 'uptime'},
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        execution = response.json()['executions'][0]
        self.assertEqual(execution['host_name'], 'tf-k3s-single-node')
        self.assertEqual(execution['target_name'], 'tf-k3s-single-node')
        self.assertEqual(execution['target_id'], f'task_resource:{resource.id}')
        self.assertEqual(execution['target_kind'], 'task_resource_host')

    def test_task_resource_list_defaults_to_all_statuses_and_allows_reactivate(self):
        env = TaskResourceGroup.objects.create(name='resource-test-env', group_type=TaskResourceGroup.GROUP_ENVIRONMENT)
        active_resource = TaskResource.objects.create(
            name='active-resource-host',
            resource_type=TaskResource.RESOURCE_HOST,
            environment=env,
            status=TaskResource.STATUS_ACTIVE,
            ip_address='10.20.30.10',
            ssh_user='root',
            ssh_password='secret',
        )
        inactive_resource = TaskResource.objects.create(
            name='inactive-resource-host',
            resource_type=TaskResource.RESOURCE_HOST,
            environment=env,
            status=TaskResource.STATUS_INACTIVE,
            ip_address='10.20.30.11',
            ssh_user='root',
            ssh_password='secret',
        )
        warning_resource = TaskResource.objects.create(
            name='warning-resource-host',
            resource_type=TaskResource.RESOURCE_HOST,
            environment=env,
            status=TaskResource.STATUS_WARNING,
            ip_address='10.20.30.12',
            ssh_user='root',
            ssh_password='secret',
        )

        response = self.client.get('/api/task-resources/')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        items = payload.get('results', payload)
        returned_ids = {item['id'] for item in items}
        self.assertTrue({active_resource.id, inactive_resource.id, warning_resource.id}.issubset(returned_ids))

        stats_response = self.client.get('/api/task-resources/stats/')
        self.assertEqual(stats_response.status_code, 200)
        stats_payload = stats_response.json()
        self.assertGreaterEqual(stats_payload['total'], 3)
        self.assertGreaterEqual(stats_payload['active'], 1)
        self.assertGreaterEqual(stats_payload['warning'], 1)
        self.assertGreaterEqual(stats_payload['inactive'], 1)

        active_response = self.client.get('/api/task-resources/', {'status': TaskResource.STATUS_ACTIVE})
        self.assertEqual(active_response.status_code, 200)
        active_items = active_response.json().get('results', active_response.json())
        self.assertIn(active_resource.id, {item['id'] for item in active_items})
        self.assertNotIn(inactive_resource.id, {item['id'] for item in active_items})

        update_response = self.client.put(
            f'/api/task-resources/{inactive_resource.id}/',
            {
                'name': inactive_resource.name,
                'resource_type': inactive_resource.resource_type,
                'environment': env.id,
                'system': None,
                'status': TaskResource.STATUS_ACTIVE,
                'ip_address': str(inactive_resource.ip_address),
                'ssh_port': inactive_resource.ssh_port,
                'ssh_user': inactive_resource.ssh_user,
                'description': inactive_resource.description,
                'metadata': inactive_resource.metadata,
            },
            format='json',
        )

        self.assertEqual(update_response.status_code, 200)
        inactive_resource.refresh_from_db()
        self.assertEqual(inactive_resource.status, TaskResource.STATUS_ACTIVE)

    def test_task_resource_stats_follow_context_not_selected_resource_type(self):
        env = TaskResourceGroup.objects.create(name='stats-env', group_type=TaskResourceGroup.GROUP_ENVIRONMENT)
        other_env = TaskResourceGroup.objects.create(name='stats-other-env', group_type=TaskResourceGroup.GROUP_ENVIRONMENT)
        cluster = K8sCluster.objects.create(name='stats-env-k3s', kubeconfig='demo', status='connected')
        TaskResource.objects.create(
            name='stats-host',
            resource_type=TaskResource.RESOURCE_HOST,
            environment=env,
            status=TaskResource.STATUS_ACTIVE,
            ip_address='10.30.1.10',
        )
        TaskResource.objects.create(
            name='stats-k8s',
            resource_type=TaskResource.RESOURCE_K8S,
            environment=env,
            status=TaskResource.STATUS_ACTIVE,
            cluster=cluster,
        )
        TaskResource.objects.create(
            name='stats-other-host',
            resource_type=TaskResource.RESOURCE_HOST,
            environment=other_env,
            status=TaskResource.STATUS_ACTIVE,
            ip_address='10.30.1.11',
        )

        response = self.client.get(
            '/api/task-resources/stats/',
            {'environment': env.id, 'resource_type': TaskResource.RESOURCE_HOST},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['total'], 2)
        self.assertEqual(payload['host'], 1)
        self.assertEqual(payload['k8s'], 1)
        self.assertEqual(payload['active'], 2)

    @patch('ops.host_tasks.open_ssh_client')
    def test_task_resource_ssh_failure_does_not_mark_resource_inactive(self, mock_open_ssh_client):
        mock_open_ssh_client.side_effect = RuntimeError('authentication failed')
        env = TaskResourceGroup.objects.create(name='ssh-failure-env', group_type=TaskResourceGroup.GROUP_ENVIRONMENT)
        resource = TaskResource.objects.create(
            name='ssh-failure-resource-host',
            resource_type=TaskResource.RESOURCE_HOST,
            environment=env,
            status=TaskResource.STATUS_ACTIVE,
            ip_address='10.20.40.11',
            ssh_user='root',
            ssh_password='bad-secret',
        )

        response = self.client.post(
            '/api/host-tasks/',
            {
                'name': 'resource-ssh-failure-command',
                'task_type': HostTask.TASK_RUN_COMMAND,
                'execution_mode': HostTask.EXECUTION_MODE_SSH,
                'resource_ids': [resource.id],
                'payload': {'command': 'uptime'},
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['executions'][0]['status'], 'failed')
        resource.refresh_from_db()
        self.assertEqual(resource.status, TaskResource.STATUS_ACTIVE)

    @patch('ops.host_tasks.is_ansible_available', return_value=True)
    @patch('ops.host_tasks.execute_ansible_command')
    def test_task_resource_ansible_failure_does_not_mark_resource_inactive(self, mock_execute_ansible_command, _mock_available):
        mock_execute_ansible_command.side_effect = RuntimeError('UNREACHABLE! authentication failed')
        env = TaskResourceGroup.objects.create(name='ansible-failure-env', group_type=TaskResourceGroup.GROUP_ENVIRONMENT)
        resource = TaskResource.objects.create(
            name='ansible-failure-resource-host',
            resource_type=TaskResource.RESOURCE_HOST,
            environment=env,
            status=TaskResource.STATUS_ACTIVE,
            ip_address='10.20.40.12',
            ssh_user='root',
            ssh_password='bad-secret',
        )

        response = self.client.post(
            '/api/host-tasks/',
            {
                'name': 'resource-ansible-failure-command',
                'task_type': HostTask.TASK_RUN_COMMAND,
                'execution_mode': HostTask.EXECUTION_MODE_ANSIBLE,
                'resource_ids': [resource.id],
                'payload': {'command': 'uptime'},
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['executions'][0]['status'], 'failed')
        resource.refresh_from_db()
        self.assertEqual(resource.status, TaskResource.STATUS_ACTIVE)

    @patch('ops.host_tasks.collect_host_metrics')
    @patch('ops.host_tasks.open_ssh_client')
    def test_refresh_metrics_task_updates_host_usage(self, mock_open_ssh_client, mock_collect_host_metrics):
        mock_open_ssh_client.return_value = MagicMock()
        mock_collect_host_metrics.return_value = (
            {'cpu_usage': 12.5, 'memory_usage': 48.2, 'disk_usage': 66.0},
            {},
        )

        response = self.client.post(
            '/api/host-tasks/',
            {
                'name': 'refresh-prod-host-metrics',
                'task_type': 'refresh_metrics',
                'host_ids': [self.host.id],
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.host.refresh_from_db()
        self.assertEqual(self.host.status, 'online')
        self.assertEqual(self.host.cpu_usage, 12.5)
        self.assertEqual(self.host.memory_usage, 48.2)
        self.assertEqual(self.host.disk_usage, 66.0)

    def test_host_tasks_require_execute_permission(self):
        viewer = get_user_model().objects.create_user('host-viewer', password='Admin@123456')
        role = Role.objects.create(code='host-viewer-role', name='Host Viewer')
        role.permissions.set([])
        role.users.add(viewer)
        self.client.force_authenticate(user=viewer)

        response = self.client.get('/api/host-tasks/')

        self.assertEqual(response.status_code, 403)

    def test_delete_completed_host_task_removes_history_and_executions(self):
        task = HostTask.objects.create(
            name='completed-history-task',
            task_type=HostTask.TASK_RUN_COMMAND,
            status=HostTask.STATUS_SUCCESS,
            lifecycle_status=HostTask.LIFECYCLE_SUCCESS,
            payload={'command': 'uptime'},
            target_count=1,
            success_count=1,
            created_by=self.user.username,
        )
        execution = HostTaskExecution.objects.create(
            task=task,
            host=self.host,
            host_name=self.host.hostname,
            host_ip=str(self.host.ip_address),
            status='success',
            command='uptime',
            output='ok',
        )

        response = self.client.delete(f'/api/host-tasks/{task.id}/')

        self.assertEqual(response.status_code, 204)
        self.assertFalse(HostTask.objects.filter(id=task.id).exists())
        self.assertFalse(HostTaskExecution.objects.filter(id=execution.id).exists())

    def test_delete_running_host_task_is_rejected(self):
        task = HostTask.objects.create(
            name='running-history-task',
            task_type=HostTask.TASK_RUN_COMMAND,
            status=HostTask.STATUS_RUNNING,
            lifecycle_status=HostTask.LIFECYCLE_RUNNING,
            payload={'command': 'uptime'},
            target_count=1,
            created_by=self.user.username,
        )

        response = self.client.delete(f'/api/host-tasks/{task.id}/')

        self.assertEqual(response.status_code, 400)
        self.assertTrue(HostTask.objects.filter(id=task.id).exists())

    def test_k8s_pod_exec_task_records_non_host_execution(self):
        cluster = K8sCluster.objects.create(name='demo-k8s', kubeconfig='demo', status='connected')

        response = self.client.post(
            '/api/host-tasks/',
            {
                'name': 'pod-diagnostic',
                'target_type': HostTask.TARGET_K8S,
                'task_type': HostTask.TASK_K8S_POD_EXEC,
                'k8s_targets': [
                    {
                        'cluster_id': cluster.id,
                        'namespace': 'production',
                        'name': 'api-server-5f8b7c6d4-r9p2w',
                        'kind': 'pod',
                    },
                ],
                'payload': {'command': 'pwd'},
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload['target_type'], HostTask.TARGET_K8S)
        self.assertEqual(payload['execution_mode'], HostTask.EXECUTION_MODE_K8S_API)
        self.assertEqual(payload['status'], HostTask.STATUS_SUCCESS)
        self.assertEqual(payload['success_count'], 1)
        self.assertEqual(payload['executions'][0]['target_type'], HostTask.TARGET_K8S)
        self.assertEqual(payload['executions'][0]['target_namespace'], 'production')
        self.assertIn('demo-exec', payload['executions'][0]['output'])

    def test_k8s_cluster_command_task_records_cluster_level_execution(self):
        cluster = K8sCluster.objects.create(name='demo-k8s-cluster', kubeconfig='demo', status='connected')

        response = self.client.post(
            '/api/host-tasks/',
            {
                'name': 'cluster-diagnostic',
                'target_type': HostTask.TARGET_K8S,
                'task_type': HostTask.TASK_K8S_POD_EXEC,
                'k8s_targets': [
                    {
                        'cluster_id': cluster.id,
                        'kind': 'cluster',
                    },
                ],
                'payload': {'command': 'get pods -A | head -5'},
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload['target_type'], HostTask.TARGET_K8S)
        self.assertEqual(payload['status'], HostTask.STATUS_SUCCESS)
        self.assertEqual(payload['success_count'], 1)
        self.assertEqual(payload['executions'][0]['target_name'], cluster.name)
        self.assertEqual(payload['executions'][0]['target_kind'], 'cluster')
        self.assertEqual(payload['executions'][0]['target_namespace'], '')
        self.assertEqual(payload['executions'][0]['command'], 'kubectl get pods -A | head -5')
        self.assertIn('kubectl get pods -A', payload['executions'][0]['output'])

    def test_k8s_cluster_command_accepts_cluster_target_without_pod_name(self):
        cluster = K8sCluster.objects.create(name='demo-k8s-submit', kubeconfig='demo', status='connected')

        response = self.client.post(
            '/api/host-tasks/',
            {
                'name': 'cluster-submit',
                'target_type': HostTask.TARGET_K8S,
                'task_type': HostTask.TASK_K8S_POD_EXEC,
                'k8s_targets': [
                    {
                        'cluster_id': cluster.id,
                        'kind': 'cluster',
                    },
                ],
                'payload': {'command': 'kubectl get ns'},
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload['executions'][0]['target_kind'], 'cluster')
        self.assertEqual(payload['executions'][0]['target_name'], cluster.name)

    @patch('ops.host_tasks.subprocess.run')
    def test_k8s_apply_heredoc_uses_manifest_file_for_real_cluster(self, mocked_run):
        cluster = K8sCluster.objects.create(
            name='real-k8s-apply',
            kubeconfig='apiVersion: v1\nclusters: []\n',
            status='connected',
        )
        manifest = (
            'apiVersion: apps/v1\n'
            'kind: Deployment\n'
            'metadata:\n'
            '  name: xxl-job-admin\n'
            '---\n'
            'apiVersion: v1\n'
            'kind: Service\n'
            'metadata:\n'
            '  name: xxl-job-admin\n'
        )
        command = (
            "kubectl apply -f - <<'EOF'\n"
            f"{manifest}"
            "EOF\n"
            "kubectl rollout status deployment/xxl-job-admin -n default --timeout=120s\n"
            "kubectl get deploy,svc -n default -l app.kubernetes.io/instance=xxl-job-admin"
        )
        mocked_run.return_value.returncode = 0
        mocked_run.return_value.stdout = 'ok'
        mocked_run.return_value.stderr = ''
        task = HostTask.objects.create(
            name='k8s-apply-heredoc',
            target_type=HostTask.TARGET_K8S,
            task_type=HostTask.TASK_K8S_POD_EXEC,
            execution_mode=HostTask.EXECUTION_MODE_K8S_API,
            payload={
                'command': command,
                'manifest': manifest,
                'resource_kind': 'deployment',
                'namespace': 'default',
            },
            created_by=self.user.username,
        )

        execute_k8s_task(task, [{'cluster_id': cluster.id, 'namespace': 'default', 'name': 'xxl-job-admin', 'kind': 'deployment'}])

        task.refresh_from_db()
        self.assertEqual(task.status, HostTask.STATUS_SUCCESS)
        self.assertEqual(mocked_run.call_count, 3)
        apply_args = mocked_run.call_args_list[0].args[0]
        self.assertEqual(apply_args[0], 'kubectl')
        self.assertIn('--kubeconfig', apply_args)
        self.assertIn('-f', apply_args)
        filename_arg = apply_args[apply_args.index('-f') + 1]
        self.assertNotEqual(filename_arg, '-')
        self.assertNotIn('---', apply_args)
        self.assertIn('rollout', mocked_run.call_args_list[1].args[0])
        self.assertIn('get', mocked_run.call_args_list[2].args[0])

    def test_k8s_helm_release_runs_as_helm_command_not_kubectl(self):
        cluster = K8sCluster.objects.create(name='demo-k8s-helm', kubeconfig='demo', status='connected')

        response = self.client.post(
            '/api/host-tasks/',
            {
                'name': 'helm-redis-release',
                'target_type': HostTask.TARGET_K8S,
                'task_type': HostTask.TASK_K8S_POD_EXEC,
                'k8s_targets': [
                    {
                        'cluster_id': cluster.id,
                        'namespace': 'production',
                        'name': 'redis',
                        'kind': 'helm_release',
                    },
                ],
                'payload': {
                    'deployment_strategy': 'helm',
                    'resource_kind': 'helm_release',
                    'release_name': 'redis',
                    'chart': 'bitnami/redis',
                    'namespace': 'production',
                    'command': 'helm upgrade --install redis bitnami/redis --namespace production --create-namespace',
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload['status'], HostTask.STATUS_SUCCESS)
        execution = payload['executions'][0]
        self.assertEqual(execution['target_kind'], 'helm_release')
        self.assertEqual(execution['command'], 'helm upgrade --install redis bitnami/redis --namespace production --create-namespace')
        self.assertNotIn('kubectl helm', execution['command'])
        self.assertIn('Helm release redis', execution['output'])

    @patch('ops.host_tasks.shutil.which', return_value=None)
    def test_k8s_helm_release_requires_helm_client_for_real_cluster(self, _mock_which):
        cluster = K8sCluster.objects.create(name='real-k8s-helm', kubeconfig='apiVersion: v1\nclusters: []\n', status='connected')
        task = HostTask.objects.create(
            name='helm-real-release',
            target_type=HostTask.TARGET_K8S,
            task_type=HostTask.TASK_K8S_POD_EXEC,
            execution_mode=HostTask.EXECUTION_MODE_K8S_API,
            payload={
                'deployment_strategy': 'helm',
                'resource_kind': 'helm_release',
                'release_name': 'redis',
                'chart': 'bitnami/redis',
                'namespace': 'production',
                'command': 'helm upgrade --install redis bitnami/redis --namespace production --create-namespace',
            },
        )

        execute_k8s_task(task, [{'cluster_id': cluster.id, 'namespace': 'production', 'name': 'redis', 'kind': 'helm_release'}])
        task.refresh_from_db()
        execution = task.executions.first()

        self.assertEqual(task.status, HostTask.STATUS_FAILED)
        self.assertEqual(execution.command, 'helm upgrade --install redis bitnami/redis --namespace production --create-namespace')
        self.assertIn('未安装 Helm 客户端', execution.error_message)

    def test_k8s_service_patch_runs_as_generic_k8s_command(self):
        cluster = K8sCluster.objects.create(name='demo-k8s-service-patch', kubeconfig='demo', status='connected')

        response = self.client.post(
            '/api/host-tasks/',
            {
                'name': 'patch-prometheus-service',
                'target_type': HostTask.TARGET_K8S,
                'task_type': HostTask.TASK_K8S_POD_EXEC,
                'execution_mode': HostTask.EXECUTION_MODE_SSH,
                'execution_strategy': HostTask.STRATEGY_STOP_ON_ERROR,
                'k8s_targets': [
                    {
                        'cluster_id': cluster.id,
                        'kind': 'cluster',
                    },
                ],
                'payload': {
                    'command': 'kubectl patch svc prometheus -n monitoring --type merge -p \'{"spec":{"type":"LoadBalancer"}}\'',
                    'resource_kind': 'service',
                    'service_name': 'prometheus',
                    'namespace': 'monitoring',
                    'patch': {'spec': {'type': 'LoadBalancer'}},
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload['target_type'], HostTask.TARGET_K8S)
        self.assertEqual(payload['task_type'], HostTask.TASK_K8S_POD_EXEC)
        self.assertEqual(payload['execution_mode'], HostTask.EXECUTION_MODE_K8S_API)
        self.assertEqual(payload['status'], HostTask.STATUS_SUCCESS)
        self.assertEqual(payload['risk_level'], HostTask.RISK_HIGH)
        self.assertEqual(payload['target_snapshot'][0]['cluster_name'], cluster.name)
        self.assertEqual(payload['target_snapshot'][0]['namespace'], 'monitoring')
        self.assertEqual(payload['target_snapshot'][0]['name'], 'prometheus')
        self.assertEqual(payload['target_snapshot'][0]['kind'], 'service')
        execution = payload['executions'][0]
        self.assertEqual(execution['target_name'], 'prometheus')
        self.assertEqual(execution['target_namespace'], 'monitoring')
        self.assertEqual(execution['target_kind'], 'service')
        self.assertIn('kubectl patch svc prometheus -n monitoring', execution['command'])
        self.assertIn('K8s API', execution['output'])

    def test_k8s_task_resource_target_maps_to_real_cluster_and_environment(self):
        cluster = K8sCluster.objects.create(name='电商测试环境-k3s', kubeconfig='demo', status='connected')
        env = TaskResourceGroup.objects.create(name='电商测试环境', group_type=TaskResourceGroup.GROUP_ENVIRONMENT)
        TaskResource.objects.create(
            name='dummy-host',
            resource_type=TaskResource.RESOURCE_HOST,
            environment=env,
            status=TaskResource.STATUS_ACTIVE,
            ip_address='10.1.1.1',
        )
        resource = TaskResource.objects.create(
            name='电商测试环境-k3s',
            resource_type=TaskResource.RESOURCE_K8S,
            environment=env,
            status=TaskResource.STATUS_ACTIVE,
        )

        response = self.client.post(
            '/api/host-tasks/',
            {
                'name': 'patch-prometheus-nodeport',
                'target_type': HostTask.TARGET_K8S,
                'task_type': HostTask.TASK_K8S_POD_EXEC,
                'k8s_targets': [
                    {
                        'cluster_id': resource.id,
                        'resource_id': resource.id,
                        'cluster_name': resource.name,
                        'namespace': 'monitoring',
                        'name': 'prometheus',
                        'kind': 'service',
                    },
                ],
                'payload': {
                    'command': 'kubectl patch svc prometheus -n monitoring --type strategic -p \'{"spec":{"type":"NodePort","ports":[{"port":9090,"nodePort":31001}]}}\'',
                    'resource_kind': 'service',
                    'service_name': 'prometheus',
                    'namespace': 'monitoring',
                    'patch_type': 'strategic',
                    'patch': {'spec': {'type': 'NodePort', 'ports': [{'port': 9090, 'nodePort': 31001}]}},
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload['status'], HostTask.STATUS_SUCCESS)
        self.assertEqual(payload['environment_display'], '电商测试环境')
        self.assertEqual(payload['source_context']['resource_environment'], '电商测试环境')
        self.assertEqual(payload['target_snapshot'][0]['cluster_id'], cluster.id)
        self.assertEqual(payload['target_snapshot'][0]['resource_id'], resource.id)
        self.assertEqual(payload['target_snapshot'][0]['environment_name'], '电商测试环境')
        self.assertEqual(payload['target_snapshot'][0]['cluster_name'], '电商测试环境-k3s')
        self.assertEqual(payload['executions'][0]['target_name'], 'prometheus')
        self.assertEqual(payload['executions'][0]['target_namespace'], 'monitoring')
        self.assertIn('K8s API', payload['executions'][0]['output'])

    def test_k8s_task_api_rejects_invalid_cluster_target(self):
        response = self.client.post(
            '/api/host-tasks/',
            {
                'name': 'invalid-k8s-cluster',
                'target_type': HostTask.TARGET_K8S,
                'task_type': HostTask.TASK_K8S_POD_EXEC,
                'k8s_targets': [
                    {
                        'cluster_id': 99999,
                        'kind': 'cluster',
                    },
                ],
                'payload': {'command': 'kubectl get ns'},
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('k8s_targets', response.json())

    def test_k8s_executor_marks_invalid_snapshot_target_failed(self):
        task = HostTask.objects.create(
            name='stale-invalid-k8s-target',
            target_type=HostTask.TARGET_K8S,
            task_type=HostTask.TASK_K8S_POD_EXEC,
            payload={'command': 'kubectl get ns'},
            execution_mode=HostTask.EXECUTION_MODE_K8S_API,
            created_by=self.user.username,
        )

        execute_k8s_task(task, [{'cluster_id': 99999, 'cluster_name': 'Cluster 99999', 'kind': 'cluster'}])

        task.refresh_from_db()
        self.assertEqual(task.status, HostTask.STATUS_FAILED)
        self.assertEqual(task.lifecycle_status, HostTask.LIFECYCLE_FAILED)
        self.assertEqual(task.failed_count, 1)
        execution = task.executions.get()
        self.assertEqual(execution.status, 'failed')
        self.assertIn('未找到 K8s 集群', execution.error_message)

    def test_non_k8s_task_cannot_use_k8s_api_execution_mode(self):
        response = self.client.post(
            '/api/host-tasks/',
            {
                'name': 'invalid-k8s-api-mode',
                'task_type': 'run_command',
                'execution_mode': HostTask.EXECUTION_MODE_K8S_API,
                'host_ids': [self.host.id],
                'payload': {'command': 'uptime'},
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('execution_mode', response.json())

    def test_k8s_resource_options_include_unmapped_clusters(self):
        cluster = K8sCluster.objects.create(
            name='task-option-k3s',
            api_server='https://10.10.10.2:6443',
            kubeconfig='demo',
            status='connected',
            description='测试集群',
        )

        response = self.client.get('/api/host-tasks/resource_options/', {'resource_type': TaskResource.RESOURCE_K8S})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        option = next(item for item in payload if item['cluster'] == cluster.id)
        self.assertEqual(option['id'], f'cluster:{cluster.id}')
        self.assertEqual(option['name'], cluster.name)
        self.assertEqual(option['resource_type'], TaskResource.RESOURCE_K8S)
        self.assertEqual(option['status'], TaskResource.STATUS_ACTIVE)
        self.assertEqual(option['endpoint'], cluster.api_server)

    @patch('ops.host_tasks.open_ssh_client')
    def test_create_task_preserves_aiops_trigger_source(self, mock_open_ssh_client):
        mock_open_ssh_client.return_value = self._mock_client({
            'uptime': {'exit_status': 0, 'stdout': 'from-aiops'},
        })

        response = self.client.post(
            '/api/host-tasks/',
            {
                'name': 'aiops-draft-task',
                'task_type': 'run_command',
                'host_ids': [self.host.id],
                'payload': {'command': 'uptime'},
                'trigger_source': HostTask.TRIGGER_SOURCE_AIOPS,
                'source_context': {
                    'source': 'aiops',
                    'session_id': 88,
                    'pending_action_id': 99,
                    'request_summary': 'aiops generated uptime check',
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload['trigger_source'], HostTask.TRIGGER_SOURCE_AIOPS)
        self.assertEqual(payload['source_context']['source'], 'aiops')
        self.assertEqual(payload['source_context']['session_id'], 88)

    @patch('ops.host_tasks.open_ssh_client')
    def test_create_task_links_aiops_pending_action(self, mock_open_ssh_client):
        mock_open_ssh_client.return_value = self._mock_client({
            'uptime': {'exit_status': 0, 'stdout': 'from-aiops'},
        })
        session = AIOpsChatSession.objects.create(user=self.user, title='aiops-task')
        message = AIOpsChatMessage.objects.create(session=session, role=AIOpsChatMessage.ROLE_ASSISTANT, content='任务草稿')
        pending_action = AIOpsPendingAction.objects.create(
            session=session,
            message=message,
            action_type=AIOpsPendingAction.ACTION_EXECUTE_HOST_TASK,
            title='服务器巡检任务',
            risk_level=AIOpsPendingAction.RISK_LOW,
            status=AIOpsPendingAction.STATUS_EXECUTED,
            action_payload={'name': '服务器巡检任务'},
            result_payload={'draft_ready': True, 'task_name': '服务器巡检任务', 'materialized_in_task_center': False},
        )

        response = self.client.post(
            '/api/host-tasks/',
            {
                'name': '服务器巡检任务',
                'task_type': 'run_command',
                'host_ids': [self.host.id],
                'payload': {'command': 'uptime'},
                'trigger_source': HostTask.TRIGGER_SOURCE_AIOPS,
                'source_context': {
                    'source': 'aiops',
                    'session_id': session.id,
                    'pending_action_id': pending_action.id,
                    'request_summary': '帮我建个服务器巡检任务',
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        task_id = response.json()['id']
        pending_action.refresh_from_db()
        self.assertEqual(pending_action.result_payload['task_id'], task_id)
        self.assertEqual(pending_action.result_payload['created_task_id'], task_id)
        self.assertEqual(pending_action.result_payload['task_name'], '服务器巡检任务')
        self.assertTrue(pending_action.result_payload['materialized_in_task_center'])

    @patch('ops.host_tasks.open_ssh_client')
    def test_rerun_reuses_original_targets_and_mode(self, mock_open_ssh_client):
        mock_open_ssh_client.return_value = self._mock_client({
            'uptime': {'exit_status': 0, 'stdout': 'ok'},
        })
        create_response = self.client.post(
            '/api/host-tasks/',
            {
                'name': 'initial-run',
                'task_type': 'run_command',
                'execution_mode': HostTask.EXECUTION_MODE_ANSIBLE,
                'host_ids': [self.host.id],
                'payload': {'command': 'uptime'},
            },
            format='json',
        )
        task_id = create_response.json()['id']

        rerun_response = self.client.post(f'/api/host-tasks/{task_id}/rerun/', {}, format='json')

        self.assertEqual(rerun_response.status_code, 201)
        rerun_payload = rerun_response.json()
        self.assertEqual(rerun_payload['target_count'], 1)
        self.assertEqual(rerun_payload['created_by'], self.user.username)
        self.assertEqual(rerun_payload['execution_mode'], HostTask.EXECUTION_MODE_ANSIBLE)
        self.assertTrue(HostTask.objects.filter(id=rerun_payload['id']).exists())

    def test_update_personal_template(self):
        template = HostTaskTemplate.objects.create(
            name='health-check',
            task_type='run_command',
            description='before update',
            payload={'command': 'uptime'},
            execution_mode=HostTask.EXECUTION_MODE_SSH,
            execution_strategy=HostTask.STRATEGY_CONTINUE,
            timeout_seconds=20,
            created_by=self.user.username,
        )

        response = self.client.put(
            f'/api/host-task-templates/{template.id}/',
            {
                'name': 'health-check-v2',
                'task_type': 'run_command',
                'description': 'after update',
                'payload': {'command': 'hostname && uptime'},
                'execution_mode': HostTask.EXECUTION_MODE_ANSIBLE,
                'execution_strategy': 'stop_on_error',
                'timeout_seconds': 35,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        template.refresh_from_db()
        self.assertEqual(template.name, 'health-check-v2')
        self.assertEqual(template.payload['command'], 'hostname && uptime')
        self.assertEqual(template.execution_mode, HostTask.EXECUTION_MODE_ANSIBLE)
        self.assertEqual(template.execution_strategy, HostTask.STRATEGY_STOP_ON_ERROR)
        self.assertEqual(template.timeout_seconds, 35)

    def test_create_playbook_template_forces_ansible_mode(self):
        response = self.client.post(
            '/api/host-task-templates/',
            {
                'name': 'deploy-playbook',
                'task_type': HostTask.TASK_RUN_PLAYBOOK,
                'description': 'deploy app',
                'payload': {
                    'playbook_name': 'deploy-app.yml',
                    'playbook_content': '- hosts: targets\\n  gather_facts: false\\n  tasks: []',
                },
                'execution_mode': HostTask.EXECUTION_MODE_SSH,
                'execution_strategy': HostTask.STRATEGY_STOP_ON_ERROR,
                'timeout_seconds': 40,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload['execution_mode'], HostTask.EXECUTION_MODE_ANSIBLE)

    def test_non_k8s_template_cannot_use_k8s_api_execution_mode(self):
        response = self.client.post(
            '/api/host-task-templates/',
            {
                'name': 'invalid-k8s-api-template',
                'task_type': 'run_command',
                'target_type': HostTask.TARGET_HOST,
                'execution_mode': HostTask.EXECUTION_MODE_K8S_API,
                'payload': {'command': 'uptime'},
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('execution_mode', response.json())

    def test_cannot_update_builtin_template(self):
        template = HostTaskTemplate.objects.create(
            name='builtin-template',
            task_type='refresh_metrics',
            description='demo',
            payload={},
            execution_mode=HostTask.EXECUTION_MODE_SSH,
            execution_strategy=HostTask.STRATEGY_CONTINUE,
            timeout_seconds=15,
            is_builtin=True,
            created_by='system',
        )

        response = self.client.put(
            f'/api/host-task-templates/{template.id}/',
            {
                'name': 'builtin-template-v2',
                'task_type': 'refresh_metrics',
                'description': 'updated',
                'payload': {},
                'execution_mode': HostTask.EXECUTION_MODE_SSH,
                'execution_strategy': 'continue',
                'timeout_seconds': 15,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        template.refresh_from_db()
        self.assertEqual(template.name, 'builtin-template')
