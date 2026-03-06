"""
SSH 部署执行器
通过 paramiko 连接远程主机，上传 docker-compose.yml 并执行部署/管理命令
"""
import logging
import re
import paramiko

logger = logging.getLogger(__name__)

DEPLOY_BASE = '/opt/agdevops'


def _render_template(template_str, context):
    """简易模板渲染：将 {{key}} 替换为 context[key]"""
    result = template_str
    for key, value in context.items():
        result = result.replace('{{' + key + '}}', str(value))
    # 清理未替换的占位符
    result = re.sub(r'\{\{[^}]+\}\}', '', result)
    return result


def _get_ssh_client(host):
    """建立 SSH 连接"""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host.ip_address,
        port=getattr(host, 'ssh_port', 22) or 22,
        username=getattr(host, 'ssh_user', 'root') or 'root',
        password=getattr(host, 'ssh_password', '') or None,
        timeout=15,
    )
    return client


def _ssh_exec(client, cmd):
    """执行远程命令并返回 (exit_code, stdout, stderr)"""
    stdin, stdout, stderr = client.exec_command(cmd, timeout=120)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    return exit_code, out, err


def deploy_service(deployment):
    """
    部署服务到远程主机
    1. 渲染 docker-compose.yml
    2. SSH 上传文件
    3. 执行 docker-compose up -d
    """
    template = deployment.template
    host = deployment.host
    service_dir = f'{DEPLOY_BASE}/{template.name.lower().replace(" ", "_")}'
    deployment.deploy_dir = service_dir
    deployment.status = 'deploying'
    deployment.deploy_log = ''
    deployment.save(update_fields=['status', 'deploy_dir', 'deploy_log'])

    # 构建渲染上下文
    context = {'version': deployment.version}
    context.update(deployment.env_config)

    compose_content = _render_template(template.docker_compose_template, context)

    log_lines = []
    try:
        client = _get_ssh_client(host)
        log_lines.append(f'[✓] SSH 连接成功: {host.ip_address}:{getattr(host, "ssh_port", 22)}')

        # 创建目录
        code, out, err = _ssh_exec(client, f'mkdir -p {service_dir}')
        log_lines.append(f'[✓] 创建目录: {service_dir}')

        # 上传 docker-compose.yml
        sftp = client.open_sftp()
        compose_path = f'{service_dir}/docker-compose.yml'
        with sftp.file(compose_path, 'w') as f:
            f.write(compose_content)
        sftp.close()
        log_lines.append(f'[✓] 上传 docker-compose.yml')

        # 执行 docker-compose up -d
        code, out, err = _ssh_exec(client, f'cd {service_dir} && docker-compose up -d 2>&1 || docker compose up -d 2>&1')
        log_lines.append(f'[CMD] docker-compose up -d')
        if out.strip():
            log_lines.append(out.strip())
        if err.strip():
            log_lines.append(err.strip())

        if code == 0:
            deployment.status = 'running'
            log_lines.append('[✓] 部署成功！')
        else:
            deployment.status = 'failed'
            log_lines.append(f'[✗] 部署失败，退出码: {code}')

        client.close()

    except Exception as e:
        deployment.status = 'failed'
        log_lines.append(f'[✗] 部署异常: {str(e)}')
        logger.exception('deploy_service error')

    deployment.deploy_log = '\n'.join(log_lines)
    deployment.save(update_fields=['status', 'deploy_log'])
    return deployment


def stop_service(deployment):
    """停止服务"""
    host = deployment.host
    service_dir = deployment.deploy_dir
    if not service_dir:
        deployment.deploy_log += '\n[✗] 无部署目录信息，无法停止'
        deployment.save(update_fields=['deploy_log'])
        return deployment

    try:
        client = _get_ssh_client(host)
        code, out, err = _ssh_exec(client, f'cd {service_dir} && docker-compose stop 2>&1 || docker compose stop 2>&1')
        deployment.status = 'stopped'
        deployment.deploy_log += f'\n[✓] 服务已停止\n{out}{err}'
        client.close()
    except Exception as e:
        deployment.deploy_log += f'\n[✗] 停止失败: {str(e)}'

    deployment.save(update_fields=['status', 'deploy_log'])
    return deployment


def start_service(deployment):
    """启动已停止的服务"""
    host = deployment.host
    service_dir = deployment.deploy_dir

    try:
        client = _get_ssh_client(host)
        code, out, err = _ssh_exec(client, f'cd {service_dir} && docker-compose start 2>&1 || docker compose start 2>&1')
        deployment.status = 'running'
        deployment.deploy_log += f'\n[✓] 服务已启动\n{out}{err}'
        client.close()
    except Exception as e:
        deployment.deploy_log += f'\n[✗] 启动失败: {str(e)}'

    deployment.save(update_fields=['status', 'deploy_log'])
    return deployment


def remove_service(deployment):
    """卸载服务"""
    host = deployment.host
    service_dir = deployment.deploy_dir

    try:
        client = _get_ssh_client(host)
        code, out, err = _ssh_exec(client, f'cd {service_dir} && docker-compose down -v 2>&1 || docker compose down -v 2>&1')
        code2, out2, err2 = _ssh_exec(client, f'rm -rf {service_dir}')
        deployment.deploy_log += f'\n[✓] 服务已卸载并清理\n{out}{err}'
        client.close()
    except Exception as e:
        deployment.deploy_log += f'\n[✗] 卸载失败: {str(e)}'
        deployment.save(update_fields=['deploy_log'])
        return deployment

    deployment.save(update_fields=['deploy_log'])
    deployment.delete()
    return None


def get_service_logs(deployment, tail=100):
    """获取容器日志"""
    host = deployment.host
    service_dir = deployment.deploy_dir

    try:
        client = _get_ssh_client(host)
        code, out, err = _ssh_exec(client, f'cd {service_dir} && docker-compose logs --tail={tail} 2>&1 || docker compose logs --tail={tail} 2>&1')
        client.close()
        return out or err
    except Exception as e:
        return f'获取日志失败: {str(e)}'
