from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import PermissionDefinition, Role, UserGroup
from .serializers import UserSerializer
from .services import DEMO_ACCOUNT_MUTATION_MESSAGE, ensure_builtin_rbac, get_user_effective_permissions


User = get_user_model()


class RbacPermissionTests(TestCase):
    def setUp(self):
        ensure_builtin_rbac()
        self.dashboard_permission = PermissionDefinition.objects.get(code='ops.dashboard.view')
        self.user_view_permission = PermissionDefinition.objects.get(code='rbac.user.view')

    def test_group_role_grants_effective_permission(self):
        role = Role.objects.create(code='dashboard-viewer', name='Dashboard Viewer')
        role.permissions.add(self.dashboard_permission)
        group = UserGroup.objects.create(code='observers', name='Observers')
        group.roles.add(role)

        user = User.objects.create_user(username='observer', password='Admin@123456')
        group.users.add(user)
        self.client.force_login(user)

        response = self.client.get('/api/dashboard/stats/')
        self.assertEqual(response.status_code, 200)

        denied = self.client.get('/api/hosts/')
        self.assertEqual(denied.status_code, 403)

    def test_view_only_user_cannot_create_users(self):
        role = Role.objects.create(code='user-auditor', name='User Auditor')
        role.permissions.add(self.user_view_permission)

        user = User.objects.create_user(username='auditor', password='Admin@123456')
        role.users.add(user)
        self.client.force_login(user)

        list_response = self.client.get('/api/users/')
        self.assertEqual(list_response.status_code, 200)

        create_response = self.client.post(
            '/api/users/',
            {
                'username': 'blocked-user',
                'password': 'Admin@123456',
                'email': 'blocked@example.com',
            },
        )
        self.assertEqual(create_response.status_code, 403)

    def test_demo_account_has_full_permissions(self):
        demo_user = User.objects.create_user(username='demo', password='Demo#123')
        permissions = get_user_effective_permissions(demo_user)

        self.assertIn('rbac.user.manage', permissions)
        self.assertIn('ops.k8s.manage', permissions)
        self.assertIn('ops.deployment.manage', permissions)

    def test_demo_account_cannot_create_users(self):
        demo_user = User.objects.create_user(username='demo', password='Demo#123')
        self.client.force_login(demo_user)

        response = self.client.post(
            '/api/users/',
            {
                'username': 'blocked-demo-created-user',
                'password': 'Admin@123456',
                'email': 'blocked-demo-created-user@example.com',
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['detail'], DEMO_ACCOUNT_MUTATION_MESSAGE)

    def test_demo_account_cannot_call_custom_write_action(self):
        demo_user = User.objects.create_user(username='demo', password='Demo#123')
        target_user = User.objects.create_user(username='reset-target', password='Admin@123456')
        self.client.force_login(demo_user)

        response = self.client.post(
            f'/api/users/{target_user.id}/reset_password/',
            {'password': 'Admin@654321'},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['detail'], DEMO_ACCOUNT_MUTATION_MESSAGE)

    def test_user_serializer_cannot_assign_privileged_flags(self):
        user = User.objects.create_user(username='ordinary-user', password='Passw0rd!123')
        serializer = UserSerializer(user, data={'is_superuser': True, 'is_staff': True, 'is_active': False}, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()
        user.refresh_from_db()
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_staff)
        self.assertTrue(user.is_active)
