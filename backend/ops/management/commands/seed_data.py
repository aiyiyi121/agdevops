import json
import random
from datetime import timedelta

from django.db import connection
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from cmdb.demo_seed import BIZ_DATA, BIZ_INFRA, seed_cmdb_demo
from eventwall.models import EventRecord
from eventwall.services import record_event
from marketplace.models import ServiceDeployment, ServiceTemplate
from ops.deployer import sync_current_deployments_to_cmdb
from sqlaudit.models import DataSource, QueryOrder, SqlCheckResult, SqlOrder
from ops.models import (
    Alert,
    Deployment,
    DeploymentApprovalFlow,
    DeploymentApprovalNode,
    DeploymentApprovalStep,
    DockerHost,
    Host,
    HostTask,
    HostTaskExecution,
    HostTaskSchedule,
    HostTaskScheduleExecution,
    HostTaskTemplate,
    K8sCluster,
    LogEntry,
)


SYSTEM_TRADE = '交易系统'


def seed_eventwall_unmatched_environment_demo(stdout):
    stdout.write('正在生成事件环境未映射演示数据...')
    EventRecord.objects.filter(metadata__demo_unmatched_environment_ui=True).delete()
    demo_events = [
        {
            'module': 'ops',
            'category': 'execution',
            'action': 'task_finished',
            'title': 'Demo：任务中心未映射环境',
            'summary': '任务中心事件携带了支付生产环境，但事件中心环境暂未配置该标识或别名。',
            'resource_type': 'host_task',
            'resource_id': 'demo-unmatched-task-1',
            'resource_name': '支付生产巡检任务',
            'business_line': '支付',
            'environment': '支付生产环境',
            'metadata': {'event_category': 'task_center'},
        },
        {
            'module': 'ops',
            'category': 'execution',
            'action': 'task_finished',
            'title': 'Demo：任务中心未映射环境 2',
            'summary': '任务中心事件再次携带支付生产环境，用于展示未映射环境聚合计数。',
            'resource_type': 'host_task',
            'resource_id': 'demo-unmatched-task-2',
            'resource_name': '支付生产发布后检查',
            'business_line': '支付',
            'environment': '支付生产环境',
            'metadata': {'event_category': 'task_center'},
        },
        {
            'module': 'ops',
            'category': 'workflow',
            'action': 'create_ticket',
            'title': 'Demo：工单系统未映射环境',
            'summary': '工单事件携带了订单预发环境，但事件中心环境暂未配置该标识或别名。',
            'resource_type': 'transaction_ticket',
            'resource_id': 'demo-unmatched-ticket-1',
            'resource_name': '订单预发变更工单',
            'business_line': '订单',
            'environment': '订单预发环境',
            'metadata': {'event_category': 'ops_transaction'},
        },
    ]
    for index, payload in enumerate(demo_events):
        metadata = {
            **payload.pop('metadata'),
            'demo_unmatched_environment_ui': True,
        }
        record_event(
            source_type=EventRecord.SOURCE_SEED,
            actor_type=EventRecord.ACTOR_SYSTEM,
            actor_username='system',
            actor_display='System',
            is_demo=True,
            occurred_at=timezone.now() - timedelta(minutes=15 + index),
            metadata=metadata,
            **payload,
        )


def seed_marketplace_demo(stdout, hosts):
    stdout.write('正在生成工具市场演示数据...')
    call_command('seed_templates')
    ServiceDeployment.objects.all().delete()

    cluster_main, _ = K8sCluster.objects.update_or_create(
        name='demo-k8s-cluster',
        defaults={
            'api_server': 'https://demo-k8s-cluster.example.local:6443',
            'kubeconfig': 'demo',
            'status': 'connected',
            'description': '工具市场演示 Kubernetes 集群',
        },
    )
    cluster_dev, _ = K8sCluster.objects.update_or_create(
        name='dev-k8s-cluster',
        defaults={
            'api_server': 'https://dev-k8s-cluster.example.local:6443',
            'kubeconfig': 'demo',
            'status': 'connected',
            'description': '开发环境演示 Kubernetes 集群',
        },
    )

    template_map = {
        item.name: item
        for item in ServiceTemplate.objects.filter(
            name__in=['Redis', 'MongoDB', 'Nginx', 'Grafana', 'Java', 'Python', 'Node.js']
        )
    }
    host_map = {host.hostname: host for host in hosts}
    host_list = list(hosts)

    def resolve_host(*preferred_names, fallback_index=0):
        for name in preferred_names:
            host = host_map.get(name)
            if host:
                return host
        if 0 <= fallback_index < len(host_list):
            return host_list[fallback_index]
        return host_list[0] if host_list else None

    deployments = [
        {
            'template': template_map['Redis'],
            'deploy_mode': 'docker_compose',
            'host': resolve_host('feature-x-dev-ecs', 'redis-01', fallback_index=0),
            'version': '7.0',
            'status': 'running',
            'env_config': {'port': '6379', 'password': 'redis@2024'},
            'deployer': 'ops-demo',
            'deploy_dir': '/opt/sxdevops/redis',
            'deploy_log': '[INFO] Docker Compose 部署成功',
        },
        {
            'template': template_map['MongoDB'],
            'deploy_mode': 'docker_compose',
            'host': resolve_host('legacy-data-sync', 'db-master', fallback_index=1),
            'version': '7.0',
            'status': 'stopped',
            'env_config': {'port': '27017', 'root_username': 'admin', 'root_password': 'mongo@2024'},
            'deployer': 'admin',
            'deploy_dir': '/opt/sxdevops/mongodb',
            'deploy_log': '[INFO] MongoDB 已部署，当前处于停止状态',
        },
        {
            'template': template_map['Nginx'],
            'deploy_mode': 'docker_compose',
            'host': resolve_host('order-api-ecs-01', 'nginx-lb-01', fallback_index=2),
            'version': '1.25',
            'status': 'failed',
            'env_config': {'http_port': '80', 'https_port': '443'},
            'deployer': 'zhangsan',
            'deploy_dir': '/opt/sxdevops/nginx',
            'deploy_log': '[ERROR] 端口 80 被占用，部署失败',
        },
        {
            'template': template_map['Grafana'],
            'deploy_mode': 'k8s',
            'cluster': cluster_main,
            'namespace': 'monitoring',
            'release_name': 'grafana-demo',
            'replicas': 1,
            'version': '10.3',
            'status': 'running',
            'env_config': {'port': '3000'},
            'deployer': 'ops-demo',
            'deploy_dir': 'k8s://demo-k8s-cluster/monitoring/grafana-demo',
            'deploy_log': '[INFO] Grafana K8s 部署成功',
        },
        {
            'template': template_map['Java'],
            'deploy_mode': 'k8s',
            'cluster': cluster_dev,
            'namespace': 'devenv',
            'release_name': 'java-devbox',
            'replicas': 1,
            'version': '3.9.9-eclipse-temurin-21',
            'status': 'running',
            'env_config': {'workspace': '/workspace'},
            'deployer': 'dev-demo',
            'deploy_dir': 'k8s://dev-k8s-cluster/devenv/java-devbox',
            'deploy_log': '[INFO] Java 开发环境已创建',
        },
        {
            'template': template_map['Python'],
            'deploy_mode': 'k8s',
            'cluster': cluster_dev,
            'namespace': 'devenv',
            'release_name': 'python-devbox',
            'replicas': 1,
            'version': '3.12',
            'status': 'running',
            'env_config': {'workspace': '/workspace'},
            'deployer': 'dev-demo',
            'deploy_dir': 'k8s://dev-k8s-cluster/devenv/python-devbox',
            'deploy_log': '[INFO] Python 开发环境已创建',
        },
        {
            'template': template_map['Node.js'],
            'deploy_mode': 'k8s',
            'cluster': cluster_dev,
            'namespace': 'frontend-dev',
            'release_name': 'nodejs-devbox',
            'replicas': 1,
            'version': '20',
            'status': 'deploying',
            'env_config': {'workspace': '/workspace'},
            'deployer': 'dev-demo',
            'deploy_dir': 'k8s://dev-k8s-cluster/frontend-dev/nodejs-devbox',
            'deploy_log': '[INFO] 正在拉取 node:20 镜像',
        },
    ]

    for item in deployments:
        create_marketplace_deployment(item)


def create_marketplace_deployment(item):
    columns = set()
    with connection.cursor() as cursor:
        table_description = connection.introspection.get_table_description(
            cursor,
            ServiceDeployment._meta.db_table,
        )
        columns = {column.name for column in table_description}

    now = timezone.now()
    status_value = item.get('status', 'pending')
    payload = {
        'template_id': item['template'].id,
        'deploy_mode': item.get('deploy_mode', 'docker_compose'),
        'host_id': item['host'].id if item.get('host') else None,
        'cluster_id': item['cluster'].id if item.get('cluster') else None,
        'namespace': item.get('namespace', ''),
        'release_name': item.get('release_name', ''),
        'replicas': item.get('replicas', 1),
        'version': item['version'],
        'status': status_value,
        'env_config': json.dumps(item.get('env_config', {}), ensure_ascii=False),
        'deploy_log': item.get('deploy_log', ''),
        'deployer': item.get('deployer', 'admin'),
        'deploy_dir': item.get('deploy_dir', ''),
        'created_at': now,
        'updated_at': now,
        'action_type': 'deploy',
        'approval_comment': '',
        'approval_status': 'approved',
        'approved_at': now,
        'approver': item.get('deployer', 'admin'),
        'change_summary': '工具市场演示数据',
        'executed_at': now,
        'execution_count': 1,
        'finished_at': now,
        'is_current': status_value in {'running', 'stopped'},
        'submitter': item.get('deployer', 'admin'),
        'previous_success_id': None,
        'rerun_source_id': None,
        'rollback_source_id': None,
    }

    insert_columns = [name for name in payload.keys() if name in columns]
    placeholders = ', '.join(['%s'] * len(insert_columns))
    sql = f'INSERT INTO marketplace_servicedeployment ({", ".join(insert_columns)}) VALUES ({placeholders})'
    values = [payload[name] for name in insert_columns]
    with connection.cursor() as cursor:
        cursor.execute(sql, values)


def seed_sqlaudit_demo(stdout):
    stdout.write('正在生成 SQL 审计演示数据...')
    SqlCheckResult.objects.all().delete()
    QueryOrder.objects.all().delete()
    SqlOrder.objects.all().delete()
    DataSource.objects.all().delete()

    ds_order = DataSource.objects.create(
        name='trade-primary',
        db_type='mysql',
        host='10.10.1.20',
        port=3306,
        user='audit_reader',
        password='demo-secret',
        charset='utf8mb4',
        remark='订单核心库，供 SQL 审计演示使用',
        is_active=True,
    )
    ds_member = DataSource.objects.create(
        name='member-archive',
        db_type='polardb',
        host='10.20.8.18',
        port=3306,
        user='archive_reader',
        password='demo-secret',
        charset='utf8mb4',
        remark='会员归档库，供只读查询演示使用',
        is_active=True,
    )

    order_pending = SqlOrder.objects.create(
        title='订单表增加灰度索引',
        datasource=ds_order,
        database='trade_prod',
        sql_type='DDL',
        sql_content='ALTER TABLE order_main ADD INDEX idx_order_gray_status (gray_status, updated_at);',
        status='pending',
        submitter='dev_demo',
    )
    SqlCheckResult.objects.create(
        order=order_pending,
        level='warning',
        rule_name='DDLReview',
        message='生产 DDL 需要在低峰窗口执行，并提前准备回滚方案',
        line_no=1,
    )

    order_done = SqlOrder.objects.create(
        title='修复库存同步状态',
        datasource=ds_order,
        database='trade_prod',
        sql_type='DML',
        sql_content='UPDATE stock_job SET sync_status = 1 WHERE sync_status = 0 AND updated_at < NOW() - INTERVAL 10 MINUTE;',
        status='executed',
        submitter='dev_demo',
        reviewer='audit_demo',
        review_comment='已确认影响范围，并在低峰执行',
        reviewed_at=timezone.now() - timedelta(hours=6),
        execute_log='[INFO] Statement executed successfully',
        affected_rows=42,
        duration_ms=186,
        executed_at=timezone.now() - timedelta(hours=6),
    )
    SqlCheckResult.objects.create(
        order=order_done,
        level='info',
        rule_name='SafeWhere',
        message='检测到 where 条件，执行风险可控',
        line_no=1,
    )

    QueryOrder.objects.create(
        datasource=ds_member,
        database='member_archive',
        sql_content='SELECT region, COUNT(*) AS total FROM member_login_log GROUP BY region ORDER BY total DESC LIMIT 10;',
        submitter='audit_demo',
        result_count=10,
        duration_ms=84,
    )


def _create_approval_steps(deployment, statuses):
    nodes = list(deployment.approval_flow.nodes.all().order_by('order'))
    steps = []
    for index, node in enumerate(nodes):
        status_value = statuses[index]
        previous_pending = any(item == 'pending' for item in statuses[:index])
        steps.append(
            DeploymentApprovalStep(
                deployment=deployment,
                flow=deployment.approval_flow,
                node_name=node.name,
                node_order=node.order,
                approver_type=node.approver_type,
                approver_value=node.approver_value,
                status=status_value,
                is_current=status_value == 'pending' and not previous_pending,
                approver='ops-admin' if status_value == 'approved' else '',
                comment='演示审批通过' if status_value == 'approved' else '',
                acted_at=deployment.approved_at if status_value == 'approved' else None,
            )
        )
    DeploymentApprovalStep.objects.bulk_create(steps)


def seed_app_release_demo(stdout, hosts, docker_hosts):
    stdout.write('正在生成应用发布演示数据...')

    cluster_prod, _ = K8sCluster.objects.update_or_create(
        name='app-prod-k8s',
        defaults={
            'api_server': 'https://app-prod-k8s.example.local:6443',
            'kubeconfig': 'demo',
            'status': 'connected',
            'description': '应用发布生产集群演示环境',
        },
    )
    cluster_gray, _ = K8sCluster.objects.update_or_create(
        name='app-gray-k8s',
        defaults={
            'api_server': 'https://app-gray-k8s.example.local:6443',
            'kubeconfig': 'demo',
            'status': 'connected',
            'description': '应用发布灰度集群演示环境',
        },
    )

    flow_prod = DeploymentApprovalFlow.objects.create(
        name='生产发布三段审批',
        environment='prod',
        description='研发负责人、产品负责人、运维负责人三级审批',
        is_active=True,
        created_by='ops-demo',
    )
    DeploymentApprovalNode.objects.bulk_create([
        DeploymentApprovalNode(flow=flow_prod, name='研发负责人审批', order=1, approver_type='user', approver_value='ops-admin'),
        DeploymentApprovalNode(flow=flow_prod, name='产品负责人审批', order=2, approver_type='role', approver_value='platform-admin'),
        DeploymentApprovalNode(flow=flow_prod, name='运维负责人审批', order=3, approver_type='group', approver_value='ops-team'),
    ])

    flow_staging = DeploymentApprovalFlow.objects.create(
        name='测试快速审批',
        environment='test',
        description='测试环境双节点审批',
        is_active=True,
        created_by='ops-demo',
    )
    DeploymentApprovalNode.objects.bulk_create([
        DeploymentApprovalNode(flow=flow_staging, name='研发自检', order=1, approver_type='user', approver_value='zhangsan'),
        DeploymentApprovalNode(flow=flow_staging, name='运维确认', order=2, approver_type='user', approver_value='ops-admin'),
    ])

    docker_host_map = {host.name: host for host in docker_hosts}
    app_docker_env = docker_host_map.get('app-release-test') or docker_hosts[0]
    gateway_docker_env = docker_host_map.get('gateway-prod') or docker_hosts[1]

    release_items = [
        {
            'app_name': 'erp-platform',
            'business_line': SYSTEM_TRADE,
            'version': 'v5.2.0',
            'image': 'registry.demo.local/erp-platform:v5.2.0',
            'environment': 'prod',
            'deploy_mode': 'k8s',
            'release_strategy': 'standard',
            'status': 'running',
            'approval_status': 'approved',
            'submitter': 'zhangsan',
            'deployer': 'ops-admin',
            'approver': 'ops-admin',
            'approval_comment': '生产窗口已确认',
            'change_summary': 'ERP 平台生产正式发布',
            'description': '典型案例：生产 K8s 标准发布',
            'cluster': cluster_prod,
            'namespace': 'erp-prod',
            'release_name': 'erp-platform-prod',
            'replicas': 3,
            'container_port': 8080,
            'service_port': 80,
            'approval_flow': flow_prod,
            'execution_count': 1,
            'is_current': True,
            'approved_at': timezone.now() - timedelta(days=2, minutes=10),
            'executed_at': timezone.now() - timedelta(days=2, minutes=5),
            'finished_at': timezone.now() - timedelta(days=2),
            'deploy_dir': 'k8s://app-prod-k8s/erp-prod/erp-platform-prod',
            'deploy_log': '[INFO] 发布模式: K8s 集群\n[INFO] 发布策略: 标准发布\n[SUCCESS] Deployment/erp-platform-prod 已发布',
            'deployed_at': timezone.now() - timedelta(days=2),
            'step_statuses': ['approved', 'approved', 'approved'],
        },
        {
            'app_name': 'gateway-service',
            'business_line': SYSTEM_TRADE,
            'version': 'v3.8.1',
            'image': 'registry.demo.local/gateway-service:v3.8.1',
            'environment': 'prod',
            'deploy_mode': 'k8s',
            'release_strategy': 'canary',
            'canary_percent': 20,
            'status': 'running',
            'approval_status': 'approved',
            'submitter': 'lisi',
            'deployer': 'ops-admin',
            'approver': 'ops-admin',
            'approval_comment': '灰度计划已确认',
            'change_summary': '网关服务 20% 灰度发布',
            'description': '典型案例：生产 K8s 灰度发布',
            'cluster': cluster_gray,
            'namespace': 'gateway-prod',
            'release_name': 'gateway-service-canary',
            'replicas': 2,
            'container_port': 8080,
            'service_port': 80,
            'approval_flow': flow_prod,
            'execution_count': 1,
            'is_current': True,
            'approved_at': timezone.now() - timedelta(days=1, hours=2, minutes=8),
            'executed_at': timezone.now() - timedelta(days=1, hours=2, minutes=5),
            'finished_at': timezone.now() - timedelta(days=1, hours=2),
            'deploy_dir': 'k8s://app-gray-k8s/gateway-prod/gateway-service-canary',
            'deploy_log': '[INFO] 发布模式: K8s 集群\n[INFO] 发布策略: 灰度发布 20%\n[SUCCESS] Canary Deployment/gateway-service-canary 已发布',
            'deployed_at': timezone.now() - timedelta(days=1, hours=2),
            'step_statuses': ['approved', 'approved', 'approved'],
        },
        {
            'app_name': 'order-center',
            'business_line': SYSTEM_TRADE,
            'version': 'v2.6.0',
            'image': 'registry.demo.local/order-center:v2.6.0',
            'environment': 'test',
            'deploy_mode': 'docker_compose',
            'release_strategy': 'batch',
            'batch_total': 3,
            'batch_current': 2,
            'batch_size': 2,
            'status': 'running',
            'approval_status': 'approved',
            'submitter': 'wangwu',
            'deployer': 'ops-admin',
            'approver': 'ops-admin',
            'approval_comment': '第二批次验证正常',
            'change_summary': '订单中心分三批发布，当前第二批',
            'description': '典型案例：测试环境 Docker 批次发布',
            'docker_host': app_docker_env,
            'container_port': 8081,
            'service_port': 8081,
            'approval_flow': flow_staging,
            'execution_count': 1,
            'is_current': True,
            'approved_at': timezone.now() - timedelta(hours=8, minutes=6),
            'executed_at': timezone.now() - timedelta(hours=8, minutes=3),
            'finished_at': timezone.now() - timedelta(hours=8),
            'deploy_dir': '/opt/sxdevops/apps/order-center-test',
            'deploy_log': '[INFO] 发布模式: Docker 环境\n[INFO] 发布策略: 批次发布，共 3 批，单批规模 2\n[INFO] 批次推进: 第 2/3 批',
            'deployed_at': timezone.now() - timedelta(hours=8),
            'step_statuses': ['approved', 'approved'],
        },
        {
            'app_name': 'order-center',
            'business_line': SYSTEM_TRADE,
            'version': 'v2.6.3',
            'image': 'registry.demo.local/order-center:v2.6.3',
            'environment': 'prod',
            'deploy_mode': 'docker_compose',
            'release_strategy': 'standard',
            'status': 'failed',
            'approval_status': 'approved',
            'submitter': 'wangwu',
            'deployer': 'ops-admin',
            'approver': 'ops-admin',
            'approval_comment': '回滚窗口已预留',
            'change_summary': '订单中心生产发布后库存校验超时，已触发异常排查',
            'description': '典型案例：生产环境异常发布记录',
            'docker_host': gateway_docker_env,
            'container_port': 8081,
            'service_port': 8081,
            'approval_flow': flow_prod,
            'execution_count': 1,
            'is_current': False,
            'approved_at': timezone.now() - timedelta(hours=3, minutes=18),
            'executed_at': timezone.now() - timedelta(hours=3, minutes=12),
            'finished_at': timezone.now() - timedelta(hours=3, minutes=5),
            'deploy_dir': '/opt/sxdevops/apps/order-center-prod',
            'deploy_log': '[INFO] 发布模式: Docker 环境\n[INFO] 发布策略: 标准发布\n[ERROR] 调用 inventory-service 超时，发布后健康检查失败',
            'deployed_at': timezone.now() - timedelta(hours=3, minutes=5),
            'step_statuses': ['approved', 'approved', 'approved'],
        },
        {
            'app_name': 'admin-portal',
            'business_line': BIZ_DATA,
            'version': 'v1.9.3',
            'image': 'registry.demo.local/admin-portal:v1.9.3',
            'environment': 'prod',
            'deploy_mode': 'docker_compose',
            'release_strategy': 'standard',
            'status': 'pending',
            'approval_status': 'pending',
            'submitter': 'zhangsan',
            'change_summary': '管理后台生产发布申请',
            'description': '典型案例：待审批发布单',
            'docker_host': gateway_docker_env,
            'container_port': 8082,
            'service_port': 8082,
            'approval_flow': flow_prod,
            'deploy_log': '',
            'deploy_dir': '',
            'deployed_at': timezone.now() - timedelta(hours=1),
            'step_statuses': ['approved', 'pending', 'pending'],
        },
        {
            'app_name': 'member-center',
            'business_line': BIZ_DATA,
            'version': 'v2.4.1',
            'image': 'registry.demo.local/member-center:v2.4.1',
            'environment': 'prod',
            'deploy_mode': 'docker_compose',
            'release_strategy': 'standard',
            'status': 'failed',
            'approval_status': 'approved',
            'submitter': 'lisi',
            'deployer': 'ops-admin',
            'approver': 'ops-admin',
            'approval_comment': '允许按故障单重试',
            'change_summary': '会员中心生产发布失败示例',
            'description': '典型案例：执行失败发布单',
            'docker_host': gateway_docker_env,
            'container_port': 8090,
            'service_port': 8090,
            'approval_flow': flow_prod,
            'execution_count': 1,
            'is_current': False,
            'approved_at': timezone.now() - timedelta(hours=4, minutes=12),
            'executed_at': timezone.now() - timedelta(hours=4, minutes=10),
            'finished_at': timezone.now() - timedelta(hours=4, minutes=6),
            'deploy_dir': '/opt/sxdevops/apps/member-center-prod',
            'deploy_log': '[INFO] 发布模式: Docker 环境\n[INFO] 发布策略: 标准发布\n[ERROR] 应用健康检查失败，已终止发布',
            'deployed_at': timezone.now() - timedelta(hours=4),
            'step_statuses': ['approved', 'approved', 'approved'],
        },
    ]

    for item in release_items:
        deployed_at = item.pop('deployed_at')
        step_statuses = item.pop('step_statuses')
        deployment = Deployment.objects.create(**item)
        Deployment.objects.filter(pk=deployment.pk).update(deployed_at=deployed_at)
        deployment.refresh_from_db()
        _create_approval_steps(deployment, step_statuses)


def seed_host_task_demo(stdout, hosts):
    stdout.write('\u6b63\u5728\u751f\u6210\u4e3b\u673a\u4efb\u52a1\u6f14\u793a\u6570\u636e...')
    host_map = {host.hostname: host for host in hosts}

    HostTaskTemplate.objects.create(
        name='\u751f\u4ea7 SSH \u5de1\u68c0',
        task_type=HostTask.TASK_CHECK_CONNECTION,
        description='\u6279\u91cf\u6821\u9a8c SSH \u767b\u5f55\u80fd\u529b\u4e0e\u57fa\u7840\u8fde\u901a\u6027',
        payload={},
        execution_mode=HostTask.EXECUTION_MODE_SSH,
        execution_strategy=HostTask.STRATEGY_CONTINUE,
        timeout_seconds=15,
        is_builtin=True,
        created_by='system',
    )
    HostTaskTemplate.objects.create(
        name='\u5e38\u7528\u670d\u52a1\u5de1\u68c0',
        task_type=HostTask.TASK_SERVICE_STATUS,
        description='\u9002\u5408\u68c0\u67e5 nginx / docker / sshd \u7b49\u57fa\u7840\u670d\u52a1\u72b6\u6001',
        payload={'service_name': 'nginx'},
        execution_mode=HostTask.EXECUTION_MODE_SSH,
        execution_strategy=HostTask.STRATEGY_CONTINUE,
        timeout_seconds=15,
        is_builtin=True,
        created_by='system',
    )
    HostTaskTemplate.objects.create(
        name='\u6279\u91cf\u5065\u5eb7\u5ea6\u68c0\u67e5',
        task_type=HostTask.TASK_RUN_COMMAND,
        description='\u53d1\u5e03\u524d\u7edf\u4e00\u68c0\u67e5\u8d1f\u8f7d\u3001\u78c1\u76d8\u4e0e\u5185\u5b58',
        payload={'command': 'uptime && df -h && free -m'},
        execution_mode=HostTask.EXECUTION_MODE_ANSIBLE,
        execution_strategy=HostTask.STRATEGY_STOP_ON_ERROR,
        timeout_seconds=30,
        is_builtin=False,
        created_by='admin',
    )
    HostTaskTemplate.objects.create(
        name='Ansible \u6279\u91cf\u57fa\u7ebf\u91c7\u96c6',
        task_type=HostTask.TASK_RUN_COMMAND,
        description='\u901a\u8fc7 Ansible \u7edf\u4e00\u4e0b\u53d1\u57fa\u7ebf\u91c7\u96c6\u547d\u4ee4\uff0c\u9002\u5408\u53d8\u66f4\u524d\u5b58\u6863',
        payload={'command': 'hostname && uptime && df -h && free -m'},
        execution_mode=HostTask.EXECUTION_MODE_ANSIBLE,
        execution_strategy=HostTask.STRATEGY_CONTINUE,
        timeout_seconds=30,
        is_builtin=True,
        created_by='system',
    )
    HostTaskTemplate.objects.create(
        name='Nginx \u914d\u7f6e\u4e00\u81f4\u6027 Playbook',
        task_type=HostTask.TASK_RUN_PLAYBOOK,
        description='\u901a\u8fc7 Playbook \u7edf\u4e00\u6821\u9a8c Nginx \u914d\u7f6e\u3001\u8bed\u6cd5\u4e0e\u7aef\u53e3\u76d1\u542c\u72b6\u6001',
        payload={
            'playbook_name': 'nginx-audit.yml',
            'playbook_content': (
                '- hosts: targets\n'
                '  gather_facts: false\n'
                '  tasks:\n'
                '    - name: check nginx config\n'
                '      shell: nginx -t\n'
                '      register: nginx_test\n'
                '      changed_when: false\n'
                '    - name: show listeners\n'
                '      shell: ss -lntp | grep nginx || true\n'
                '      changed_when: false\n'
            ),
        },
        execution_mode=HostTask.EXECUTION_MODE_ANSIBLE,
        execution_strategy=HostTask.STRATEGY_STOP_ON_ERROR,
        timeout_seconds=45,
        is_builtin=True,
        created_by='system',
    )

    demo_tasks = [
        {
            'name': '\u751f\u4ea7 SSH \u8fde\u901a\u6027\u6821\u9a8c',
            'task_type': HostTask.TASK_CHECK_CONNECTION,
            'status': HostTask.STATUS_SUCCESS,
            'description': '\u6279\u91cf\u786e\u8ba4\u751f\u4ea7\u4e3b\u673a SSH \u53ef\u7528\u6027',
            'payload': {},
            'selection_filters': {'business_line': SYSTEM_TRADE, 'environment': 'prod'},
            'execution_mode': HostTask.EXECUTION_MODE_SSH,
            'execution_strategy': HostTask.STRATEGY_CONTINUE,
            'timeout_seconds': 15,
            'created_by': 'ops_demo',
            'summary': '\u5171 2 \u53f0\uff0c\u6210\u529f 2\uff0c\u5931\u8d25 0',
            'target_hosts': ['order-api-ecs-01', 'order-api-ecs-02'],
            'executions': [
                {'host': 'order-api-ecs-01', 'status': 'success', 'command': 'hostname && uname -sr', 'output': 'order-api-ecs-01\nLinux 5.10.134-16', 'duration_ms': 820},
                {'host': 'order-api-ecs-02', 'status': 'success', 'command': 'hostname && uname -sr', 'output': 'order-api-ecs-02\nLinux 5.10.134-16', 'duration_ms': 840},
            ],
            'created_offset': timedelta(hours=9),
            'started_offset': timedelta(hours=9, minutes=2),
            'finished_offset': timedelta(hours=9, minutes=1, seconds=20),
        },
        {
            'name': '\u6279\u91cf\u5237\u65b0\u4e3b\u673a\u4fe1\u606f',
            'task_type': HostTask.TASK_REFRESH_METRICS,
            'status': HostTask.STATUS_PARTIAL,
            'description': '\u5237\u65b0 CPU / \u5185\u5b58 / \u78c1\u76d8 \u6307\u6807\u5e76\u66f4\u65b0\u5728\u7ebf\u72b6\u6001',
            'payload': {},
            'selection_filters': {'business_line': SYSTEM_TRADE},
            'execution_mode': HostTask.EXECUTION_MODE_SSH,
            'execution_strategy': HostTask.STRATEGY_CONTINUE,
            'timeout_seconds': 20,
            'created_by': 'admin',
            'summary': '\u5171 3 \u53f0\uff0c\u6210\u529f 2\uff0c\u5931\u8d25 1\uff0c\u5931\u8d25\u4e3b\u673a\uff1aorder-perf-test-ecs',
            'target_hosts': ['order-api-ecs-01', 'order-api-ecs-02', 'order-perf-test-ecs'],
            'executions': [
                {'host': 'order-api-ecs-01', 'status': 'success', 'command': 'metrics: cpu/memory/disk refresh', 'output': 'CPU 43.0% | \u5185\u5b58 52.0% | \u78c1\u76d8 61.0%', 'duration_ms': 1120},
                {'host': 'order-api-ecs-02', 'status': 'success', 'command': 'metrics: cpu/memory/disk refresh', 'output': 'CPU 41.0% | \u5185\u5b58 49.0% | \u78c1\u76d8 58.0%', 'duration_ms': 1080},
                {'host': 'order-perf-test-ecs', 'status': 'failed', 'command': 'metrics: cpu/memory/disk refresh', 'error_message': 'SSH authentication failed', 'duration_ms': 5900},
            ],
            'created_offset': timedelta(hours=6),
            'started_offset': timedelta(hours=6, minutes=3),
            'finished_offset': timedelta(hours=6, minutes=2, seconds=10),
        },
        {
            'name': '\u53d1\u5e03\u524d Nginx \u914d\u7f6e\u7a33\u5b9a\u6027\u6821\u9a8c',
            'task_type': HostTask.TASK_RUN_PLAYBOOK,
            'status': HostTask.STATUS_PARTIAL,
            'description': '\u4f7f\u7528 Playbook \u7edf\u4e00\u6821\u9a8c prod \u8282\u70b9 Nginx \u8bed\u6cd5\u548c\u76d1\u542c\u72b6\u6001',
            'payload': {
                'playbook_name': 'nginx-preflight.yml',
                'playbook_content': (
                    '- hosts: targets\n'
                    '  gather_facts: false\n'
                    '  tasks:\n'
                    '    - name: validate nginx config\n'
                    '      shell: nginx -t\n'
                    '      changed_when: false\n'
                    '    - name: inspect listeners\n'
                    '      shell: ss -lntp | grep nginx || true\n'
                    '      changed_when: false\n'
                ),
            },
            'selection_filters': {'business_line': SYSTEM_TRADE, 'environment': 'prod'},
            'execution_mode': HostTask.EXECUTION_MODE_ANSIBLE,
            'execution_strategy': HostTask.STRATEGY_STOP_ON_ERROR,
            'timeout_seconds': 45,
            'created_by': 'release_mgr',
            'summary': '\u5171 2 \u53f0\uff0c\u6210\u529f 1\uff0c\u5931\u8d25 1\uff0c\u5931\u8d25\u4e3b\u673a\uff1aorder-api-ecs-02\uff0c\u6267\u884c\u65b9\u5f0f\uff1aAnsible',
            'target_hosts': ['order-api-ecs-01', 'order-api-ecs-02'],
            'executions': [
                {'host': 'order-api-ecs-01', 'status': 'success', 'command': 'ansible-playbook nginx-preflight.yml', 'output': 'PLAY [targets]\nTASK [validate nginx config]\nok: [order-api-ecs-01]', 'duration_ms': 2320},
                {'host': 'order-api-ecs-02', 'status': 'failed', 'command': 'ansible-playbook nginx-preflight.yml', 'error_message': 'fatal: [order-api-ecs-02]: FAILED! => nginx: [emerg] unexpected end of file', 'duration_ms': 2010},
            ],
            'created_offset': timedelta(hours=4, minutes=30),
            'started_offset': timedelta(hours=4, minutes=29),
            'finished_offset': timedelta(hours=4, minutes=28, seconds=20),
        },
        {
            'name': '\u6279\u91cf\u65e5\u5fd7\u5de1\u68c0',
            'task_type': HostTask.TASK_RUN_COMMAND,
            'status': HostTask.STATUS_CANCELED,
            'description': '\u6267\u884c\u65e5\u5fd7\u4e0e\u6587\u4ef6\u7cfb\u7edf\u5feb\u901f\u68c0\u67e5\uff0c\u4e2d\u9014\u53d1\u8d77\u4e86\u7ec8\u6b62',
            'payload': {'command': 'uptime && df -h / /data && cat /etc/fstab'},
            'selection_filters': {'business_line': '\u57fa\u7840\u8bbe\u65bd', 'environment': 'prod'},
            'execution_mode': HostTask.EXECUTION_MODE_ANSIBLE,
            'execution_strategy': HostTask.STRATEGY_CONTINUE,
            'timeout_seconds': 30,
            'created_by': 'admin',
            'summary': '\u5171 3 \u53f0\uff0c\u6210\u529f 1\uff0c\u5931\u8d25 0\uff0c\u8df3\u8fc7 2\uff0c\u4efb\u52a1\u5df2\u6309\u7533\u8bf7\u7ec8\u6b62\uff0cAnsible \u4e0d\u53ef\u7528\u5df2\u56de\u9000 SSH',
            'target_hosts': ['k8s-node-01', 'order-api-ecs-01', 'order-api-ecs-02'],
            'executions': [
                {'host': 'k8s-node-01', 'status': 'success', 'command': 'uptime && df -h / /data && cat /etc/fstab', 'output': 'load average: 1.12, 1.09, 0.98', 'duration_ms': 1380},
                {'host': 'order-api-ecs-01', 'status': 'skipped', 'command': '', 'error_message': '\u4efb\u52a1\u5df2\u6536\u5230\u7ec8\u6b62\u8bf7\u6c42\uff0c\u5269\u4f59\u4e3b\u673a\u5df2\u8df3\u8fc7\u6267\u884c', 'duration_ms': 0},
                {'host': 'order-api-ecs-02', 'status': 'skipped', 'command': '', 'error_message': '\u4efb\u52a1\u5df2\u6536\u5230\u7ec8\u6b62\u8bf7\u6c42\uff0c\u5269\u4f59\u4e3b\u673a\u5df2\u8df3\u8fc7\u6267\u884c', 'duration_ms': 0},
            ],
            'target_count': 3,
            'success_count': 1,
            'failed_count': 0,
            'skipped_count': 2,
            'cancel_requested': True,
            'cancel_requested_by': 'admin',
            'cancel_requested_at_offset': timedelta(hours=2, minutes=9),
            'created_offset': timedelta(hours=2, minutes=10),
            'started_offset': timedelta(hours=2, minutes=10),
            'finished_offset': timedelta(hours=2, minutes=8, seconds=40),
        },
        {
            'name': '\u53d1\u5e03\u540e\u5e94\u7528\u5065\u5eb7\u5267\u672c',
            'task_type': HostTask.TASK_RUN_PLAYBOOK,
            'status': HostTask.STATUS_RUNNING,
            'description': '\u6b63\u5728\u901a\u8fc7 Playbook \u91c7\u96c6 prod \u8282\u70b9\u5065\u5eb7\u5ea6\u4e0e\u5e94\u7528\u8fdb\u7a0b\u4fe1\u606f',
            'payload': {
                'playbook_name': 'post-release-health.yml',
                'playbook_content': (
                    '- hosts: targets\n'
                    '  gather_facts: false\n'
                    '  tasks:\n'
                    '    - name: check uptime\n'
                    '      shell: uptime\n'
                    '      changed_when: false\n'
                    '    - name: inspect app process\n'
                    '      shell: ps -ef | grep order-api | grep -v grep\n'
                    '      changed_when: false\n'
                ),
            },
            'selection_filters': {'environment': 'prod'},
            'execution_mode': HostTask.EXECUTION_MODE_ANSIBLE,
            'execution_strategy': HostTask.STRATEGY_CONTINUE,
            'timeout_seconds': 60,
            'created_by': 'ops_demo',
            'summary': '\u4efb\u52a1\u6267\u884c\u4e2d\uff0c\u6b63\u5728\u901a\u8fc7 Ansible \u8fde\u63a5\u76ee\u6807\u4e3b\u673a',
            'target_hosts': ['k8s-node-01', 'order-api-ecs-01', 'order-api-ecs-02', 'legacy-data-sync'],
            'executions': [
                {'host': 'k8s-node-01', 'status': 'success', 'command': 'ansible-playbook post-release-health.yml', 'output': 'PLAY [targets]\nTASK [check uptime]\nok: [k8s-node-01]', 'duration_ms': 2100},
            ],
            'target_count': 4,
            'success_count': 1,
            'failed_count': 0,
            'skipped_count': 0,
            'created_offset': timedelta(minutes=45),
            'started_offset': timedelta(minutes=44),
        },
        {
            'name': '\u9057\u7559\u670d\u52a1\u72b6\u6001\u68c0\u67e5',
            'task_type': HostTask.TASK_SERVICE_STATUS,
            'status': HostTask.STATUS_FAILED,
            'description': '\u68c0\u67e5 legacy-data-sync \u670d\u52a1\u662f\u5426\u4ecd\u5728\u8fd0\u884c',
            'payload': {'service_name': 'data-sync'},
            'selection_filters': {'hostname': 'legacy-data-sync'},
            'execution_mode': HostTask.EXECUTION_MODE_SSH,
            'execution_strategy': HostTask.STRATEGY_STOP_ON_ERROR,
            'timeout_seconds': 20,
            'created_by': 'ops_demo',
            'summary': '\u5171 1 \u53f0\uff0c\u6210\u529f 0\uff0c\u5931\u8d25 1\uff0c\u5931\u8d25\u4e3b\u673a\uff1alegacy-data-sync',
            'target_hosts': ['legacy-data-sync'],
            'executions': [
                {'host': 'legacy-data-sync', 'status': 'failed', 'command': 'systemctl status data-sync --no-pager --lines=12', 'error_message': 'Unit data-sync.service could not be found.', 'duration_ms': 1640},
            ],
            'created_offset': timedelta(minutes=110),
            'started_offset': timedelta(minutes=109),
            'finished_offset': timedelta(minutes=108, seconds=20),
        },
    ]

    for item in demo_tasks:
        target_hosts = [host_map[name] for name in item.pop('target_hosts') if name in host_map]
        target_snapshot = [
            {
                'id': host.id,
                'hostname': host.hostname,
                'ip_address': host.ip_address,
                'business_line': host.business_line,
                'environment': host.environment,
                'status': host.status,
            }
            for host in target_hosts
        ]
        executions = item.pop('executions')
        created_offset = item.pop('created_offset')
        started_offset = item.pop('started_offset', None)
        finished_offset = item.pop('finished_offset', None)
        cancel_requested_at_offset = item.pop('cancel_requested_at_offset', None)
        task = HostTask.objects.create(
            target_snapshot=target_snapshot,
            target_count=item.pop('target_count', len(target_hosts)),
            success_count=item.pop('success_count', sum(1 for execution in executions if execution['status'] == 'success')),
            failed_count=item.pop('failed_count', sum(1 for execution in executions if execution['status'] == 'failed')),
            skipped_count=item.pop('skipped_count', sum(1 for execution in executions if execution['status'] == 'skipped')),
            cancel_requested=item.pop('cancel_requested', False),
            cancel_requested_by=item.pop('cancel_requested_by', ''),
            cancel_requested_at=timezone.now() - cancel_requested_at_offset if cancel_requested_at_offset else None,
            started_at=timezone.now() - started_offset if started_offset else None,
            finished_at=timezone.now() - finished_offset if finished_offset else None,
            **item,
        )
        created_at = timezone.now() - created_offset
        updated_at = task.finished_at or task.started_at or created_at
        HostTask.objects.filter(pk=task.pk).update(created_at=created_at, updated_at=updated_at)
        task.refresh_from_db()
        for execution in executions:
            host = host_map[execution['host']]
            finished_at = (task.finished_at or timezone.now()) if task.status != HostTask.STATUS_RUNNING else None
            started_at = task.started_at or created_at
            HostTaskExecution.objects.create(
                task=task,
                host=host,
                host_name=host.hostname,
                host_ip=host.ip_address,
                status=execution['status'],
                command=execution.get('command', ''),
                output=execution.get('output', ''),
                error_message=execution.get('error_message', ''),
                duration_ms=execution.get('duration_ms', 0),
                started_at=started_at,
                finished_at=finished_at,
            )


def seed_host_schedule_demo(stdout, hosts):
    stdout.write('正在生成主机定时任务演示数据...')
    host_map = {host.hostname: host for host in hosts}
    now = timezone.now()

    def build_snapshot(host_names):
        selected = [host_map[name] for name in host_names if name in host_map]
        return selected, [
            {
                'id': host.id,
                'hostname': host.hostname,
                'ip_address': host.ip_address,
                'business_line': host.business_line,
                'environment': host.environment,
                'status': host.status,
            }
            for host in selected
        ]

    schedule_specs = [
        {
            'name': '生产主机夜间健康巡检',
            'description': '每天凌晨对生产主机执行负载、磁盘与内存巡检。',
            'task_type': HostTask.TASK_RUN_COMMAND,
            'payload': {'command': 'hostname && uptime && df -h && free -m'},
            'execution_mode': HostTask.EXECUTION_MODE_ANSIBLE,
            'execution_strategy': HostTask.STRATEGY_CONTINUE,
            'schedule_type': HostTaskSchedule.SCHEDULE_TYPE_CRON,
            'cron_expression': '0 2 * * *',
            'timeout_seconds': 30,
            'enabled': True,
            'overlap_policy': HostTaskSchedule.OVERLAP_SKIP,
            'host_names': ['order-api-ecs-01', 'order-api-ecs-02'],
            'last_status': HostTask.STATUS_SUCCESS,
            'last_run_at': now - timedelta(hours=22),
            'next_run_at': now + timedelta(hours=2),
            'total_run_count': 14,
            'created_by': 'ops_demo',
        },
        {
            'name': '核心主机资源指标刷新',
            'description': '每 30 分钟刷新一次核心主机的 CPU、内存和磁盘指标。',
            'task_type': HostTask.TASK_REFRESH_METRICS,
            'payload': {},
            'execution_mode': HostTask.EXECUTION_MODE_SSH,
            'execution_strategy': HostTask.STRATEGY_CONTINUE,
            'schedule_type': HostTaskSchedule.SCHEDULE_TYPE_INTERVAL,
            'interval_seconds': 1800,
            'run_at': now - timedelta(hours=3),
            'timeout_seconds': 20,
            'enabled': True,
            'overlap_policy': HostTaskSchedule.OVERLAP_SKIP,
            'host_names': ['legacy-data-sync', 'feature-x-dev-ecs'],
            'last_status': HostTask.STATUS_PARTIAL,
            'last_run_at': now - timedelta(minutes=25),
            'next_run_at': now + timedelta(minutes=5),
            'total_run_count': 38,
            'created_by': 'ops_demo',
            'last_error': '1 台主机刷新失败，建议检查 SSH 凭据',
            'consecutive_failures': 1,
        },
        {
            'name': '窗口期 Nginx Playbook 检查',
            'description': '维护窗口执行一次 Nginx 配置一致性检查 Playbook。',
            'task_type': HostTask.TASK_RUN_PLAYBOOK,
            'payload': {
                'playbook_name': 'nginx-window-check.yml',
                'playbook_content': (
                    '- hosts: targets\n'
                    '  gather_facts: false\n'
                    '  tasks:\n'
                    '    - name: check nginx config\n'
                    '      shell: nginx -t\n'
                    '      changed_when: false\n'
                ),
            },
            'execution_mode': HostTask.EXECUTION_MODE_ANSIBLE,
            'execution_strategy': HostTask.STRATEGY_STOP_ON_ERROR,
            'schedule_type': HostTaskSchedule.SCHEDULE_TYPE_ONCE,
            'run_at': now - timedelta(days=1),
            'timeout_seconds': 90,
            'enabled': False,
            'overlap_policy': HostTaskSchedule.OVERLAP_SKIP,
            'host_names': ['order-api-ecs-01'],
            'last_status': HostTask.STATUS_SUCCESS,
            'last_run_at': now - timedelta(days=1),
            'next_run_at': None,
            'total_run_count': 1,
            'created_by': 'ops_demo',
        },
    ]

    schedule_map = {}
    for spec in schedule_specs:
        selected_hosts, snapshot = build_snapshot(spec.pop('host_names'))
        schedule = HostTaskSchedule.objects.create(
            target_host_ids=[host.id for host in selected_hosts],
            target_snapshot=snapshot,
            target_count=len(snapshot),
            timezone='Asia/Shanghai',
            **spec,
        )
        schedule_map[schedule.name] = schedule

    def create_generated_task(schedule, spec):
        host_names = spec.pop('host_names')
        execution_items = spec.pop('executions')
        requested_at = spec['requested_at']
        started_at = spec.get('started_at')
        finished_at = spec.get('finished_at')
        trigger_source = HostTask.TRIGGER_SOURCE_SCHEDULE if spec['trigger_source'] == HostTaskScheduleExecution.TRIGGER_SCHEDULER else HostTask.TRIGGER_SOURCE_MANUAL
        selected_hosts, snapshot = build_snapshot(host_names)
        task = HostTask.objects.create(
            name=spec.pop('task_name'),
            task_type=schedule.task_type,
            status=spec['status'],
            description=schedule.description,
            payload=dict(schedule.payload or {}),
            selection_filters=dict(schedule.selection_filters or {}),
            target_snapshot=snapshot,
            target_count=spec.get('target_count', len(snapshot)),
            success_count=spec.get('success_count', sum(1 for item in execution_items if item['status'] == 'success')),
            failed_count=spec.get('failed_count', sum(1 for item in execution_items if item['status'] == 'failed')),
            skipped_count=spec.get('skipped_count', sum(1 for item in execution_items if item['status'] == 'skipped')),
            execution_mode=schedule.execution_mode,
            execution_strategy=schedule.execution_strategy,
            timeout_seconds=schedule.timeout_seconds,
            created_by=spec['requested_by'],
            summary=spec['summary'],
            started_at=started_at,
            finished_at=finished_at,
            schedule=schedule,
            trigger_source=trigger_source,
        )
        HostTask.objects.filter(pk=task.pk).update(
            created_at=requested_at,
            updated_at=finished_at or started_at or requested_at,
        )
        task.refresh_from_db()
        for item in execution_items:
            host = host_map[item['host']]
            HostTaskExecution.objects.create(
                task=task,
                host=host,
                host_name=host.hostname,
                host_ip=host.ip_address,
                status=item['status'],
                command=item.get('command', ''),
                output=item.get('output', ''),
                error_message=item.get('error_message', ''),
                duration_ms=item.get('duration_ms', 0),
                started_at=started_at or requested_at,
                finished_at=finished_at if task.status != HostTask.STATUS_RUNNING else None,
            )
        return task

    execution_specs = [
        {
            'schedule': '生产主机夜间健康巡检',
            'task_name': '生产主机夜间健康巡检 / 2026-03-31 02:00',
            'trigger_source': HostTaskScheduleExecution.TRIGGER_SCHEDULER,
            'status': HostTask.STATUS_SUCCESS,
            'summary': '共 2 台，成功 2，失败 0',
            'target_count': 2,
            'success_count': 2,
            'failed_count': 0,
            'requested_by': 'system-scheduler',
            'requested_at': now - timedelta(hours=22),
            'started_at': now - timedelta(hours=22),
            'finished_at': now - timedelta(hours=21, minutes=58),
            'host_names': ['order-api-ecs-01', 'order-api-ecs-02'],
            'executions': [
                {'host': 'order-api-ecs-01', 'status': 'success', 'command': 'ansible nightly-health-check', 'output': 'load average: 0.62, 0.48, 0.35', 'duration_ms': 1620},
                {'host': 'order-api-ecs-02', 'status': 'success', 'command': 'ansible nightly-health-check', 'output': 'disk /data usage: 58%', 'duration_ms': 1740},
            ],
        },
        {
            'schedule': '核心主机资源指标刷新',
            'task_name': '核心主机资源指标刷新 / 近 30 分钟轮询',
            'trigger_source': HostTaskScheduleExecution.TRIGGER_SCHEDULER,
            'status': HostTask.STATUS_PARTIAL,
            'summary': '共 2 台，成功 1，失败 1',
            'target_count': 2,
            'success_count': 1,
            'failed_count': 1,
            'error_message': 'legacy-data-sync 刷新失败',
            'requested_by': 'system-scheduler',
            'requested_at': now - timedelta(minutes=25),
            'started_at': now - timedelta(minutes=25),
            'finished_at': now - timedelta(minutes=24, seconds=15),
            'host_names': ['legacy-data-sync', 'feature-x-dev-ecs'],
            'executions': [
                {'host': 'feature-x-dev-ecs', 'status': 'success', 'command': 'refresh host metrics', 'output': 'CPU 4% | 内存 18% | 磁盘 25%', 'duration_ms': 980},
                {'host': 'legacy-data-sync', 'status': 'failed', 'command': 'refresh host metrics', 'error_message': 'SSH authentication failed', 'duration_ms': 3020},
            ],
        },
        {
            'schedule': '窗口期 Nginx Playbook 检查',
            'task_name': '窗口期 Nginx Playbook 检查 / 手动触发',
            'trigger_source': HostTaskScheduleExecution.TRIGGER_MANUAL,
            'status': HostTask.STATUS_SUCCESS,
            'summary': '窗口执行完成，Nginx 配置检查通过',
            'target_count': 1,
            'success_count': 1,
            'failed_count': 0,
            'requested_by': 'ops_demo',
            'requested_at': now - timedelta(days=1),
            'started_at': now - timedelta(days=1),
            'finished_at': now - timedelta(days=1, minutes=-3),
            'host_names': ['order-api-ecs-01'],
            'executions': [
                {'host': 'order-api-ecs-01', 'status': 'success', 'command': 'ansible-playbook nginx-window-check.yml', 'output': 'PLAY RECAP: order-api-ecs-01 ok=1 changed=0 failed=0', 'duration_ms': 2410},
            ],
        },
        {
            'schedule': '生产主机夜间健康巡检',
            'task_name': '生产主机夜间健康巡检 / 2026-03-30 02:00',
            'trigger_source': HostTaskScheduleExecution.TRIGGER_SCHEDULER,
            'status': HostTask.STATUS_SUCCESS,
            'summary': 'Ansible 批量巡检完成，输出已归档到任务历史',
            'target_count': 2,
            'success_count': 2,
            'failed_count': 0,
            'requested_by': 'system-scheduler',
            'requested_at': now - timedelta(days=2, hours=22),
            'started_at': now - timedelta(days=2, hours=22),
            'finished_at': now - timedelta(days=2, hours=21, minutes=58),
            'host_names': ['order-api-ecs-01', 'order-api-ecs-02'],
            'executions': [
                {'host': 'order-api-ecs-01', 'status': 'success', 'command': 'ansible nightly-health-check', 'output': 'uptime ok | free -m ok', 'duration_ms': 1580},
                {'host': 'order-api-ecs-02', 'status': 'success', 'command': 'ansible nightly-health-check', 'output': 'hostname ok | df -h ok', 'duration_ms': 1660},
            ],
        },
    ]

    for spec in execution_specs:
        schedule = schedule_map[spec.pop('schedule')]
        task = create_generated_task(schedule, spec)
        requested_at = spec.pop('requested_at')
        execution = HostTaskScheduleExecution.objects.create(
            schedule=schedule,
            host_task=task,
            requested_at=requested_at,
            created_at=requested_at,
            **spec,
        )
        HostTaskScheduleExecution.objects.filter(pk=execution.pk).update(requested_at=requested_at, created_at=requested_at)

class Command(BaseCommand):
    help = '生成 Mock 演示数据'

    def handle(self, *args, **options):

        self.stdout.write('\u6b63\u5728\u6e05\u7406\u65e7\u6570\u636e...')
        ServiceDeployment.objects.all().delete()
        DeploymentApprovalStep.objects.all().delete()
        DeploymentApprovalNode.objects.all().delete()
        DeploymentApprovalFlow.objects.all().delete()
        Deployment.objects.all().delete()
        HostTaskExecution.objects.all().delete()
        HostTaskScheduleExecution.objects.all().delete()
        HostTaskSchedule.objects.all().delete()
        HostTask.objects.all().delete()
        HostTaskTemplate.objects.all().delete()
        Alert.objects.all().delete()
        LogEntry.objects.all().delete()
        Host.objects.all().delete()
        DockerHost.objects.all().delete()

        self.stdout.write('\u6b63\u5728\u751f\u6210\u4e3b\u673a\u6570\u636e...')
        hosts = []
        host_configs = [
            {
                'hostname': 'order-api-ecs-01',
                'ip_address': '10.10.1.10',
                'os_type': 'Alibaba Cloud Linux 3',
                'business_line': SYSTEM_TRADE,
                'environment': 'prod',
                'admin_user': '\u5e94\u7528\u8fd0\u7ef4-\u674e\u4fca',
                'description': '\u8ba2\u5355\u670d\u52a1\u751f\u4ea7\u8282\u70b9 A\uff0c\u5bf9\u5e94 CMDB \u4e91\u4e3b\u673a\u914d\u7f6e\u9879',
                'status': 'online',
                'cpu_usage': 43.0,
                'memory_usage': 52.0,
                'disk_usage': 61.0,
            },
            {
                'hostname': 'order-api-ecs-02',
                'ip_address': '10.10.1.11',
                'os_type': 'Alibaba Cloud Linux 3',
                'business_line': SYSTEM_TRADE,
                'environment': 'prod',
                'admin_user': '\u5e94\u7528\u8fd0\u7ef4-\u674e\u4fca',
                'description': '\u8ba2\u5355\u670d\u52a1\u751f\u4ea7\u8282\u70b9 B\uff0c\u5bf9\u5e94 CMDB \u4e91\u4e3b\u673a\u914d\u7f6e\u9879',
                'status': 'online',
                'cpu_usage': 41.0,
                'memory_usage': 49.0,
                'disk_usage': 58.0,
            },
            {
                'hostname': 'order-perf-test-ecs',
                'ip_address': '10.10.20.10',
                'os_type': 'Ubuntu 22.04',
                'business_line': SYSTEM_TRADE,
                'environment': 'test',
                'admin_user': '\u6d4b\u8bd5\u5e73\u53f0-\u9648\u82b3',
                'description': '\u538b\u6d4b\u73af\u5883\u4e3b\u673a\uff0c\u538b\u6d4b\u7ed3\u675f\u540e\u5e94\u53ca\u65f6\u56de\u6536\u6216\u964d\u914d',
                'status': 'warning',
                'cpu_usage': 12.0,
                'memory_usage': 28.0,
                'disk_usage': 46.0,
            },
            {
                'hostname': 'feature-x-dev-ecs',
                'ip_address': '10.10.30.30',
                'os_type': 'Ubuntu 22.04',
                'business_line': SYSTEM_TRADE,
                'environment': 'dev',
                'admin_user': '\u7814\u53d1-\u5f20\u6668',
                'description': '\u529f\u80fd\u8054\u8c03\u5f00\u53d1\u4e3b\u673a\uff0c\u5f53\u524d\u5229\u7528\u7387\u504f\u4f4e',
                'status': 'warning',
                'cpu_usage': 4.0,
                'memory_usage': 18.0,
                'disk_usage': 25.0,
            },
            {
                'hostname': 'airflow-worker-dev',
                'ip_address': '10.20.10.10',
                'os_type': 'CentOS Stream 9',
                'business_line': BIZ_DATA,
                'environment': 'dev',
                'admin_user': '\u6570\u636e\u5e73\u53f0-\u97e9\u6885',
                'description': '\u5f00\u53d1\u8c03\u5ea6\u8282\u70b9\uff0c\u5bf9\u5e94 CMDB \u5f00\u53d1\u73af\u5883\u4e3b\u673a',
                'status': 'online',
                'cpu_usage': 14.0,
                'memory_usage': 32.0,
                'disk_usage': 37.0,
            },
            {
                'hostname': 'legacy-data-sync',
                'ip_address': '10.20.30.20',
                'os_type': 'CentOS 7.9',
                'business_line': BIZ_DATA,
                'environment': 'prod',
                'admin_user': '\u6570\u636e\u96c6\u6210-\u5b59\u535a',
                'description': '\u9057\u7559\u540c\u6b65\u4e3b\u673a\uff0c\u5df2\u505c\u6b62\u4f7f\u7528\u4f46\u4ecd\u672a\u5b8c\u6210\u4e0b\u7ebf\u56de\u6536',
                'status': 'offline',
                'cpu_usage': 0.0,
                'memory_usage': 0.0,
                'disk_usage': 0.0,
            },
            {
                'hostname': 'k8s-node-01',
                'ip_address': '10.30.1.11',
                'os_type': 'Ubuntu 22.04',
                'business_line': BIZ_INFRA,
                'environment': 'prod',
                'admin_user': 'SRE-\u738b\u6d9b',
                'description': '\u57fa\u7840\u8bbe\u65bd\u751f\u4ea7 K8s \u5de5\u4f5c\u8282\u70b9\uff0c\u4e0e CMDB \u914d\u7f6e\u9879\u4e00\u81f4',
                'status': 'online',
                'cpu_usage': 28.0,
                'memory_usage': 44.0,
                'disk_usage': 51.0,
            },
        ]
        for config in host_configs:
            hosts.append(
                Host.objects.create(
                    hostname=config['hostname'],
                    ip_address=config['ip_address'],
                    os_type=config['os_type'],
                    business_line=config['business_line'],
                    environment=config['environment'],
                    admin_user=config['admin_user'],
                    description=config['description'],
                    status=config['status'],
                    cpu_usage=config['cpu_usage'],
                    memory_usage=config['memory_usage'],
                    disk_usage=config['disk_usage'],
                )
            )

        self.stdout.write('正在生成 Docker 主机数据...')
        docker_hosts = [
            DockerHost.objects.create(
                name='app-release-test',
                ip_address='192.168.1.120',
                ssh_port=22,
                ssh_user='root',
                ssh_password='',
                docker_api_version='24.0',
                status='connected',
                description='应用发布测试 Docker 环境',
            ),
            DockerHost.objects.create(
                name='gateway-prod',
                ip_address='192.168.1.121',
                ssh_port=22,
                ssh_user='root',
                ssh_password='',
                docker_api_version='24.0',
                status='connected',
                description='网关生产 Docker 环境',
            ),
            DockerHost.objects.create(
                name='member-prod',
                ip_address='192.168.1.122',
                ssh_port=22,
                ssh_user='root',
                ssh_password='',
                docker_api_version='24.0',
                status='connected',
                description='会员中心生产 Docker 环境',
            ),
        ]

        self.stdout.write('正在生成监控告警数据...')

        self.stdout.write('正在生成告警数据...')
        alert_templates = [
            ('CPU 使用率过高', 'critical', 'Prometheus', 'CPU 使用率持续 5 分钟超过 90%'),
            ('内存使用率过高', 'warning', 'Prometheus', '内存使用率超过 80%'),
            ('磁盘空间不足', 'critical', 'Zabbix', '磁盘使用率超过 95%，请及时清理'),
            ('服务响应超时', 'warning', 'APM', '服务平均响应时间超过 3 秒'),
        ]
        for _ in range(12):
            title, level, source, message = random.choice(alert_templates)
            Alert.objects.create(
                title=title,
                level=level,
                source=source,
                message=message,
                is_acknowledged=random.choice([True, False, False]),
                host=random.choice(hosts),
            )
        prod_hosts = [host for host in hosts if host.environment == 'prod']
        order_prod_host = next((host for host in prod_hosts if 'order' in host.hostname), None) or (prod_hosts[0] if prod_hosts else hosts[0])
        Alert.objects.bulk_create([
            Alert(
                title='order-center 库存校验超时',
                level='critical',
                source='APM',
                message='order-service inventory timeout in prod',
                is_acknowledged=False,
                host=order_prod_host,
            ),
            Alert(
                title='order-center 下游依赖重试激增',
                level='critical',
                source='APM',
                message='inventory-service retry rate exceeded threshold in prod',
                is_acknowledged=False,
                host=order_prod_host,
            ),
            Alert(
                title='order-center 发布后健康检查失败',
                level='warning',
                source='APM',
                message='post-release health check failed for order-center in prod',
                is_acknowledged=False,
                host=order_prod_host,
            ),
            Alert(
                title='payment-worker Deployment 副本不可用',
                level='critical',
                source='Prometheus',
                message='kube_deployment_status_replicas_unavailable > 0 for deployment payment-worker in namespace production',
                is_acknowledged=False,
                host=next((host for host in prod_hosts if host.hostname == 'k8s-node-01'), order_prod_host),
            ),
            Alert(
                title='member-api Deployment 滚动发布卡住',
                level='critical',
                source='Prometheus',
                message='kube_deployment_status_condition indicates progressing timeout for deployment member-api in namespace production',
                is_acknowledged=False,
                host=next((host for host in prod_hosts if host.hostname == 'k8s-node-01'), order_prod_host),
            ),
        ])

        self.stdout.write('正在生成日志数据...')
        services = ['user-service', 'order-service', 'gateway', 'nginx', 'mysql', 'redis']
        log_messages = {
            'error': ['Connection refused to database', 'Timeout while waiting for response'],
            'warning': ['Slow query detected: 2.5s', 'Connection pool reaching limit'],
            'info': ['Service started successfully', 'Health check passed'],
            'debug': ['Cache hit for key: user_123', 'WebSocket connection established'],
        }
        for _ in range(40):
            level = random.choices(['error', 'warning', 'info', 'debug'], weights=[10, 20, 50, 20])[0]
            LogEntry.objects.create(
                level=level,
                service=random.choice(services),
                message=random.choice(log_messages[level]),
                host=random.choice(hosts),
            )
        LogEntry.objects.bulk_create([
            LogEntry(
                level='error',
                service='order-service',
                message='Inventory service timeout while creating order ORD-20260410-1024',
                host=order_prod_host,
            ),
            LogEntry(
                level='warning',
                service='order-service',
                message='Order center downstream latency increased to 1.8s on /api/orders/create',
                host=order_prod_host,
            ),
            LogEntry(
                level='warning',
                service='order-center',
                message='Order center detected retry storm after inventory timeout in prod',
                host=order_prod_host,
            ),
        ])

        seed_app_release_demo(self.stdout, hosts, docker_hosts)
        seed_host_task_demo(self.stdout, hosts)
        seed_host_schedule_demo(self.stdout, hosts)
        seed_sqlaudit_demo(self.stdout)
        self.stdout.write(
            f'演示数据完成: {len(hosts)} 台主机, {Deployment.objects.count()} 个发布单, {Alert.objects.count()} 条告警, {LogEntry.objects.count()} 条日志'
        )

        self.stdout.write('正在生成 RBAC 演示数据...')
        seed_marketplace_demo(self.stdout, hosts)
        call_command('seed_rbac_demo')
        self.stdout.write('正在生成 RBAC 演示数据...')
        self.stdout.write('正在生成 CMDB 演示数据...')
        seed_cmdb_demo(self.stdout)
        call_command('seed_transaction_ticket_demo')
        call_command('seed_multicloud_demo')
        sync_current_deployments_to_cmdb()
        call_command('seed_eventwall_demo')
        seed_eventwall_unmatched_environment_demo(self.stdout)

