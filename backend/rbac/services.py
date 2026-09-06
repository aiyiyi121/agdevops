import os

from django.contrib.auth import get_user_model
from django.db import transaction

from sxdevops.features import filter_feature_permissions, permission_feature_enabled

from .models import PermissionDefinition, Role, SystemModuleSetting, UserGroup
from .registry import BUILTIN_ROLES, PERMISSION_DEFINITIONS


User = get_user_model()
DEFAULT_ADMIN_USERNAME = 'admin'
DEFAULT_ADMIN_PASSWORD_ENV = 'SXDEVOPS_ADMIN_INITIAL_PASSWORD'
DEFAULT_ADMIN_EMAIL = 'admin@example.com'
DEMO_ACCOUNT_USERNAME = 'demo'
DEMO_ACCOUNT_MUTATION_MESSAGE = '演示账号无实际操作权限。'
SYSTEM_MODULE_CATALOG = [
    {'code': 'dashboard', 'title': '仪表盘', 'required': True, 'description': '平台首页与核心概览入口。', 'sort_order': 10},
    {'code': 'aiops', 'title': 'AIOps', 'required': True, 'description': '智能助手、知识图谱与配置入口。', 'sort_order': 20},
    {'code': 'observability', 'title': '可观测性', 'required': True, 'description': '监控、日志、链路与告警入口。', 'sort_order': 30},
    {'code': 'events', 'title': '事件中心', 'required': True, 'description': '事件流、事件源与分析入口。', 'sort_order': 40},
    {'code': 'tasks', 'title': '任务中心', 'required': True, 'description': '资源、工作台与定时任务入口。', 'sort_order': 50},
    {'code': 'workorders', 'title': '工单系统', 'required': False, 'description': '发布、SQL 审计与事务工单入口。', 'sort_order': 60},
    {'code': 'containers', 'title': '容器管理', 'required': False, 'description': 'K8s 与 Docker 管理入口。', 'sort_order': 70},
    {'code': 'system', 'title': '系统管理', 'required': True, 'description': '用户、审计与模块配置入口。', 'sort_order': 80},
]


@transaction.atomic
def ensure_builtin_rbac():
    permission_by_code = {}
    for index, (code, name, category, description) in enumerate(PERMISSION_DEFINITIONS, start=1):
        if not permission_feature_enabled(code):
            continue
        permission, _ = PermissionDefinition.objects.update_or_create(
            code=code,
            defaults={
                'name': name,
                'category': category,
                'description': description,
                'sort_order': index,
                'is_builtin': True,
            },
        )
        permission_by_code[code] = permission

    for role_data in BUILTIN_ROLES:
        role, _ = Role.objects.update_or_create(
            code=role_data['code'],
            defaults={
                'name': role_data['name'],
                'description': role_data['description'],
                'is_builtin': True,
            },
        )
        codes = role_data['permissions']
        if '*' in codes:
            role.permissions.set(PermissionDefinition.objects.filter(code__in=permission_by_code))
        else:
            role.permissions.set([permission_by_code[code] for code in filter_feature_permissions(codes) if code in permission_by_code])


@transaction.atomic
def ensure_default_superuser():
    if User.objects.filter(is_superuser=True).exists():
        return

    initial_password = os.getenv(DEFAULT_ADMIN_PASSWORD_ENV, '').strip()
    if not initial_password:
        return

    user = User.objects.create_superuser(
        username=DEFAULT_ADMIN_USERNAME,
        email=DEFAULT_ADMIN_EMAIL,
        password=initial_password,
    )
    role = Role.objects.filter(code='platform-admin').first()
    if role:
        role.users.add(user)


def is_demo_account(user):
    return bool(
        getattr(user, 'is_authenticated', False)
        and getattr(user, 'username', '') == DEMO_ACCOUNT_USERNAME
    )


def get_user_direct_roles(user):
    if not getattr(user, 'is_authenticated', False):
        return Role.objects.none()
    return user.rbac_roles.prefetch_related('permissions').all()


def get_user_group_roles(user):
    if not getattr(user, 'is_authenticated', False):
        return Role.objects.none()
    return Role.objects.filter(user_groups__users=user).prefetch_related('permissions').distinct()


def get_user_effective_permissions(user):
    if not getattr(user, 'is_authenticated', False):
        return set()
    if getattr(user, 'is_superuser', False) or is_demo_account(user):
        return set(filter_feature_permissions(PermissionDefinition.objects.values_list('code', flat=True)))

    permission_codes = set(
        PermissionDefinition.objects.filter(roles__users=user).values_list('code', flat=True)
    )
    permission_codes.update(
        PermissionDefinition.objects.filter(roles__user_groups__users=user).values_list('code', flat=True)
    )
    return permission_codes


def user_has_permissions(user, codes):
    codes = [code for code in (codes or []) if code]
    if any(not permission_feature_enabled(code) for code in codes):
        return False
    if not codes:
        return True
    if not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_superuser', False) or is_demo_account(user):
        return True
    granted = get_user_effective_permissions(user)
    return all(code in granted for code in codes)


def get_permission_catalog():
    disabled_codes = [
        code
        for code in PermissionDefinition.objects.values_list('code', flat=True)
        if not permission_feature_enabled(code)
    ]
    return PermissionDefinition.objects.exclude(code__in=disabled_codes).order_by('sort_order', 'code')


def get_builtin_role_catalog():
    return Role.objects.filter(is_builtin=True).order_by('name')


@transaction.atomic
def ensure_system_module_settings():
    existing = {item.code: item for item in SystemModuleSetting.objects.all()}
    for module in SYSTEM_MODULE_CATALOG:
        setting = existing.get(module['code'])
        if setting is None:
            SystemModuleSetting.objects.create(code=module['code'], enabled=True)


def get_system_module_settings():
    ensure_system_module_settings()
    setting_map = {item.code: item for item in SystemModuleSetting.objects.all()}
    items = []
    for module in SYSTEM_MODULE_CATALOG:
        setting = setting_map.get(module['code'])
        items.append({
            'code': module['code'],
            'title': module['title'],
            'description': module['description'],
            'required': module['required'],
            'sort_order': module['sort_order'],
            'enabled': True if setting is None else setting.enabled,
            'updated_by': '' if setting is None else setting.updated_by,
            'updated_at': None if setting is None else setting.updated_at,
        })
    return items


def get_user_summary(user):
    roles = list(Role.objects.filter(users=user).values('id', 'code', 'name'))
    groups = list(UserGroup.objects.filter(users=user).values('id', 'code', 'name'))
    return {
        'roles': roles,
        'groups': groups,
        'effective_permissions': sorted(get_user_effective_permissions(user)),
    }
