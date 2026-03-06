"""
初始化 12 个内置中间件服务模板
用法: python manage.py seed_templates
"""
from django.core.management.base import BaseCommand
from marketplace.models import ServiceTemplate

TEMPLATES = [
    {
        'name': 'MySQL',
        'icon': 'mysql',
        'category': 'database',
        'description': '关系型数据库',
        'versions': ['8.0', '5.7'],
        'sort_order': 1,
        'env_schema': [
            {'key': 'port', 'label': '端口', 'default': '3306', 'required': True},
            {'key': 'root_password', 'label': 'Root 密码', 'default': 'mysql@2024', 'required': True},
        ],
        'docker_compose_template': '''version: "3.8"
services:
  mysql:
    image: mysql:{{version}}
    container_name: agdevops_mysql
    restart: always
    ports:
      - "{{port}}:3306"
    environment:
      MYSQL_ROOT_PASSWORD: "{{root_password}}"
      TZ: Asia/Shanghai
    volumes:
      - mysql_data:/var/lib/mysql
    command: --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci
volumes:
  mysql_data:
''',
    },
    {
        'name': 'Redis',
        'icon': 'redis',
        'category': 'cache',
        'description': '内存数据库/缓存',
        'versions': ['7.0', '6.2'],
        'sort_order': 2,
        'env_schema': [
            {'key': 'port', 'label': '端口', 'default': '6379', 'required': True},
            {'key': 'password', 'label': '密码', 'default': 'redis@2024', 'required': False},
        ],
        'docker_compose_template': '''version: "3.8"
services:
  redis:
    image: redis:{{version}}-alpine
    container_name: agdevops_redis
    restart: always
    ports:
      - "{{port}}:6379"
    command: redis-server --requirepass "{{password}}" --appendonly yes
    volumes:
      - redis_data:/data
volumes:
  redis_data:
''',
    },
    {
        'name': 'PostgreSQL',
        'icon': 'postgresql',
        'category': 'database',
        'description': '关系型数据库',
        'versions': ['16', '15', '14'],
        'sort_order': 3,
        'env_schema': [
            {'key': 'port', 'label': '端口', 'default': '5432', 'required': True},
            {'key': 'postgres_password', 'label': '密码', 'default': 'pg@2024', 'required': True},
        ],
        'docker_compose_template': '''version: "3.8"
services:
  postgres:
    image: postgres:{{version}}
    container_name: agdevops_postgres
    restart: always
    ports:
      - "{{port}}:5432"
    environment:
      POSTGRES_PASSWORD: "{{postgres_password}}"
      TZ: Asia/Shanghai
    volumes:
      - pg_data:/var/lib/postgresql/data
volumes:
  pg_data:
''',
    },
    {
        'name': 'Nginx',
        'icon': 'nginx',
        'category': 'middleware',
        'description': 'Web 服务器/反向代理',
        'versions': ['1.25', '1.24'],
        'sort_order': 4,
        'env_schema': [
            {'key': 'http_port', 'label': 'HTTP 端口', 'default': '80', 'required': True},
            {'key': 'https_port', 'label': 'HTTPS 端口', 'default': '443', 'required': False},
        ],
        'docker_compose_template': '''version: "3.8"
services:
  nginx:
    image: nginx:{{version}}
    container_name: agdevops_nginx
    restart: always
    ports:
      - "{{http_port}}:80"
      - "{{https_port}}:443"
    volumes:
      - nginx_conf:/etc/nginx/conf.d
      - nginx_html:/usr/share/nginx/html
volumes:
  nginx_conf:
  nginx_html:
''',
    },
    {
        'name': 'Jenkins',
        'icon': 'jenkins',
        'category': 'cicd',
        'description': '持续集成/持续部署',
        'versions': ['lts', 'latest'],
        'sort_order': 5,
        'env_schema': [
            {'key': 'port', 'label': '端口', 'default': '8080', 'required': True},
        ],
        'docker_compose_template': '''version: "3.8"
services:
  jenkins:
    image: jenkins/jenkins:{{version}}
    container_name: agdevops_jenkins
    restart: always
    ports:
      - "{{port}}:8080"
      - "50000:50000"
    volumes:
      - jenkins_home:/var/jenkins_home
    environment:
      TZ: Asia/Shanghai
volumes:
  jenkins_home:
''',
    },
    {
        'name': 'GitLab',
        'icon': 'gitlab',
        'category': 'cicd',
        'description': '代码托管平台',
        'versions': ['latest', '16.8'],
        'sort_order': 6,
        'env_schema': [
            {'key': 'http_port', 'label': 'HTTP 端口', 'default': '8929', 'required': True},
            {'key': 'ssh_port', 'label': 'SSH 端口', 'default': '2224', 'required': True},
        ],
        'docker_compose_template': '''version: "3.8"
services:
  gitlab:
    image: gitlab/gitlab-ce:{{version}}
    container_name: agdevops_gitlab
    restart: always
    ports:
      - "{{http_port}}:80"
      - "{{ssh_port}}:22"
    volumes:
      - gitlab_config:/etc/gitlab
      - gitlab_logs:/var/log/gitlab
      - gitlab_data:/var/opt/gitlab
    shm_size: "256m"
volumes:
  gitlab_config:
  gitlab_logs:
  gitlab_data:
''',
    },
    {
        'name': 'Grafana',
        'icon': 'grafana',
        'category': 'monitoring',
        'description': '可视化面板',
        'versions': ['latest', '10.3'],
        'sort_order': 7,
        'env_schema': [
            {'key': 'port', 'label': '端口', 'default': '3000', 'required': True},
        ],
        'docker_compose_template': '''version: "3.8"
services:
  grafana:
    image: grafana/grafana:{{version}}
    container_name: agdevops_grafana
    restart: always
    ports:
      - "{{port}}:3000"
    volumes:
      - grafana_data:/var/lib/grafana
    environment:
      TZ: Asia/Shanghai
volumes:
  grafana_data:
''',
    },
    {
        'name': 'Elasticsearch',
        'icon': 'elasticsearch',
        'category': 'monitoring',
        'description': '搜索引擎',
        'versions': ['8.12', '7.17'],
        'sort_order': 8,
        'env_schema': [
            {'key': 'port', 'label': 'HTTP 端口', 'default': '9200', 'required': True},
            {'key': 'java_opts', 'label': 'JVM 参数', 'default': '-Xms512m -Xmx512m', 'required': False},
        ],
        'docker_compose_template': '''version: "3.8"
services:
  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:{{version}}.0
    container_name: agdevops_elasticsearch
    restart: always
    ports:
      - "{{port}}:9200"
    environment:
      - discovery.type=single-node
      - ES_JAVA_OPTS={{java_opts}}
      - xpack.security.enabled=false
      - TZ=Asia/Shanghai
    volumes:
      - es_data:/usr/share/elasticsearch/data
volumes:
  es_data:
''',
    },
    {
        'name': 'Loki',
        'icon': 'loki',
        'category': 'monitoring',
        'description': '日志聚合系统',
        'versions': ['2.9.4', '2.8.0'],
        'sort_order': 9,
        'env_schema': [
            {'key': 'port', 'label': '端口', 'default': '3100', 'required': True},
        ],
        'docker_compose_template': '''version: "3.8"
services:
  loki:
    image: grafana/loki:{{version}}
    container_name: agdevops_loki
    restart: always
    ports:
      - "{{port}}:3100"
    command: -config.file=/etc/loki/local-config.yaml
    volumes:
      - loki_data:/loki
volumes:
  loki_data:
''',
    },
    {
        'name': 'JumpServer',
        'icon': 'jumpserver',
        'category': 'security',
        'description': '开源堡垒机',
        'versions': ['latest', 'v3.10'],
        'sort_order': 10,
        'env_schema': [
            {'key': 'port', 'label': 'HTTP 端口', 'default': '80', 'required': True},
            {'key': 'secret_key', 'label': 'Secret Key', 'default': 'agdevops_jumpserver_secret', 'required': True},
        ],
        'docker_compose_template': '''version: "3.8"
services:
  jumpserver:
    image: jumpserver/jms_all:{{version}}
    container_name: agdevops_jumpserver
    restart: always
    ports:
      - "{{port}}:80"
      - "2222:2222"
    environment:
      SECRET_KEY: "{{secret_key}}"
      BOOTSTRAP_TOKEN: "{{secret_key}}"
      TZ: Asia/Shanghai
    volumes:
      - js_data:/opt/jumpserver/data
volumes:
  js_data:
''',
    },
    {
        'name': 'Nacos',
        'icon': 'nacos',
        'category': 'middleware',
        'description': '注册中心/配置中心',
        'versions': ['v2.3.0', 'v2.2.3', 'latest'],
        'sort_order': 11,
        'env_schema': [
            {'key': 'port', 'label': '端口', 'default': '8848', 'required': True},
            {'key': 'mode', 'label': '运行模式', 'default': 'standalone', 'required': True},
        ],
        'docker_compose_template': '''version: "3.8"
services:
  nacos:
    image: nacos/nacos-server:{{version}}
    container_name: agdevops_nacos
    restart: always
    ports:
      - "{{port}}:8848"
      - "9848:9848"
      - "9849:9849"
    environment:
      MODE: "{{mode}}"
      TZ: Asia/Shanghai
    volumes:
      - nacos_logs:/home/nacos/logs
volumes:
  nacos_logs:
''',
    },
    {
        'name': 'XXL-Job',
        'icon': 'xxljob',
        'category': 'middleware',
        'description': '分布式任务调度平台',
        'versions': ['2.4.0', '2.3.1'],
        'sort_order': 12,
        'env_schema': [
            {'key': 'port', 'label': '端口', 'default': '8088', 'required': True},
            {'key': 'db_host', 'label': 'MySQL 地址', 'default': '127.0.0.1', 'required': True},
            {'key': 'db_port', 'label': 'MySQL 端口', 'default': '3306', 'required': True},
            {'key': 'db_user', 'label': 'MySQL 用户', 'default': 'root', 'required': True},
            {'key': 'db_password', 'label': 'MySQL 密码', 'default': 'root', 'required': True},
        ],
        'docker_compose_template': '''version: "3.8"
services:
  xxl-job-admin:
    image: xuxueli/xxl-job-admin:{{version}}
    container_name: agdevops_xxljob
    restart: always
    ports:
      - "{{port}}:8080"
    environment:
      PARAMS: >-
        --spring.datasource.url=jdbc:mysql://{{db_host}}:{{db_port}}/xxl_job?useUnicode=true&characterEncoding=UTF-8&autoReconnect=true&serverTimezone=Asia/Shanghai
        --spring.datasource.username={{db_user}}
        --spring.datasource.password={{db_password}}
      TZ: Asia/Shanghai
    volumes:
      - xxljob_data:/data/applogs
volumes:
  xxljob_data:
''',
    },
]


class Command(BaseCommand):
    help = '初始化工具市场模板数据（12 个中间件）'

    def handle(self, *args, **options):
        created_count = 0
        updated_count = 0
        for tpl_data in TEMPLATES:
            obj, created = ServiceTemplate.objects.update_or_create(
                name=tpl_data['name'],
                defaults=tpl_data,
            )
            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(self.style.SUCCESS(
            f'完成! 新增 {created_count} 个, 更新 {updated_count} 个模板'
        ))
