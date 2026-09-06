from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

import os
import secrets

from rbac.models import Role, UserGroup
from rbac.services import ensure_builtin_rbac


User = get_user_model()
DEFAULT_PASSWORD = os.getenv('SXDEVOPS_DEMO_PASSWORD') or secrets.token_urlsafe(18)

DEMO_USERS = [
    {
        'username': 'ops_demo',
        'email': 'ops_demo@example.com',
        'first_name': 'Ops',
        'last_name': 'Demo',
        'roles': ['ops-admin'],
        'groups': ['ops-team'],
        'is_staff': True,
    },
    {
        'username': 'dev_demo',
        'email': 'dev_demo@example.com',
        'first_name': 'Dev',
        'last_name': 'Demo',
        'roles': ['developer'],
        'groups': ['dev-team'],
        'is_staff': False,
    },
    {
        'username': 'audit_demo',
        'email': 'audit_demo@example.com',
        'first_name': 'Audit',
        'last_name': 'Demo',
        'roles': ['security-auditor'],
        'groups': ['audit-team'],
        'is_staff': False,
    },
    {
        'username': 'viewer_demo',
        'email': 'viewer_demo@example.com',
        'first_name': 'Viewer',
        'last_name': 'Demo',
        'roles': ['read-only'],
        'groups': ['visitors'],
        'is_staff': False,
    },
    {
        'username': 'demo',
        'email': 'demo@example.com',
        'first_name': 'Demo',
        'last_name': 'User',
        'password': 'Demo#123',
        'roles': ['platform-admin'],
        'groups': ['visitors'],
        'is_staff': True,
    },
]

DEMO_GROUPS = [
    {'code': 'ops-team', 'name': '运维组', 'description': '负责主机、部署、容器、Nginx 与 CMDB 运维', 'roles': ['ops-admin']},
    {'code': 'dev-team', 'name': '研发组', 'description': '负责应用开发与 SQL 提交', 'roles': ['developer']},
    {'code': 'audit-team', 'name': '审计组', 'description': '负责日志审计与 SQL 审核', 'roles': ['security-auditor']},
    {'code': 'visitors', 'name': '访客组', 'description': '只读浏览平台信息', 'roles': ['read-only']},
]


class Command(BaseCommand):
    help = '生成 RBAC 演示账号、用户组和角色绑定'

    def handle(self, *args, **options):
        ensure_builtin_rbac()
        role_map = {role.code: role for role in Role.objects.all()}

        self.stdout.write('正在同步演示用户组...')
        group_map = {}
        for item in DEMO_GROUPS:
            group, _ = UserGroup.objects.update_or_create(
                code=item['code'],
                defaults={
                    'name': item['name'],
                    'description': item['description'],
                },
            )
            group.roles.set([role_map[code] for code in item['roles'] if code in role_map])
            group_map[item['code']] = group

        self.stdout.write('正在同步演示用户...')
        for item in DEMO_USERS:
            user, created = User.objects.get_or_create(
                username=item['username'],
                defaults={
                    'email': item['email'],
                    'first_name': item['first_name'],
                    'last_name': item['last_name'],
                    'is_active': True,
                    'is_staff': item['is_staff'],
                },
            )
            user.email = item['email']
            user.first_name = item['first_name']
            user.last_name = item['last_name']
            user.is_active = True
            user.is_staff = item['is_staff']
            user.set_password(item.get('password') or DEFAULT_PASSWORD)
            user.save()

            user.rbac_roles.set([role_map[code] for code in item['roles'] if code in role_map])
            user.rbac_groups.set([group_map[code] for code in item['groups'] if code in group_map])
            action = '创建' if created else '更新'
            self.stdout.write(self.style.SUCCESS(f"{action}演示用户: {user.username} / {item.get('password') or DEFAULT_PASSWORD}"))

        self.stdout.write(self.style.SUCCESS('RBAC 演示数据已同步完成。'))
