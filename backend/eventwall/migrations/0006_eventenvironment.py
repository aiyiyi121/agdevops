from django.db import migrations, models


DEFAULT_ENVIRONMENTS = [
    ('ecommerce-prod', '电商生产环境', ['电商生产']),
    ('ecommerce-test', '电商测试环境', ['电商测试', '电商测试环境-k3s']),
    ('ecommerce-dev', '电商开发环境', ['电商开发']),
]

LEGACY_ENV_CODE_MAP = {
    'prod': 'ecommerce-prod',
    'production': 'ecommerce-prod',
    '生产': 'ecommerce-prod',
    '生产环境': 'ecommerce-prod',
    'test': 'ecommerce-test',
    'testing': 'ecommerce-test',
    '测试': 'ecommerce-test',
    '测试环境': 'ecommerce-test',
    'dev': 'ecommerce-dev',
    'development': 'ecommerce-dev',
    '开发': 'ecommerce-dev',
    '开发环境': 'ecommerce-dev',
}

DEFAULT_ENV_NAMES = {
    'prod': '电商生产环境',
    'production': '电商生产环境',
    'test': '电商测试环境',
    'testing': '电商测试环境',
    'stage': '预发环境',
    'staging': '预发环境',
    'dev': '电商开发环境',
    'development': '电商开发环境',
}


def seed_event_environments(apps, schema_editor):
    event_record_model = apps.get_model('eventwall', 'EventRecord')
    event_environment_model = apps.get_model('eventwall', 'EventEnvironment')
    alias_map = {}
    for index, (code, name, aliases) in enumerate(DEFAULT_ENVIRONMENTS, start=1):
        event_environment_model.objects.update_or_create(
            code=code,
            defaults={
                'name': name,
                'aliases': aliases,
                'sort_order': index * 10,
            },
        )
        for value in [code, name, *aliases]:
            alias_map[str(value).strip().lower()] = code
    alias_map.update(LEGACY_ENV_CODE_MAP)
    for old_value, new_value in alias_map.items():
        event_record_model.objects.filter(environment__iexact=old_value).update(environment=new_value)
    values = (
        event_record_model.objects.exclude(environment='')
        .values_list('environment', flat=True)
        .distinct()
        .order_by('environment')
    )
    for index, code in enumerate(values, start=len(DEFAULT_ENVIRONMENTS) + 1):
        code = str(code or '').strip()
        if not code:
            continue
        name = DEFAULT_ENV_NAMES.get(code.lower(), code)
        event_environment_model.objects.get_or_create(
            code=code,
            defaults={
                'name': name,
                'aliases': [] if name == code else [code],
                'sort_order': index * 10,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ('eventwall', '0005_rename_business_line_verbose_to_system'),
    ]

    operations = [
        migrations.CreateModel(
            name='EventEnvironment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(max_length=64, unique=True, verbose_name='环境标识')),
                ('name', models.CharField(max_length=128, verbose_name='环境名称')),
                ('aliases', models.JSONField(blank=True, default=list, verbose_name='环境别名')),
                ('description', models.CharField(blank=True, default='', max_length=255, verbose_name='说明')),
                ('enabled', models.BooleanField(db_index=True, default=True, verbose_name='启用状态')),
                ('sort_order', models.PositiveIntegerField(default=100, verbose_name='排序')),
                ('last_seen_at', models.DateTimeField(blank=True, null=True, verbose_name='最近事件时间')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
            ],
            options={
                'verbose_name': '事件中心环境',
                'verbose_name_plural': '事件中心环境',
                'ordering': ['sort_order', 'code'],
            },
        ),
        migrations.AddIndex(
            model_name='eventenvironment',
            index=models.Index(fields=['enabled', 'sort_order'], name='eventwall_env_enabled_sort_idx'),
        ),
        migrations.RunPython(seed_event_environments, migrations.RunPython.noop),
    ]
