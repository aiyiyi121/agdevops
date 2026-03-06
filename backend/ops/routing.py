from django.urls import re_path
from . import ssh_consumer

websocket_urlpatterns = [
    re_path(r'ws/ssh/(?P<host_id>\d+)/$', ssh_consumer.SSHConsumer.as_asgi()),
]
