"""
WebSocket Consumer for SSH Shell (WebShell)
Uses paramiko to create an interactive SSH session and forwards I/O over WebSocket.
"""
import json
import threading
import logging
import paramiko
from channels.generic.websocket import WebsocketConsumer

logger = logging.getLogger(__name__)


class SSHConsumer(WebsocketConsumer):
    ssh_client = None
    ssh_channel = None
    _reading = False

    def connect(self):
        self.host_id = self.scope['url_route']['kwargs']['host_id']
        self.accept()

        # 获取 Host 信息
        from ops.models import Host
        try:
            host = Host.objects.get(pk=self.host_id)
        except Host.DoesNotExist:
            self.send(text_data=json.dumps({'type': 'error', 'message': '主机不存在'}))
            self.close()
            return

        # 建立 SSH 连接
        try:
            self.ssh_client = paramiko.SSHClient()
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.ssh_client.connect(
                hostname=host.ip_address,
                port=host.ssh_port or 22,
                username=host.ssh_user or 'root',
                password=host.ssh_password or None,
                timeout=15,
            )
            self.ssh_channel = self.ssh_client.invoke_shell(
                term='xterm-256color',
                width=120,
                height=40,
            )
            self.ssh_channel.settimeout(0.0)

            # 启动读取线程
            self._reading = True
            self._read_thread = threading.Thread(target=self._read_ssh_output, daemon=True)
            self._read_thread.start()

            self.send(text_data=json.dumps({
                'type': 'connected',
                'message': f'已连接到 {host.hostname} ({host.ip_address})',
            }))

        except Exception as e:
            logger.exception('SSH connection failed')
            self.send(text_data=json.dumps({
                'type': 'error',
                'message': f'SSH 连接失败: {str(e)}',
            }))
            self.close()

    def disconnect(self, close_code):
        self._reading = False
        if self.ssh_channel:
            try:
                self.ssh_channel.close()
            except Exception:
                pass
        if self.ssh_client:
            try:
                self.ssh_client.close()
            except Exception:
                pass

    def receive(self, text_data=None, bytes_data=None):
        """接收前端输入并发送到 SSH"""
        if text_data and self.ssh_channel:
            try:
                data = json.loads(text_data)
                if data.get('type') == 'input':
                    self.ssh_channel.send(data['data'])
                elif data.get('type') == 'resize':
                    cols = data.get('cols', 120)
                    rows = data.get('rows', 40)
                    self.ssh_channel.resize_pty(width=cols, height=rows)
            except Exception as e:
                logger.error(f'Error processing input: {e}')

    def _read_ssh_output(self):
        """后台线程：持续读取 SSH 输出并发送到 WebSocket"""
        import time
        while self._reading:
            try:
                if self.ssh_channel and self.ssh_channel.recv_ready():
                    data = self.ssh_channel.recv(4096)
                    if data:
                        self.send(text_data=json.dumps({
                            'type': 'output',
                            'data': data.decode('utf-8', errors='replace'),
                        }))
                else:
                    time.sleep(0.02)
            except Exception as e:
                if self._reading:
                    logger.error(f'SSH read error: {e}')
                    self.send(text_data=json.dumps({
                        'type': 'error',
                        'message': f'连接断开: {str(e)}',
                    }))
                break
