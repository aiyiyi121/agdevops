import requests as http_requests
from django.conf import settings
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status


LOKI_BASE = getattr(settings, 'LOKI_URL', 'http://localhost:3100')
LOKI_TIMEOUT = 30


def _proxy_loki(endpoint, query_params):
    """通用 Loki 代理函数"""
    url = f'{LOKI_BASE}{endpoint}'
    try:
        resp = http_requests.get(url, params=query_params, timeout=LOKI_TIMEOUT)
        resp.raise_for_status()
        return Response(resp.json(), status=resp.status_code)
    except http_requests.ConnectionError:
        return Response(
            {'error': f'无法连接 Loki 服务: {LOKI_BASE}', 'detail': 'connection_refused'},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    except http_requests.Timeout:
        return Response(
            {'error': 'Loki 请求超时', 'detail': 'timeout'},
            status=status.HTTP_504_GATEWAY_TIMEOUT,
        )
    except http_requests.HTTPError as e:
        return Response(
            {'error': f'Loki 返回错误: {e.response.status_code}', 'detail': str(e)},
            status=e.response.status_code,
        )
    except Exception as e:
        return Response(
            {'error': '代理请求异常', 'detail': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(['GET'])
def loki_labels(request):
    """获取 Loki 所有标签名"""
    params = {}
    if request.GET.get('start'):
        params['start'] = request.GET['start']
    if request.GET.get('end'):
        params['end'] = request.GET['end']
    return _proxy_loki('/loki/api/v1/labels', params)


@api_view(['GET'])
def loki_label_values(request, label_name):
    """获取指定标签的所有值"""
    params = {}
    if request.GET.get('start'):
        params['start'] = request.GET['start']
    if request.GET.get('end'):
        params['end'] = request.GET['end']
    return _proxy_loki(f'/loki/api/v1/label/{label_name}/values', params)


@api_view(['GET'])
def loki_query_range(request):
    """执行 LogQL range 查询"""
    params = {}
    for key in ('query', 'start', 'end', 'limit', 'direction', 'step'):
        val = request.GET.get(key)
        if val:
            params[key] = val
    if 'query' not in params:
        return Response(
            {'error': '缺少 query 参数'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return _proxy_loki('/loki/api/v1/query_range', params)


@api_view(['GET'])
def loki_series(request):
    """查询 Loki series 信息"""
    params = {}
    match_values = request.GET.getlist('match[]')
    if match_values:
        params['match[]'] = match_values
    if request.GET.get('start'):
        params['start'] = request.GET['start']
    if request.GET.get('end'):
        params['end'] = request.GET['end']
    return _proxy_loki('/loki/api/v1/series', params)
