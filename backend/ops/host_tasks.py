import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import paramiko
from django.conf import settings
from django.db import close_old_connections
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify

from .models import Host, HostTask, HostTaskExecution, K8sCluster, TaskResource

_TASK_THREADS = {}
_TASK_THREADS_LOCK = threading.Lock()


def _task_group_event_environment(group):
    if not group or not getattr(group, 'event_environment_id', None):
        return '', ''
    event_environment = getattr(group, 'event_environment', None)
    if not event_environment:
        return '', ''
    return event_environment.code or '', event_environment.name or ''


def _resource_event_environment(resource):
    if not resource or not getattr(resource, 'environment_id', None):
        return '', ''
    return _task_group_event_environment(getattr(resource, 'environment', None))


class AnsibleControllerError(RuntimeError):
    pass


_BLOCKED_REMOTE_COMMAND_PATTERNS = (
    re.compile(r'(^|[;&|\n\r])\s*(?:rm\s+-r(?:f)?|shutdown|reboot|mkfs|userdel|kill\s+-9)\b', re.IGNORECASE),
    re.compile(r'\b(?:curl|wget)\b[^\n|;&]*\|\s*(?:ba)?sh\b', re.IGNORECASE),
    re.compile(r'`', re.IGNORECASE),
)


def _validate_remote_command(task, command_text):
    text = str(command_text or '')
    if any(pattern.search(text) for pattern in _BLOCKED_REMOTE_COMMAND_PATTERNS):
        raise ValueError('检测到高风险远程命令，系统已拒绝执行。')
    if task.task_type == HostTask.TASK_RUN_COMMAND and not (task.payload or {}).get('script_purpose'):
        if any(token in text for token in (';', '&&', '||', '\n', '\r', '|')):
            raise ValueError('批量命令禁止 shell 拼接、管道和多行脚本，请提交单条受控命令。')


class TaskResourceHostTarget:
    def __init__(self, resource):
        self.source = 'task_resource'
        self.resource_id = resource.id
        self.id = resource.id
        self.hostname = resource.name
        self.ip_address = str(resource.ip_address or '')
        self.business_line = resource.system.name if resource.system_id else ''
        self.system_name = self.business_line
        self.environment = resource.environment.name if resource.environment_id else ''
        self.event_environment, self.event_environment_name = _resource_event_environment(resource)
        self.status = 'online' if resource.status == TaskResource.STATUS_ACTIVE else 'offline'
        self.ssh_port = resource.ssh_port or 22
        self.ssh_user = resource.ssh_user or 'root'
        self.ssh_password = resource.ssh_password or ''
        self.admin_user = resource.owner or ''

    def save(self, update_fields=None):
        status = TaskResource.STATUS_ACTIVE if self.status == 'online' else TaskResource.STATUS_INACTIVE
        TaskResource.objects.filter(pk=self.resource_id).update(status=status, updated_at=timezone.now())


def normalize_host_execution_targets(hosts):
    normalized = []
    seen = set()
    for host in hosts or []:
        if isinstance(host, TaskResource):
            target = TaskResourceHostTarget(host)
            identity = ('task_resource', target.resource_id)
        elif isinstance(host, TaskResourceHostTarget):
            target = host
            identity = ('task_resource', target.resource_id)
        else:
            target = host
            identity = ('host', getattr(target, 'id', id(target)))
        if identity in seen:
            continue
        seen.add(identity)
        normalized.append(target)
    return normalized


def _execution_host_fk(host):
    return host if isinstance(host, Host) else None


def _execution_target_fields(host):
    if isinstance(host, TaskResourceHostTarget):
        return {
            'target_type': HostTask.TARGET_HOST,
            'target_id': f'task_resource:{host.resource_id}',
            'target_name': host.hostname,
            'target_kind': 'task_resource_host',
        }
    return {
        'target_type': HostTask.TARGET_HOST,
        'target_id': str(host.id),
        'target_name': host.hostname,
        'target_kind': 'host',
    }


def _host_source_ref(host):
    if isinstance(host, TaskResourceHostTarget):
        return {'source': 'task_resource', 'id': host.resource_id}
    return {'source': 'host', 'id': host.id}


def _trim_noisy_disk_summary(text):
    cleaned_lines = []
    for line in str(text or '').splitlines():
        normalized = line.strip()
        if (
            '/var/lib/kubelet/pods/' in normalized
            or '/run/k3s/containerd/' in normalized
            or '/run/containerd/' in normalized
        ):
            continue
        cleaned_lines.append(line)
    return '\n'.join(cleaned_lines).strip()


def _format_ansible_playbook_output(output):
    text = str(output or '').strip()
    if not text or '"msg": [' not in text:
        return text
    match = re.search(r'"msg":\s*(\[[\s\S]*?\])', text)
    if not match:
        return text
    try:
        items = json.loads(match.group(1))
    except json.JSONDecodeError:
        return text
    if not isinstance(items, list) or not items or not all(isinstance(item, str) for item in items):
        return text
    formatted_parts = []
    for item in items:
        cleaned = _trim_noisy_disk_summary(item).strip()
        if cleaned:
            formatted_parts.append(cleaned)
    if not formatted_parts:
        return text
    return '\n\n'.join(formatted_parts)


def resolve_host_source_refs(refs):
    if refs and isinstance(refs[0], int):
        refs = [{'source': 'host', 'id': item} for item in refs]
    host_ids = [item.get('id') for item in refs if item.get('source') == 'host' and item.get('id')]
    resource_ids = [item.get('id') for item in refs if item.get('source') == 'task_resource' and item.get('id')]
    host_map = {host.id: host for host in Host.objects.filter(id__in=host_ids)}
    resource_map = {
        resource.id: TaskResourceHostTarget(resource)
        for resource in TaskResource.objects.select_related('environment__event_environment', 'system').filter(
            id__in=resource_ids,
            resource_type=TaskResource.RESOURCE_HOST,
        )
    }
    targets = []
    for item in refs:
        source = item.get('source') or 'host'
        target_id = item.get('id')
        if source == 'task_resource' and target_id in resource_map:
            targets.append(resource_map[target_id])
        elif source == 'host' and target_id in host_map:
            targets.append(host_map[target_id])
    return targets


def build_host_target_snapshot(hosts):
    snapshot = []
    for host in hosts:
        source = 'task_resource' if isinstance(host, TaskResourceHostTarget) else 'host'
        snapshot.append({
            'id': host.id,
            'source': source,
            'resource_id': host.resource_id if source == 'task_resource' else None,
            'hostname': host.hostname,
            'ip_address': host.ip_address,
            'business_line': getattr(host, 'business_line', ''),
            'system_name': getattr(host, 'system_name', getattr(host, 'business_line', '')),
            'environment': host.environment,
            'environment_name': host.environment,
            'event_environment': getattr(host, 'event_environment', ''),
            'event_environment_name': getattr(host, 'event_environment_name', ''),
            'status': host.status,
        })
    return snapshot


def build_host_target_queryset(filters=None):
    filters = filters or {}
    queryset = Host.objects.all().order_by('hostname', 'id')

    search = (filters.get('search') or '').strip()
    if search:
        queryset = queryset.filter(Q(hostname__icontains=search) | Q(ip_address__icontains=search))

    status = (filters.get('status') or '').strip()
    if status:
        queryset = queryset.filter(status=status)

    business_line = (filters.get('business_line') or '').strip()
    if business_line:
        queryset = queryset.filter(business_line=business_line)

    environment = (filters.get('environment') or '').strip()
    if environment:
        queryset = queryset.filter(environment=environment)

    return queryset.order_by('hostname', 'id')


def get_ansible_binary():
    return getattr(settings, 'HOST_TASK_ANSIBLE_BINARY', 'ansible')


def get_ansible_playbook_binary():
    return getattr(settings, 'HOST_TASK_ANSIBLE_PLAYBOOK_BINARY', 'ansible-playbook')


def is_ansible_available():
    return bool(shutil.which(get_ansible_binary()))


def is_ansible_playbook_available():
    return bool(shutil.which(get_ansible_playbook_binary()))


def allow_ansible_fallback_to_ssh():
    configured = getattr(settings, 'HOST_TASK_ANSIBLE_FALLBACK_TO_SSH', None)
    if configured is not None:
        return configured
    return bool(getattr(settings, 'DEBUG', False))


def _ansible_ssh_common_args():
    return getattr(
        settings,
        'HOST_TASK_ANSIBLE_SSH_COMMON_ARGS',
        '-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null',
    )


def _ansible_inventory_alias(host):
    return f"host_{host.id}_{slugify(host.hostname) or 'node'}"


def open_ssh_client(host, timeout_seconds):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host.ip_address,
        port=host.ssh_port or 22,
        username=host.ssh_user or 'root',
        password=host.ssh_password or None,
        timeout=timeout_seconds,
    )
    return client


def execute_remote_command(client, command, timeout_seconds):
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout_seconds)
    exit_status = stdout.channel.recv_exit_status()
    output = stdout.read().decode('utf-8', errors='replace').strip()
    error_output = stderr.read().decode('utf-8', errors='replace').strip()
    return exit_status, output, error_output


def _metrics_shell_command():
    return (
        "printf 'CPU='; top -bn1 | grep 'Cpu(s)' | awk '{print $2}'; "
        "printf '\\nMEM='; free | grep Mem | awk '{printf(\"%.1f\", $3/$2*100)}'; "
        "printf '\\nDISK='; df / | tail -1 | awk '{print $5}' | tr -d '%'"
    )


def _build_command_text(task):
    if task.task_type == HostTask.TASK_CHECK_CONNECTION:
        return 'hostname && uname -sr'
    if task.task_type == HostTask.TASK_REFRESH_METRICS:
        return 'metrics: cpu/memory/disk refresh'
    if task.task_type == HostTask.TASK_RUN_PLAYBOOK:
        playbook_name = ((task.payload or {}).get('playbook_name') or '').strip() or 'inline-playbook.yml'
        return f'ansible-playbook {playbook_name}'
    if task.task_type == HostTask.TASK_SERVICE_STATUS:
        service_name = (task.payload or {}).get('service_name', '').strip()
        return f"systemctl status {shlex.quote(service_name)} --no-pager --lines=12"
    return ((task.payload or {}).get('command') or '').strip()


def _build_remote_command(task):
    if task.task_type == HostTask.TASK_REFRESH_METRICS:
        return _metrics_shell_command()
    return _build_command_text(task)


def _parse_metrics_output(output):
    metrics = {}
    raw_outputs = {}
    mapping = {'CPU': 'cpu_usage', 'MEM': 'memory_usage', 'DISK': 'disk_usage'}
    for line in (output or '').splitlines():
        if '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip().upper()
        value = value.strip()
        if key not in mapping:
            continue
        raw_outputs[mapping[key]] = value
        try:
            metrics[mapping[key]] = round(float(value), 1)
        except (TypeError, ValueError):
            continue
    return metrics, raw_outputs


def collect_host_metrics(client, timeout_seconds):
    exit_status, output, error_output = execute_remote_command(client, _metrics_shell_command(), timeout_seconds)
    if exit_status != 0:
        return {}, {'metrics': error_output or output}
    return _parse_metrics_output(output)


def _mark_host_offline(host):
    if isinstance(host, TaskResourceHostTarget):
        return
    if host.status != 'offline':
        host.status = 'offline'
        host.save(update_fields=['status'])


def _should_mark_host_offline(message):
    lowered = str(message or '').lower()
    keywords = ['unreachable', 'failed to connect', 'permission denied', 'timed out', 'connection refused', 'authentication failed']
    return any(keyword in lowered for keyword in keywords)


def _create_skipped_execution(task, host, message):
    HostTaskExecution.objects.create(
        task=task,
        host=_execution_host_fk(host),
        host_name=host.hostname,
        host_ip=host.ip_address,
        **_execution_target_fields(host),
        status='skipped',
        command='',
        output='',
        error_message=message,
        started_at=timezone.now(),
        finished_at=timezone.now(),
        duration_ms=0,
    )
    task.skipped_count += 1


def _create_failed_execution(task, host, command_text, message):
    return HostTaskExecution.objects.create(
        task=task,
        host=_execution_host_fk(host),
        host_name=host.hostname,
        host_ip=host.ip_address,
        **_execution_target_fields(host),
        status='failed',
        command=command_text,
        output='',
        error_message=(message or '')[:4000],
        started_at=timezone.now(),
        finished_at=timezone.now(),
        duration_ms=0,
    )


def _create_running_host_execution(task, host, command_text):
    return HostTaskExecution.objects.create(
        task=task,
        host=_execution_host_fk(host),
        host_name=host.hostname,
        host_ip=host.ip_address,
        **_execution_target_fields(host),
        status='running',
        command=command_text,
        output='',
        error_message='',
        started_at=timezone.now(),
    )


def _finish_execution(execution, status, output='', error_message='', started_at=None, monotonic_started=None):
    finished_at = timezone.now()
    if started_at:
        execution.started_at = started_at
    execution.finished_at = finished_at
    if monotonic_started is not None:
        execution.duration_ms = int((time.monotonic() - monotonic_started) * 1000)
    elif execution.started_at:
        execution.duration_ms = max(int((finished_at - execution.started_at).total_seconds() * 1000), 0)
    execution.status = status
    execution.output = (output or '')[:8000]
    execution.error_message = (error_message or '')[:4000]
    execution.save(update_fields=['status', 'output', 'error_message', 'duration_ms', 'started_at', 'finished_at'])
    return execution


def _build_ansible_extra_vars(host):
    extra_vars = {
        'ansible_connection': 'ssh',
        'ansible_user': host.ssh_user or 'root',
        'ansible_port': host.ssh_port or 22,
    }
    common_args = _ansible_ssh_common_args()
    if common_args:
        extra_vars['ansible_ssh_common_args'] = common_args
    if host.ssh_password:
        extra_vars['ansible_password'] = host.ssh_password
    return extra_vars


def _build_ansible_process_env():
    env = dict(**getattr(settings, 'HOST_TASK_ANSIBLE_ENV', {}))
    process_env = dict(os.environ)
    process_env.update({'ANSIBLE_HOST_KEY_CHECKING': 'False', 'PYTHONIOENCODING': 'utf-8'})
    process_env.update(env)
    return process_env


def _normalize_playbook_filename(playbook_name):
    raw_name = (playbook_name or '').strip()
    suffix = '.yaml' if raw_name.endswith('.yaml') else '.yml'
    stem = Path(raw_name).stem if raw_name else 'inline-playbook'
    normalized = slugify(stem) or 'inline-playbook'
    return f'{normalized}{suffix}'


def _extract_ansible_payload(text):
    content = (text or '').strip()
    if '>>' in content:
        content = content.split('>>', 1)[1].strip()
    return content


def _is_ansible_controller_error(message):
    lowered = str(message or '').lower()
    keywords = [
        'sshpass',
        'ansible command not found',
        'is not recognized as an internal or external command',
        'unsupported platform',
        'failed to create temporary directory',
        'no such file or directory',
    ]
    return any(keyword in lowered for keyword in keywords)


def execute_ansible_command(host, command_text, timeout_seconds):
    if not is_ansible_available():
        raise AnsibleControllerError('未检测到 Ansible 控制端环境：后端运行环境未找到 ansible 命令，请安装 ansible-core 或配置 HOST_TASK_ANSIBLE_BINARY。')

    alias = _ansible_inventory_alias(host)
    extra_vars = _build_ansible_extra_vars(host)
    process_env = _build_ansible_process_env()

    with tempfile.TemporaryDirectory(prefix='sxdevops_ansible_') as tmpdir:
        inventory_path = Path(tmpdir) / 'inventory.ini'
        inventory_path.write_text(f'[targets]\n{alias} ansible_host={host.ip_address}\n', encoding='utf-8')
        command = [
            get_ansible_binary(),
            alias,
            '-i',
            str(inventory_path),
            '-m',
            'raw',
            '-a',
            command_text,
            '-T',
            str(max(5, min(timeout_seconds, 120))),
            '-e',
            json.dumps(extra_vars, ensure_ascii=False),
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=max(timeout_seconds + 20, 30),
                env=process_env,
            )
        except FileNotFoundError as exc:
            raise AnsibleControllerError(str(exc)) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f'Ansible command timeout: {exc.timeout}s') from exc

    stdout = (result.stdout or '').strip()
    stderr = (result.stderr or '').strip()
    payload = _extract_ansible_payload(stdout)
    if result.returncode == 0:
        return payload, ''

    message = stderr or payload or stdout or f'ansible exit code {result.returncode}'
    if _is_ansible_controller_error(message):
        raise AnsibleControllerError(message)
    raise RuntimeError(message)


def execute_ansible_playbook(host, playbook_content, timeout_seconds, playbook_name='', extra_vars=None):
    if not is_ansible_playbook_available():
        raise AnsibleControllerError('未检测到 Ansible Playbook 控制端环境：后端运行环境未找到 ansible-playbook 命令，请安装 ansible-core 或配置 HOST_TASK_ANSIBLE_PLAYBOOK_BINARY。')

    alias = _ansible_inventory_alias(host)
    merged_extra_vars = _build_ansible_extra_vars(host)
    if isinstance(extra_vars, dict):
        merged_extra_vars.update(extra_vars)
    process_env = _build_ansible_process_env()

    with tempfile.TemporaryDirectory(prefix='sxdevops_playbook_') as tmpdir:
        inventory_path = Path(tmpdir) / 'inventory.ini'
        playbook_path = Path(tmpdir) / _normalize_playbook_filename(playbook_name)
        inventory_path.write_text(f'[targets]\n{alias} ansible_host={host.ip_address}\n', encoding='utf-8')
        playbook_path.write_text((playbook_content or '').strip() + '\n', encoding='utf-8')
        command = [
            get_ansible_playbook_binary(),
            '-i',
            str(inventory_path),
            str(playbook_path),
            '--limit',
            alias,
            '-e',
            json.dumps(merged_extra_vars, ensure_ascii=False),
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=max(timeout_seconds + 20, 30),
                env=process_env,
            )
        except FileNotFoundError as exc:
            raise AnsibleControllerError(str(exc)) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f'Ansible playbook timeout: {exc.timeout}s') from exc

    stdout = (result.stdout or '').strip()
    stderr = (result.stderr or '').strip()
    if result.returncode == 0:
        return stdout, stderr

    message = stderr or stdout or f'ansible-playbook exit code {result.returncode}'
    if _is_ansible_controller_error(message):
        raise AnsibleControllerError(message)
    raise RuntimeError(message)


def _run_single_task_with_ssh(task, host):
    started_at = timezone.now()
    monotonic_started = time.monotonic()
    command_text = _build_command_text(task)
    _validate_remote_command(task, command_text)
    execution = _create_running_host_execution(task, host, command_text)
    output = ''
    error_message = ''
    status = 'success'

    try:
        client = open_ssh_client(host, task.timeout_seconds)
        try:
            if task.task_type == HostTask.TASK_CHECK_CONNECTION:
                exit_status, output, error_message = execute_remote_command(client, command_text, task.timeout_seconds)
                host.status = 'online'
                host.save(update_fields=['status'])
                status = 'success' if exit_status == 0 else 'failed'
            elif task.task_type == HostTask.TASK_REFRESH_METRICS:
                metrics, raw_outputs = collect_host_metrics(client, task.timeout_seconds)
                for key, value in metrics.items():
                    setattr(host, key, value)
                host.status = 'online'
                host.save(update_fields=['cpu_usage', 'memory_usage', 'disk_usage', 'status'])
                output = f'CPU {host.cpu_usage}% | \u5185\u5b58 {host.memory_usage}% | \u78c1\u76d8 {host.disk_usage}%'
                if raw_outputs and not metrics:
                    error_message = '; '.join([f'{key}: {value}' for key, value in raw_outputs.items() if value])
                status = 'success'
            elif task.task_type == HostTask.TASK_SERVICE_STATUS:
                exit_status, output, error_message = execute_remote_command(client, command_text, task.timeout_seconds)
                status = 'success' if exit_status == 0 else 'failed'
            else:
                exit_status, output, error_message = execute_remote_command(client, command_text, task.timeout_seconds)
                status = 'success' if exit_status == 0 else 'failed'
        finally:
            client.close()
    except Exception as exc:
        _mark_host_offline(host)
        status = 'failed'
        error_message = str(exc)

    finished_at = timezone.now()
    duration_ms = int((time.monotonic() - monotonic_started) * 1000)
    execution.finished_at = finished_at
    execution.duration_ms = duration_ms
    execution.status = status
    execution.output = output[:8000]
    execution.error_message = error_message[:4000]
    execution.started_at = started_at
    execution.save(update_fields=['status', 'output', 'error_message', 'duration_ms', 'started_at', 'finished_at'])
    return execution


def _run_single_task_with_ansible(task, host):
    started_at = timezone.now()
    monotonic_started = time.monotonic()
    command_text = _build_command_text(task)
    _validate_remote_command(task, command_text)
    if task.task_type == HostTask.TASK_RUN_PLAYBOOK:
        if not is_ansible_playbook_available():
            raise AnsibleControllerError('未检测到 Ansible Playbook 控制端环境：后端运行环境未找到 ansible-playbook 命令，请安装 ansible-core 或配置 HOST_TASK_ANSIBLE_PLAYBOOK_BINARY。')
    elif not is_ansible_available():
        raise AnsibleControllerError('未检测到 Ansible 控制端环境：后端运行环境未找到 ansible 命令，请安装 ansible-core 或配置 HOST_TASK_ANSIBLE_BINARY。')
    execution = _create_running_host_execution(task, host, command_text)
    output = ''
    error_message = ''
    status = 'success'

    try:
        if task.task_type == HostTask.TASK_RUN_PLAYBOOK:
            raw_output, raw_error = execute_ansible_playbook(
                host,
                (task.payload or {}).get('playbook_content', ''),
                task.timeout_seconds,
                (task.payload or {}).get('playbook_name', ''),
                (task.payload or {}).get('extra_vars') or {},
            )
            raw_output = _format_ansible_playbook_output(raw_output)
        else:
            raw_output, raw_error = execute_ansible_command(host, _build_remote_command(task), task.timeout_seconds)
        if task.task_type == HostTask.TASK_REFRESH_METRICS:
            metrics, raw_outputs = _parse_metrics_output(raw_output)
            for key, value in metrics.items():
                setattr(host, key, value)
            host.status = 'online'
            host.save(update_fields=['cpu_usage', 'memory_usage', 'disk_usage', 'status'])
            output = f'CPU {host.cpu_usage}% | \u5185\u5b58 {host.memory_usage}% | \u78c1\u76d8 {host.disk_usage}%'
            if raw_outputs and not metrics:
                error_message = '; '.join([f'{key}: {value}' for key, value in raw_outputs.items() if value])
        else:
            output = raw_output
            if task.task_type == HostTask.TASK_CHECK_CONNECTION:
                host.status = 'online'
                host.save(update_fields=['status'])
    except AnsibleControllerError:
        execution.delete()
        raise
    except Exception as exc:
        status = 'failed'
        error_message = str(exc)
        if _should_mark_host_offline(error_message):
            _mark_host_offline(host)

    finished_at = timezone.now()
    duration_ms = int((time.monotonic() - monotonic_started) * 1000)
    execution.finished_at = finished_at
    execution.duration_ms = duration_ms
    execution.status = status
    execution.output = output[:8000]
    execution.error_message = error_message[:4000]
    execution.started_at = started_at
    execution.save(update_fields=['status', 'output', 'error_message', 'duration_ms', 'started_at', 'finished_at'])
    return execution


def _run_single_task(task, host, execution_mode):
    if execution_mode == HostTask.EXECUTION_MODE_ANSIBLE:
        return _run_single_task_with_ansible(task, host)
    return _run_single_task_with_ssh(task, host)


def _task_result_for_event(status):
    try:
        from eventwall.models import EventRecord
    except Exception:
        return 'success'
    if status == HostTask.STATUS_FAILED:
        return EventRecord.RESULT_FAILED
    if status == HostTask.STATUS_PARTIAL:
        return EventRecord.RESULT_PARTIAL
    if status == HostTask.STATUS_CANCELED:
        return EventRecord.RESULT_FAILED
    if status == HostTask.STATUS_PENDING:
        return EventRecord.RESULT_PENDING
    return EventRecord.RESULT_SUCCESS


def _task_severity_for_event(task):
    try:
        from eventwall.models import EventRecord
    except Exception:
        return 'info'
    if task.risk_level in [HostTask.RISK_CRITICAL, HostTask.RISK_HIGH]:
        return EventRecord.SEVERITY_DANGER
    if task.status in [HostTask.STATUS_FAILED, HostTask.STATUS_PARTIAL] or task.risk_level == HostTask.RISK_MEDIUM:
        return EventRecord.SEVERITY_WARNING
    return EventRecord.SEVERITY_INFO


def _task_environment_for_event(task):
    values = []

    def append(value):
        text = str(value or '').strip()
        if text and not text.isdigit() and text not in values:
            values.append(text)

    source_context = task.source_context or {}
    selection_filters = task.selection_filters or {}
    for key in ['event_environment', 'event_environment_code', 'resource_event_environment']:
        append(source_context.get(key))
        append(selection_filters.get(key))
    for item in task.target_snapshot or []:
        append(item.get('event_environment') or item.get('event_environment_code'))
    for key in ['resource_environment', 'environment_name', 'environment']:
        append(source_context.get(key))
        append(selection_filters.get(key))
    for item in task.target_snapshot or []:
        append(item.get('environment_name') or item.get('environment') or item.get('env'))
    return values[0] if values else ''


def record_task_center_event(task, action, title, summary='', request=None, actor_username='', source_type=''):
    try:
        from eventwall.models import EventRecord
        from eventwall.services import record_event
    except Exception:
        return None
    return record_event(
        request=request,
        module='ops',
        category='execution',
        action=action,
        title=title,
        summary=summary or task.summary or title,
        result=_task_result_for_event(task.status),
        severity=_task_severity_for_event(task),
        actor_username=actor_username or task.created_by,
        actor_type=EventRecord.ACTOR_USER if (actor_username or task.created_by) != 'system' else EventRecord.ACTOR_SYSTEM,
        source_type=source_type or (EventRecord.SOURCE_SCHEDULER if task.trigger_source == HostTask.TRIGGER_SOURCE_SCHEDULE else ''),
        resource_type='host_task',
        resource_id=task.id,
        resource_name=task.name,
        environment=_task_environment_for_event(task),
        correlation_id=task.correlation_id or f'host-task:{task.id}',
        metadata={
            'event_category': 'task_center',
            'target_type': task.target_type,
            'task_type': task.task_type,
            'trigger_source': task.trigger_source,
            'lifecycle_status': task.lifecycle_status,
            'risk_level': task.risk_level,
            'target_count': task.target_count,
            **(task.source_context or {}),
        },
    )


def mark_stale_running_host_tasks(max_running_seconds=1800):
    threshold = timezone.now() - timezone.timedelta(seconds=max_running_seconds)
    stale_tasks = list(HostTask.objects.filter(status=HostTask.STATUS_RUNNING, started_at__lt=threshold)[:100])
    if not stale_tasks:
        return 0
    now = timezone.now()
    for task in stale_tasks:
        for execution in task.executions.filter(status='running'):
            started_at = execution.started_at or task.started_at or threshold
            execution.status = 'failed'
            execution.error_message = '执行超时：任务执行中状态持续超过 30 分钟，系统已自动标记失败。'
            execution.finished_at = now
            execution.duration_ms = max(int((now - started_at).total_seconds() * 1000), 0)
            execution.save(update_fields=['status', 'error_message', 'finished_at', 'duration_ms'])
        finished_count = task.executions.filter(status__in=['success', 'failed', 'skipped']).count()
        missing_count = max((task.target_count or 0) - finished_count, 0)
        task.success_count = task.executions.filter(status='success').count()
        task.failed_count = task.executions.filter(status='failed').count() + missing_count
        task.skipped_count = task.executions.filter(status='skipped').count()
        task.status = HostTask.STATUS_FAILED
        task.lifecycle_status = HostTask.LIFECYCLE_FAILED
        task.finished_at = now
        task.summary = '执行超时：任务执行中状态持续超过 30 分钟，系统已自动标记失败。'
        task.save(update_fields=['status', 'lifecycle_status', 'success_count', 'failed_count', 'skipped_count', 'finished_at', 'summary'])
    return len(stale_tasks)


def _coerce_positive_int(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _is_placeholder_cluster_name(value):
    return bool(re.fullmatch(r'Cluster\s+\d+', str(value or '').strip(), flags=re.IGNORECASE))


def _find_k8s_cluster_by_name(name):
    name = str(name or '').strip()
    if not name or _is_placeholder_cluster_name(name):
        return None
    return K8sCluster.objects.filter(name=name).first() or K8sCluster.objects.filter(name__icontains=name).first()


def normalize_k8s_execution_target(target):
    item = dict(target or {})
    raw_cluster_id = _coerce_positive_int(item.get('cluster_id') or item.get('cluster'))
    resource_id = _coerce_positive_int(item.get('resource_id') or item.get('task_resource_id'))
    cluster = K8sCluster.objects.filter(pk=raw_cluster_id).first() if raw_cluster_id else None
    resource = None
    if resource_id:
        resource = TaskResource.objects.select_related('environment__event_environment', 'system', 'cluster').filter(
            pk=resource_id,
            resource_type=TaskResource.RESOURCE_K8S,
        ).first()
    if not resource and raw_cluster_id and not cluster:
        resource = TaskResource.objects.select_related('environment__event_environment', 'system', 'cluster').filter(
            pk=raw_cluster_id,
            resource_type=TaskResource.RESOURCE_K8S,
        ).first()
    if resource:
        resource_id = resource.id
        if not cluster:
            cluster = resource.cluster or _find_k8s_cluster_by_name(resource.name)
        item.setdefault('resource_name', resource.name)
        item.setdefault('environment_name', resource.environment.name if resource.environment_id else '')
        event_environment, event_environment_name = _resource_event_environment(resource)
        item.setdefault('event_environment', event_environment)
        item.setdefault('event_environment_name', event_environment_name)
        item.setdefault('system_name', resource.system.name if resource.system_id else '')
    if not cluster:
        cluster = _find_k8s_cluster_by_name(item.get('cluster_name') or item.get('name'))

    cluster_id = cluster.id if cluster else raw_cluster_id
    cluster_name = cluster.name if cluster else (item.get('cluster_name') or (f'Cluster {cluster_id}' if cluster_id else ''))
    return {
        **item,
        'cluster_id': cluster_id,
        'cluster_name': cluster_name,
        'resource_id': resource_id,
        'task_resource_id': resource_id,
        'resource_name': item.get('resource_name') or (resource.name if resource else ''),
        'environment_name': item.get('environment_name') or (resource.environment.name if resource and resource.environment_id else ''),
        'event_environment': item.get('event_environment') or (_resource_event_environment(resource)[0] if resource else ''),
        'event_environment_name': item.get('event_environment_name') or (_resource_event_environment(resource)[1] if resource else ''),
        'system_name': item.get('system_name') or (resource.system.name if resource and resource.system_id else ''),
        'namespace': item.get('namespace') or '',
        'name': item.get('name') or item.get('pod_name') or '',
        'kind': item.get('kind') or item.get('resource_type') or '',
        'container': item.get('container') or '',
        'status': cluster.status if cluster else item.get('status') or 'unknown',
    }


def build_k8s_target_snapshot(targets):
    snapshot = []
    for item in targets:
        normalized = normalize_k8s_execution_target(item)
        cluster_id = normalized.get('cluster_id')
        namespace = normalized.get('namespace') or ''
        name = normalized.get('name') or ''
        kind = normalized.get('kind') or ''
        snapshot.append({
            'id': f'k8s:{cluster_id}:{namespace}:{kind}:{name}',
            'cluster_id': cluster_id,
            'cluster_name': normalized.get('cluster_name') or (f'Cluster {cluster_id}' if cluster_id else ''),
            'resource_id': normalized.get('resource_id'),
            'task_resource_id': normalized.get('resource_id'),
            'resource_name': normalized.get('resource_name') or '',
            'environment_name': normalized.get('environment_name') or '',
            'event_environment': normalized.get('event_environment') or '',
            'event_environment_name': normalized.get('event_environment_name') or '',
            'system_name': normalized.get('system_name') or '',
            'namespace': namespace,
            'name': name,
            'kind': kind,
            'container': normalized.get('container') or '',
            'status': normalized.get('status') or 'unknown',
        })
    return snapshot


def _strip_kubectl_binary(args):
    return args[1:] if args and args[0] == 'kubectl' else args


def _replace_kubectl_stdin_manifest_arg(args, manifest_path):
    replaced = []
    replace_next = False
    for arg in args:
        if replace_next and arg == '-':
            replaced.append(manifest_path)
            replace_next = False
            continue
        replaced.append(arg)
        replace_next = arg in ('-f', '--filename')
    return replaced


def _extract_kubectl_heredoc(command):
    lines = str(command or '').splitlines()
    for index, line in enumerate(lines):
        if '<<' not in line or 'kubectl apply' not in line:
            continue
        command_line, marker = line.split('<<', 1)
        marker = marker.strip().strip('\'"')
        if not marker:
            continue
        manifest_lines = []
        tail_lines = []
        found_end = False
        for body_line in lines[index + 1:]:
            if not found_end and body_line.strip() == marker:
                found_end = True
                continue
            if found_end:
                tail_lines.append(body_line)
            else:
                manifest_lines.append(body_line)
        if not found_end:
            return '', '', []
        return command_line.strip(), '\n'.join(manifest_lines).strip(), tail_lines
    return '', '', []


def _kubectl_command_steps(command, payload=None):
    payload = payload if isinstance(payload, dict) else {}
    command = str(command or '').strip()
    manifest_from_payload = str(payload.get('manifest') or payload.get('k8s_manifest') or '').strip()
    heredoc_command, heredoc_manifest, tail_lines = _extract_kubectl_heredoc(command)
    if heredoc_command:
        steps = [{
            'args': _strip_kubectl_binary(shlex.split(heredoc_command)),
            'manifest': manifest_from_payload or heredoc_manifest,
        }]
        for line in tail_lines:
            line = line.strip()
            if line:
                steps.append({'args': _strip_kubectl_binary(shlex.split(line))})
        return steps

    lines = [line.strip() for line in command.splitlines() if line.strip()]
    if manifest_from_payload and lines and 'kubectl apply' in lines[0] and ' -f -' in f' {lines[0]} ':
        steps = [{'args': _strip_kubectl_binary(shlex.split(lines[0])), 'manifest': manifest_from_payload}]
        steps.extend({'args': _strip_kubectl_binary(shlex.split(line))} for line in lines[1:])
        return steps

    return [{'args': _strip_kubectl_binary(shlex.split(command))}]


def _run_k8s_cluster_command(task, cluster):
    from . import k8s_views

    payload = task.payload or {}
    command = (payload.get('command') or '').strip() or 'kubectl get pods -A | head -20'
    rendered_command = command if command.startswith('kubectl') else f'kubectl {command}'
    if k8s_views._is_demo(cluster):
        return '\n'.join([
            f'$ {rendered_command}',
            f'demo-cluster: {cluster.name}',
            'NAME                           READY   STATUS    RESTARTS   AGE',
            'api-server-5f8b7c6d4-r9p2w    1/1     Running   1          2d',
            'web-frontend-6d9f8b7c5-j2m4n  1/1     Running   0          1d',
        ])
    from .k8s_views import _prepare_kubeconfig

    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as tmp:
        tmp.write(_prepare_kubeconfig(cluster))
        kubeconfig_path = tmp.name
    temporary_paths = [kubeconfig_path]
    try:
        outputs = []
        for step in _kubectl_command_steps(command, payload):
            kubectl_args = list(step['args'])
            manifest = step.get('manifest') or ''
            if manifest:
                with tempfile.NamedTemporaryFile(mode='w', suffix='.manifest.yaml', delete=False, encoding='utf-8') as manifest_file:
                    manifest_file.write(manifest)
                    manifest_path = manifest_file.name
                temporary_paths.append(manifest_path)
                kubectl_args = _replace_kubectl_stdin_manifest_arg(kubectl_args, manifest_path)
            process = subprocess.run(
                ['kubectl', '--kubeconfig', kubeconfig_path, *kubectl_args],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=max(int(task.timeout_seconds or 30), 5),
            )
            output = (process.stdout or '').strip()
            error_output = (process.stderr or '').strip()
            if process.returncode != 0:
                raise RuntimeError(error_output or output or f'kubectl exited with code {process.returncode}')
            if output or error_output:
                outputs.append(output or error_output)
        return output or error_output or '命令执行完成'
    finally:
        for path in temporary_paths:
            try:
                os.unlink(path)
            except OSError:
                pass


def _is_helm_deployment_payload(payload):
    payload = payload if isinstance(payload, dict) else {}
    strategy = str(payload.get('deployment_strategy') or payload.get('strategy') or '').strip().lower()
    command = str(payload.get('command') or '').strip().lower()
    return strategy == 'helm' or command.startswith('helm ')


def _helm_release_name(payload):
    return str(payload.get('release_name') or payload.get('app_name') or payload.get('workload_name') or '').strip()


def _helm_command_text(payload, kubeconfig_path=''):
    payload = payload if isinstance(payload, dict) else {}
    namespace = str(payload.get('namespace') or 'default').strip() or 'default'
    release_name = _helm_release_name(payload) or '<release>'
    chart = str(payload.get('chart') or payload.get('chart_ref') or payload.get('helm_chart') or '<chart>').strip()
    args = ['helm', 'upgrade', '--install', release_name, chart, '--namespace', namespace, '--create-namespace']
    if kubeconfig_path:
        args.extend(['--kubeconfig', kubeconfig_path])
    version = str(payload.get('chart_version') or payload.get('version') or '').strip()
    if version:
        args.extend(['--version', version])
    values_path = str(payload.get('values_file') or '').strip()
    if values_path:
        args.extend(['-f', values_path])
    for item in payload.get('set_values') or []:
        if item:
            args.extend(['--set', str(item)])
    return ' '.join(shlex.quote(item) for item in args)


def _run_k8s_helm_release(task, cluster):
    from . import k8s_views

    payload = task.payload or {}
    namespace = str(payload.get('namespace') or 'default').strip() or 'default'
    release_name = _helm_release_name(payload)
    chart = str(payload.get('chart') or payload.get('chart_ref') or payload.get('helm_chart') or '').strip()
    if not release_name:
        raise RuntimeError('缺少 Helm release_name，请先补充 Release 名称。')
    if not chart:
        raise RuntimeError('缺少 Helm chart，请先查阅软件官方 Helm 文档并补充 chart/repo/values 后再执行。')

    rendered_command = _helm_command_text(payload)
    if k8s_views._is_demo(cluster):
        return '\n'.join([
            f'$ {rendered_command}',
            f'Helm release {release_name} 已部署到 {cluster.name}/{namespace} [演示模式]',
        ])

    helm_bin = shutil.which('helm')
    if not helm_bin:
        raise RuntimeError('当前执行器未安装 Helm 客户端，无法执行 Helm 部署。请先在后端执行环境安装 helm，或改用 manifest/kubectl 路径。')

    from .k8s_views import _prepare_kubeconfig

    temp_paths = []
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as tmp:
        tmp.write(_prepare_kubeconfig(cluster))
        kubeconfig_path = tmp.name
    temp_paths.append(kubeconfig_path)
    try:
        repo_name = str(payload.get('repo_name') or payload.get('helm_repo_name') or '').strip()
        repo_url = str(payload.get('repo_url') or payload.get('helm_repo_url') or '').strip()
        if repo_name and repo_url:
            repo_process = subprocess.run(
                [helm_bin, 'repo', 'add', repo_name, repo_url],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=max(int(task.timeout_seconds or 30), 10),
            )
            if repo_process.returncode != 0:
                raise RuntimeError((repo_process.stderr or repo_process.stdout or '').strip() or 'helm repo add failed')
            update_process = subprocess.run(
                [helm_bin, 'repo', 'update'],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=max(int(task.timeout_seconds or 30), 10),
            )
            if update_process.returncode != 0:
                raise RuntimeError((update_process.stderr or update_process.stdout or '').strip() or 'helm repo update failed')

        args = [helm_bin, 'upgrade', '--install', release_name, chart, '--namespace', namespace, '--create-namespace', '--kubeconfig', kubeconfig_path]
        version = str(payload.get('chart_version') or payload.get('version') or '').strip()
        if version:
            args.extend(['--version', version])
        values_yaml = str(payload.get('values_yaml') or payload.get('values') or '').strip()
        if values_yaml:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.values.yaml', delete=False, encoding='utf-8') as values_file:
                values_file.write(values_yaml)
                values_path = values_file.name
            temp_paths.append(values_path)
            args.extend(['-f', values_path])
        for item in payload.get('set_values') or []:
            if item:
                args.extend(['--set', str(item)])
        process = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=max(int(task.timeout_seconds or 180), 30),
        )
        output = (process.stdout or '').strip()
        error_output = (process.stderr or '').strip()
        if process.returncode != 0:
            raise RuntimeError(error_output or output or f'helm exited with code {process.returncode}')
        return output or error_output or f'Helm release {release_name} 部署完成'
    finally:
        for path in temp_paths:
            try:
                os.unlink(path)
            except OSError:
                pass


def _create_k8s_execution(task, target, status_value, command, output='', error_message='', started_at=None, finished_at=None):
    started_at = started_at or timezone.now()
    finished_at = finished_at or timezone.now()
    return HostTaskExecution.objects.create(
        task=task,
        target_type=HostTask.TARGET_K8S,
        host_name=target.get('cluster_name') or '',
        host_ip='',
        target_id=str(target.get('id') or ''),
        target_name=target.get('name') or target.get('cluster_name') or '',
        target_namespace=target.get('namespace') or '',
        target_kind=target.get('kind') or '',
        status=status_value,
        command=command,
        output=output or '',
        error_message=error_message or '',
        duration_ms=max(int((finished_at - started_at).total_seconds() * 1000), 0),
        started_at=started_at,
        finished_at=finished_at,
    )


def _create_running_k8s_execution(task, target, command):
    return HostTaskExecution.objects.create(
        task=task,
        target_type=HostTask.TARGET_K8S,
        host_name=target.get('cluster_name') or '',
        host_ip='',
        target_id=str(target.get('id') or ''),
        target_name=target.get('name') or target.get('cluster_name') or '',
        target_namespace=target.get('namespace') or '',
        target_kind=target.get('kind') or '',
        status='running',
        command=command,
        output='',
        error_message='',
        started_at=timezone.now(),
    )


def _run_k8s_restart_pod(task, cluster, target):
    from . import k8s_views

    namespace = target.get('namespace') or 'default'
    pod_name = target.get('name') or ''
    if not pod_name:
        raise RuntimeError('缺少 Pod 名称')
    if k8s_views._is_demo(cluster):
        k8s_views._invalidate_cluster_runtime_cache(cluster)
        return f'Pod {pod_name} 正在重启 [演示模式]'
    k8s = k8s_views._get_k8s_client(cluster)
    v1 = k8s.CoreV1Api()
    v1.delete_namespaced_pod(name=pod_name, namespace=namespace)
    k8s_views._invalidate_cluster_runtime_cache(cluster)
    return f'Pod {pod_name} 正在重启'


def _format_service_ports_from_patch(patch_ports):
    ports = []
    for item in patch_ports or []:
        if not isinstance(item, dict):
            continue
        port = item.get('port')
        node_port = item.get('nodePort') or item.get('node_port')
        protocol = item.get('protocol') or 'TCP'
        if not port:
            continue
        ports.append(f"{port}{'->'+str(node_port) if node_port else ''}/{protocol}")
    return ', '.join(ports)


def _enrich_k8s_target_from_payload(task, target):
    item = dict(target or {})
    payload = task.payload or {}
    if task.task_type != HostTask.TASK_K8S_POD_EXEC:
        return item
    resource_kind = str(payload.get('resource_kind') or '').strip().lower()
    if not resource_kind or resource_kind == 'pod':
        return item
    if not item.get('kind') or item.get('kind') == 'cluster':
        item['kind'] = resource_kind
    if not item.get('namespace') and payload.get('namespace'):
        item['namespace'] = payload.get('namespace')
    if not item.get('name'):
        item['name'] = (
            payload.get('service_name')
            or payload.get('workload_name')
            or payload.get('resource_name')
            or ''
        )
    return item


def _run_k8s_service_patch(task, cluster, target):
    from . import k8s_views

    payload = task.payload or {}
    namespace = target.get('namespace') or payload.get('namespace') or 'default'
    service_name = target.get('name') or payload.get('service_name') or ''
    patch = payload.get('patch') if isinstance(payload.get('patch'), dict) else {}
    if not service_name:
        raise RuntimeError('缺少 Service 名称')
    if not patch:
        raise RuntimeError('缺少 Service patch 内容')

    if k8s_views._is_demo(cluster):
        items = k8s_views._get_demo_state(cluster.id, 'services', k8s_views.DEMO_SERVICES)
        for item in items:
            if item.get('name') != service_name or item.get('namespace') != namespace:
                continue
            spec = patch.get('spec') or {}
            if spec.get('type'):
                item['type'] = spec['type']
            if isinstance(spec.get('ports'), list):
                item['ports'] = _format_service_ports_from_patch(spec['ports']) or item.get('ports', '')
            k8s_views._set_demo_state(cluster.id, 'services', items)
            k8s_views._invalidate_cluster_runtime_cache(cluster)
            return f'Service {namespace}/{service_name} 已通过 K8s API 更新 [演示模式]'
        raise RuntimeError(f'未找到 Service：{namespace}/{service_name}')

    k8s = k8s_views._get_k8s_client(cluster)
    v1 = k8s.CoreV1Api()
    v1.patch_namespaced_service(name=service_name, namespace=namespace, body=patch)
    k8s_views._invalidate_cluster_runtime_cache(cluster)
    return f'Service {namespace}/{service_name} 已通过 K8s API 更新'


def _run_k8s_pod_exec(task, cluster, target):
    from . import k8s_views

    payload = task.payload or {}
    command = payload.get('command') or 'pwd'
    if _is_helm_deployment_payload(payload):
        return _run_k8s_helm_release(task, cluster)
    if (payload.get('resource_kind') or target.get('kind') or '').lower() == 'service' and payload.get('patch'):
        return _run_k8s_service_patch(task, cluster, target)
    if str(command).strip().startswith('kubectl') or (payload.get('resource_kind') or target.get('kind') or '').lower() not in ('', 'pod'):
        return _run_k8s_cluster_command(task, cluster)
    if not (target.get('name') or '').strip():
        return _run_k8s_cluster_command(task, cluster)

    namespace = target.get('namespace') or 'default'
    pod_name = target.get('name') or ''
    container = target.get('container') or (task.payload or {}).get('container') or ''
    if not pod_name:
        raise RuntimeError('缺少 Pod 名称')
    if k8s_views._is_demo(cluster):
        return '\n'.join([
            f'$ {command}',
            f'demo-exec on {pod_name} ({namespace})',
            'uid=1000 gid=1000 groups=1000',
            '/app',
        ])
    from kubernetes.stream import stream

    k8s = k8s_views._get_k8s_client(cluster)
    v1 = k8s.CoreV1Api()
    kwargs = {
        'name': pod_name,
        'namespace': namespace,
        'command': ['/bin/sh', '-lc', command],
        'stderr': True,
        'stdin': False,
        'stdout': True,
        'tty': False,
    }
    if container:
        kwargs['container'] = container
    return stream(v1.connect_get_namespaced_pod_exec, **kwargs) or ''


def _run_k8s_scale_workload(task, cluster, target):
    from . import k8s_views

    payload = task.payload or {}
    namespace = target.get('namespace') or 'default'
    name = target.get('name') or ''
    workload_type = (payload.get('workload_type') or target.get('kind') or '').lower()
    replicas = int(payload.get('replicas'))
    if workload_type not in ('deployment', 'statefulset'):
        raise RuntimeError('仅支持 Deployment 或 StatefulSet 伸缩')
    if not name:
        raise RuntimeError('缺少工作负载名称')
    if k8s_views._is_demo(cluster):
        cache_name = 'deployments' if workload_type == 'deployment' else 'statefulsets'
        defaults = k8s_views.DEMO_DEPLOYMENTS if workload_type == 'deployment' else k8s_views.DEMO_STATEFULSETS
        items = k8s_views._get_demo_state(cluster.id, cache_name, defaults)
        for item in items:
            if item.get('name') == name and item.get('namespace') == namespace:
                item['replicas'] = replicas
                item['ready_replicas'] = min(item.get('ready_replicas', 0), replicas)
                if workload_type == 'deployment':
                    item['available_replicas'] = min(item.get('available_replicas', item.get('ready_replicas', 0)), replicas)
                k8s_views._set_demo_state(cluster.id, cache_name, items)
                k8s_views._invalidate_cluster_runtime_cache(cluster)
                return f'{name} scaled to {replicas} replicas [演示模式]'
        raise RuntimeError(f'未找到资源：{workload_type}/{namespace}/{name}')
    k8s = k8s_views._get_k8s_client(cluster)
    apps_v1 = k8s.AppsV1Api()
    body = {'spec': {'replicas': replicas}}
    if workload_type == 'deployment':
        apps_v1.patch_namespaced_deployment_scale(name=name, namespace=namespace, body=body)
    else:
        apps_v1.patch_namespaced_stateful_set_scale(name=name, namespace=namespace, body=body)
    k8s_views._invalidate_cluster_runtime_cache(cluster)
    return f'{name} scaled to {replicas} replicas'


def _k8s_command_text(task, target):
    payload = task.payload or {}
    if task.task_type == HostTask.TASK_K8S_RESTART_POD:
        return f"kubectl delete pod {target.get('name')} -n {target.get('namespace') or 'default'}"
    if task.task_type == HostTask.TASK_K8S_POD_EXEC:
        if _is_helm_deployment_payload(payload):
            return _helm_command_text(payload)
        command = str(payload.get('command') or '').strip()
        target_kind = (payload.get('resource_kind') or target.get('kind') or '').lower()
        if not (target.get('name') or '').strip() or command.startswith('kubectl') or target_kind not in ('', 'pod'):
            if command.startswith('kubectl'):
                return command
            return f"kubectl {command}".strip()
        return f"kubectl exec {target.get('name')} -n {target.get('namespace') or 'default'} -- {payload.get('command') or ''}"
    if task.task_type == HostTask.TASK_K8S_SCALE_WORKLOAD:
        return f"kubectl scale {payload.get('workload_type')}/{target.get('name')} -n {target.get('namespace') or 'default'} --replicas={payload.get('replicas')}"
    return task.task_type


def _run_single_k8s_task(task, target):
    target = _enrich_k8s_target_from_payload(task, target)
    target = normalize_k8s_execution_target(target)
    started_at = timezone.now()
    monotonic_started = time.monotonic()
    command = _k8s_command_text(task, target)
    execution = _create_running_k8s_execution(task, target, command)
    try:
        if not target.get('cluster_id'):
            raise RuntimeError('缺少 K8s 集群')
        cluster = K8sCluster.objects.filter(pk=target.get('cluster_id')).first()
        if not cluster:
            raise RuntimeError(f"未找到 K8s 集群：{target.get('cluster_name') or target.get('cluster_id')}")
        if task.task_type == HostTask.TASK_K8S_RESTART_POD:
            output = _run_k8s_restart_pod(task, cluster, target)
        elif task.task_type == HostTask.TASK_K8S_POD_EXEC:
            output = _run_k8s_pod_exec(task, cluster, target)
        elif task.task_type == HostTask.TASK_K8S_SCALE_WORKLOAD:
            output = _run_k8s_scale_workload(task, cluster, target)
        else:
            raise RuntimeError('不支持的 K8s 任务类型')
        return _finish_execution(execution, 'success', output=output, started_at=started_at, monotonic_started=monotonic_started)
    except Exception as exc:
        return _finish_execution(execution, 'failed', error_message=str(exc), started_at=started_at, monotonic_started=monotonic_started)


def execute_k8s_task(task, targets):
    targets = [_enrich_k8s_target_from_payload(task, item) for item in targets]
    task.refresh_from_db()
    task.status = HostTask.STATUS_RUNNING
    task.lifecycle_status = HostTask.LIFECYCLE_RUNNING
    task.started_at = timezone.now()
    task.target_type = HostTask.TARGET_K8S
    task.execution_mode = HostTask.EXECUTION_MODE_K8S_API
    task.target_count = len(targets)
    task.target_snapshot = build_k8s_target_snapshot(targets)
    task.success_count = 0
    task.failed_count = 0
    task.skipped_count = 0
    task.summary = '任务执行中，正在通过 K8s API 处理目标资源'
    task.save(update_fields=['status', 'lifecycle_status', 'started_at', 'target_type', 'execution_mode', 'target_count', 'target_snapshot', 'success_count', 'failed_count', 'skipped_count', 'summary'])

    stop_on_error = task.execution_strategy == HostTask.STRATEGY_STOP_ON_ERROR
    canceled = False
    halted = False
    failure_targets = []
    snapshot = task.target_snapshot or []
    for index, target in enumerate(snapshot):
        task.refresh_from_db(fields=['cancel_requested'])
        if task.cancel_requested:
            canceled = True
            for remaining in snapshot[index:]:
                _create_k8s_execution(task, remaining, 'skipped', _k8s_command_text(task, remaining), error_message='任务已收到终止请求，剩余 K8s 目标已跳过')
                task.skipped_count += 1
            break
        if halted:
            _create_k8s_execution(task, target, 'skipped', _k8s_command_text(task, target), error_message='前序目标执行失败，策略为失败即停，当前 K8s 目标已跳过')
            task.skipped_count += 1
            continue
        execution = _run_single_k8s_task(task, target)
        if execution.status == 'success':
            task.success_count += 1
        else:
            task.failed_count += 1
            failure_targets.append(execution.target_name or execution.host_name)
            if stop_on_error:
                halted = True

    task.finished_at = timezone.now()
    if canceled:
        task.status = HostTask.STATUS_CANCELED
    elif task.failed_count and task.success_count:
        task.status = HostTask.STATUS_PARTIAL
    elif task.failed_count:
        task.status = HostTask.STATUS_FAILED
    else:
        task.status = HostTask.STATUS_SUCCESS
    task.lifecycle_status = {
        HostTask.STATUS_SUCCESS: HostTask.LIFECYCLE_SUCCESS,
        HostTask.STATUS_PARTIAL: HostTask.LIFECYCLE_PARTIAL,
        HostTask.STATUS_FAILED: HostTask.LIFECYCLE_FAILED,
        HostTask.STATUS_CANCELED: HostTask.LIFECYCLE_CANCELED,
    }.get(task.status, HostTask.LIFECYCLE_PENDING_EXECUTION)
    summary = f'共 {task.target_count} 个 K8s 目标，成功 {task.success_count}，失败 {task.failed_count}'
    if task.skipped_count:
        summary += f'，跳过 {task.skipped_count}'
    if failure_targets:
        summary += f'，失败目标：{", ".join(failure_targets[:5])}'
    if canceled:
        summary += '，任务已按申请终止'
    task.summary = summary[:255]
    task.save(update_fields=['status', 'lifecycle_status', 'success_count', 'failed_count', 'skipped_count', 'finished_at', 'summary'])
    record_task_center_event(task, 'task_finished', '任务中心执行完成')
    return task


def execute_host_task(task, hosts):
    hosts = normalize_host_execution_targets(hosts)
    task.refresh_from_db()
    requested_mode = task.execution_mode or HostTask.EXECUTION_MODE_SSH
    active_mode = requested_mode
    fallback_message = ''
    task.status = HostTask.STATUS_RUNNING
    task.lifecycle_status = HostTask.LIFECYCLE_RUNNING
    task.started_at = timezone.now()
    task.target_count = len(hosts)
    task.target_snapshot = build_host_target_snapshot(hosts)
    task.success_count = 0
    task.failed_count = 0
    task.skipped_count = 0
    if requested_mode == HostTask.EXECUTION_MODE_ANSIBLE:
        task.summary = '\u4efb\u52a1\u6267\u884c\u4e2d\uff0c\u6b63\u5728\u901a\u8fc7 Ansible \u8fde\u63a5\u76ee\u6807\u4e3b\u673a'
    else:
        task.summary = '\u4efb\u52a1\u6267\u884c\u4e2d\uff0c\u6b63\u5728\u8fde\u63a5\u76ee\u6807\u4e3b\u673a'
    task.save(
        update_fields=[
            'status',
            'lifecycle_status',
            'started_at',
            'target_count',
            'target_snapshot',
            'success_count',
            'failed_count',
            'skipped_count',
            'summary',
        ]
    )

    failure_hosts = []
    stop_on_error = task.execution_strategy == HostTask.STRATEGY_STOP_ON_ERROR
    halted = False
    canceled = False

    for index, host in enumerate(hosts):
        task.refresh_from_db(fields=['cancel_requested'])
        if task.cancel_requested:
            canceled = True
            for remaining_host in hosts[index:]:
                _create_skipped_execution(task, remaining_host, '\u4efb\u52a1\u5df2\u6536\u5230\u7ec8\u6b62\u8bf7\u6c42\uff0c\u5269\u4f59\u4e3b\u673a\u5df2\u8df3\u8fc7\u6267\u884c')
            break

        if halted:
            _create_skipped_execution(task, host, '\u524d\u5e8f\u4e3b\u673a\u6267\u884c\u5931\u8d25\uff0c\u7b56\u7565\u4e3a\u5931\u8d25\u5373\u505c\uff0c\u5f53\u524d\u4e3b\u673a\u5df2\u8df3\u8fc7')
            continue

        try:
            execution = _run_single_task(task, host, active_mode)
        except AnsibleControllerError as exc:
            if (
                requested_mode == HostTask.EXECUTION_MODE_ANSIBLE
                and task.task_type != HostTask.TASK_RUN_PLAYBOOK
                and allow_ansible_fallback_to_ssh()
            ):
                active_mode = HostTask.EXECUTION_MODE_SSH
                fallback_message = str(exc)
                execution = _run_single_task(task, host, active_mode)
            else:
                execution = _create_failed_execution(task, host, _build_command_text(task), str(exc))
        except ValueError as exc:
            execution = _create_failed_execution(task, host, _build_command_text(task), str(exc))
        if execution.status == 'success':
            task.success_count += 1
        else:
            task.failed_count += 1
            failure_hosts.append(execution.host_name)
            if stop_on_error:
                halted = True

    task.finished_at = timezone.now()
    if canceled:
        task.status = HostTask.STATUS_CANCELED
    elif task.failed_count and task.success_count:
        task.status = HostTask.STATUS_PARTIAL
    elif task.failed_count:
        task.status = HostTask.STATUS_FAILED
    else:
        task.status = HostTask.STATUS_SUCCESS
    task.lifecycle_status = {
        HostTask.STATUS_SUCCESS: HostTask.LIFECYCLE_SUCCESS,
        HostTask.STATUS_PARTIAL: HostTask.LIFECYCLE_PARTIAL,
        HostTask.STATUS_FAILED: HostTask.LIFECYCLE_FAILED,
        HostTask.STATUS_CANCELED: HostTask.LIFECYCLE_CANCELED,
    }.get(task.status, HostTask.LIFECYCLE_PENDING_EXECUTION)

    summary = f'\u5171 {task.target_count} \u53f0\uff0c\u6210\u529f {task.success_count}\uff0c\u5931\u8d25 {task.failed_count}'
    if task.skipped_count:
        summary += f'\uff0c\u8df3\u8fc7 {task.skipped_count}'
    if failure_hosts:
        summary += f'\uff0c\u5931\u8d25\u4e3b\u673a\uff1a{", ".join(failure_hosts[:5])}'
        if len(failure_hosts) > 5:
            summary += ' ...'
    if canceled:
        summary += '\uff0c\u4efb\u52a1\u5df2\u6309\u7533\u8bf7\u7ec8\u6b62'
    if requested_mode == HostTask.EXECUTION_MODE_ANSIBLE:
        if active_mode == HostTask.EXECUTION_MODE_SSH:
            summary += '\uff0cAnsible \u4e0d\u53ef\u7528\u5df2\u56de\u9000 SSH'
            if fallback_message:
                summary += f' ({fallback_message[:48]})'
        else:
            summary += '\uff0c\u6267\u884c\u65b9\u5f0f\uff1aAnsible'
    task.summary = summary[:255]
    task.save(
        update_fields=[
            'status',
            'lifecycle_status',
            'success_count',
            'failed_count',
            'skipped_count',
            'finished_at',
            'summary',
        ]
    )
    if task.schedule_id:
        from .host_task_schedules import sync_schedule_after_task

        sync_schedule_after_task(task)
    record_task_center_event(task, 'task_finished', '任务中心执行完成')
    return task


def should_run_async():
    configured = getattr(settings, 'HOST_TASK_RUN_ASYNC', None)
    if configured is not None:
        return configured
    return 'test' not in sys.argv


def _execute_host_task_thread(task_id, host_refs):
    close_old_connections()
    try:
        task = HostTask.objects.get(pk=task_id)
        hosts = resolve_host_source_refs(host_refs)
        execute_host_task(task, hosts)
    finally:
        close_old_connections()
        with _TASK_THREADS_LOCK:
            _TASK_THREADS.pop(task_id, None)


def _execute_k8s_task_thread(task_id, targets):
    close_old_connections()
    try:
        task = HostTask.objects.get(pk=task_id)
        execute_k8s_task(task, targets)
    except Exception as exc:
        HostTask.objects.filter(pk=task_id).update(
            status=HostTask.STATUS_FAILED,
            lifecycle_status=HostTask.LIFECYCLE_FAILED,
            failed_count=1,
            finished_at=timezone.now(),
            summary=f'K8s 任务执行异常：{str(exc)[:180]}',
        )
    finally:
        close_old_connections()
        with _TASK_THREADS_LOCK:
            _TASK_THREADS.pop(task_id, None)


def start_host_task(task, hosts):
    host_list = normalize_host_execution_targets(hosts)
    task.target_count = len(host_list)
    task.lifecycle_status = HostTask.LIFECYCLE_PENDING_EXECUTION
    task.target_snapshot = build_host_target_snapshot(host_list)
    if should_run_async():
        if task.execution_mode == HostTask.EXECUTION_MODE_ANSIBLE:
            task.summary = '\u4efb\u52a1\u5df2\u5165\u961f\uff0c\u7b49\u5f85\u540e\u53f0\u901a\u8fc7 Ansible \u6267\u884c'
        else:
            task.summary = '\u4efb\u52a1\u5df2\u5165\u961f\uff0c\u7b49\u5f85\u540e\u53f0\u6267\u884c'
        task.save(update_fields=['target_count', 'target_snapshot', 'lifecycle_status', 'summary'])
        host_refs = [_host_source_ref(host) for host in host_list]
        worker = threading.Thread(target=_execute_host_task_thread, args=(task.id, host_refs), daemon=True)
        with _TASK_THREADS_LOCK:
            _TASK_THREADS[task.id] = worker
        worker.start()
        return task

    execute_host_task(task, host_list)
    return task


def start_k8s_task(task, targets):
    target_list = [_enrich_k8s_target_from_payload(task, item) for item in targets]
    task.target_type = HostTask.TARGET_K8S
    task.execution_mode = HostTask.EXECUTION_MODE_K8S_API
    task.target_count = len(target_list)
    task.lifecycle_status = HostTask.LIFECYCLE_PENDING_EXECUTION
    task.target_snapshot = build_k8s_target_snapshot(target_list)
    if should_run_async():
        task.summary = '任务已入队，等待后台通过 K8s API 执行'
        task.save(update_fields=['target_type', 'execution_mode', 'target_count', 'target_snapshot', 'lifecycle_status', 'summary'])
        worker = threading.Thread(target=_execute_k8s_task_thread, args=(task.id, target_list), daemon=True)
        with _TASK_THREADS_LOCK:
            _TASK_THREADS[task.id] = worker
        worker.start()
        return task

    execute_k8s_task(task, target_list)
    return task
