from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import PermissionDefinition, Role, UserGroup
from .services import get_user_effective_permissions, is_demo_account


User = get_user_model()


class PermissionDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PermissionDefinition
        fields = '__all__'


class RoleLiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ['id', 'code', 'name']


class GroupLiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserGroup
        fields = ['id', 'code', 'name']


class UserLiteSerializer(serializers.ModelSerializer):
    display_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'is_active', 'display_name']

    def get_display_name(self, obj):
        full_name = f'{obj.first_name} {obj.last_name}'.strip()
        return full_name or obj.username


class RoleSerializer(serializers.ModelSerializer):
    permission_ids = serializers.PrimaryKeyRelatedField(
        queryset=PermissionDefinition.objects.all(), many=True, write_only=True, required=False
    )
    permissions = PermissionDefinitionSerializer(many=True, read_only=True)
    user_count = serializers.SerializerMethodField()
    group_count = serializers.SerializerMethodField()

    class Meta:
        model = Role
        fields = [
            'id', 'code', 'name', 'description', 'is_builtin', 'created_at', 'updated_at',
            'permission_ids', 'permissions', 'user_count', 'group_count',
        ]
        read_only_fields = ['is_builtin', 'created_at', 'updated_at']

    def get_user_count(self, obj):
        return obj.users.count()

    def get_group_count(self, obj):
        return obj.user_groups.count()

    def create(self, validated_data):
        permission_ids = validated_data.pop('permission_ids', [])
        instance = super().create(validated_data)
        if permission_ids is not None:
            instance.permissions.set(permission_ids)
        return instance

    def update(self, instance, validated_data):
        permission_ids = validated_data.pop('permission_ids', None)
        instance = super().update(instance, validated_data)
        if permission_ids is not None:
            instance.permissions.set(permission_ids)
        return instance


class UserGroupSerializer(serializers.ModelSerializer):
    role_ids = serializers.PrimaryKeyRelatedField(queryset=Role.objects.all(), many=True, write_only=True, required=False)
    user_ids = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), many=True, write_only=True, required=False)
    roles = RoleLiteSerializer(many=True, read_only=True)
    users = UserLiteSerializer(many=True, read_only=True)

    class Meta:
        model = UserGroup
        fields = [
            'id', 'code', 'name', 'description', 'is_builtin', 'created_at', 'updated_at',
            'role_ids', 'user_ids', 'roles', 'users',
        ]
        read_only_fields = ['is_builtin', 'created_at', 'updated_at']

    def create(self, validated_data):
        role_ids = validated_data.pop('role_ids', [])
        user_ids = validated_data.pop('user_ids', [])
        instance = super().create(validated_data)
        instance.roles.set(role_ids)
        instance.users.set(user_ids)
        return instance

    def update(self, instance, validated_data):
        role_ids = validated_data.pop('role_ids', None)
        user_ids = validated_data.pop('user_ids', None)
        instance = super().update(instance, validated_data)
        if role_ids is not None:
            instance.roles.set(role_ids)
        if user_ids is not None:
            instance.users.set(user_ids)
        return instance


class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, allow_blank=False)
    role_ids = serializers.PrimaryKeyRelatedField(queryset=Role.objects.all(), many=True, write_only=True, required=False)
    group_ids = serializers.PrimaryKeyRelatedField(queryset=UserGroup.objects.all(), many=True, write_only=True, required=False)
    roles = RoleLiteSerializer(source='rbac_roles', many=True, read_only=True)
    user_groups = GroupLiteSerializer(source='rbac_groups', many=True, read_only=True)
    effective_permissions = serializers.SerializerMethodField()
    display_name = serializers.SerializerMethodField()
    is_demo_account = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name', 'is_active', 'is_staff', 'is_superuser',
            'date_joined', 'last_login', 'password', 'role_ids', 'group_ids', 'roles', 'user_groups',
            'effective_permissions', 'display_name', 'is_demo_account',
        ]
        read_only_fields = ['date_joined', 'last_login', 'is_active', 'is_staff', 'is_superuser']

    def get_effective_permissions(self, obj):
        return sorted(get_user_effective_permissions(obj))

    def get_display_name(self, obj):
        full_name = f'{obj.first_name} {obj.last_name}'.strip()
        return full_name or obj.username

    def get_is_demo_account(self, obj):
        return is_demo_account(obj)

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        role_ids = validated_data.pop('role_ids', [])
        group_ids = validated_data.pop('group_ids', [])
        user = User(**validated_data)
        if password:
            user.set_password(password)
        else:
            raise serializers.ValidationError({'password': '创建用户时必须提供密码。'})
        user.save()
        user.rbac_roles.set(role_ids)
        user.rbac_groups.set(group_ids)
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        role_ids = validated_data.pop('role_ids', None)
        group_ids = validated_data.pop('group_ids', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            validate_password(password)
            instance.set_password(password)
        instance.save()
        if role_ids is not None:
            instance.rbac_roles.set(role_ids)
        if group_ids is not None:
            instance.rbac_groups.set(group_ids)
        return instance


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(trim_whitespace=False)
