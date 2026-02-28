from django.apps import AppConfig


class SqlauditConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'sqlaudit'
    verbose_name = 'SQL 审计'
