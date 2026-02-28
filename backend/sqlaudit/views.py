from rest_framework import viewsets, status
from rest_framework.decorators import api_view, action
from rest_framework.response import Response
from django.utils import timezone

from .models import DataSource, SqlOrder, QueryOrder, SqlCheckResult
from .serializers import (
    DataSourceSerializer, SqlOrderSerializer,
    QueryOrderSerializer, SqlCheckResultSerializer,
)
from . import sql_checker
from . import db_executor


class DataSourceViewSet(viewsets.ModelViewSet):
    """数据源管理"""
    queryset = DataSource.objects.all()
    serializer_class = DataSourceSerializer
    search_fields = ['name', 'host']

    @action(detail=True, methods=['post'])
    def test_connection(self, request, pk=None):
        """测试数据源连通性"""
        ds = self.get_object()
        success, message = db_executor.test_connection(ds)
        return Response({
            'success': success,
            'message': message,
        })

    @action(detail=True, methods=['get'])
    def databases(self, request, pk=None):
        """获取数据源中的数据库列表"""
        ds = self.get_object()
        databases = db_executor.get_databases(ds)
        return Response({'databases': databases})


class SqlOrderViewSet(viewsets.ModelViewSet):
    """SQL 工单管理"""
    queryset = SqlOrder.objects.select_related('datasource').prefetch_related('check_results').all()
    serializer_class = SqlOrderSerializer
    search_fields = ['title', 'submitter', 'sql_content']

    def perform_create(self, serializer):
        order = serializer.save()
        # 提交时自动执行 SQL 检查
        results = sql_checker.check_sql(order.sql_content, order.sql_type)
        for item in results:
            SqlCheckResult.objects.create(
                order=order,
                level=item.level,
                rule_name=item.rule_name,
                message=item.message,
                line_no=item.line_no,
            )

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """审核通过"""
        order = self.get_object()
        if order.status != 'pending':
            return Response(
                {'error': f'当前状态为"{order.get_status_display()}"，不可审核'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        order.status = 'approved'
        order.reviewer = request.data.get('reviewer', 'admin')
        order.review_comment = request.data.get('comment', '')
        order.reviewed_at = timezone.now()
        order.save()
        return Response(SqlOrderSerializer(order).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """审核驳回"""
        order = self.get_object()
        if order.status != 'pending':
            return Response(
                {'error': f'当前状态为"{order.get_status_display()}"，不可驳回'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        order.status = 'rejected'
        order.reviewer = request.data.get('reviewer', 'admin')
        order.review_comment = request.data.get('comment', '')
        order.reviewed_at = timezone.now()
        order.save()
        return Response(SqlOrderSerializer(order).data)

    @action(detail=True, methods=['post'])
    def execute(self, request, pk=None):
        """执行已审核通过的 SQL"""
        order = self.get_object()
        if order.status != 'approved':
            return Response(
                {'error': f'当前状态为"{order.get_status_display()}"，不可执行'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        order.status = 'executing'
        order.save()

        success, affected, duration, log = db_executor.execute_sql(
            order.datasource, order.database, order.sql_content,
        )

        order.status = 'executed' if success else 'failed'
        order.affected_rows = affected
        order.duration_ms = duration
        order.execute_log = log
        order.executed_at = timezone.now()
        order.save()

        return Response(SqlOrderSerializer(order).data)


class QueryOrderViewSet(viewsets.ModelViewSet):
    """查询工单"""
    queryset = QueryOrder.objects.select_related('datasource').all()
    serializer_class = QueryOrderSerializer
    search_fields = ['submitter', 'sql_content']
    http_method_names = ['get', 'post', 'head', 'options']  # 只允许查询和提交

    def create(self, request, *args, **kwargs):
        """提交查询并立即执行"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        datasource_id = request.data.get('datasource')
        database = request.data.get('database', '')
        sql_content = request.data.get('sql_content', '')

        try:
            ds = DataSource.objects.get(id=datasource_id)
        except DataSource.DoesNotExist:
            return Response(
                {'error': '数据源不存在'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 安全检查：只允许 SELECT
        upper = sql_content.strip().upper()
        if not upper.startswith('SELECT') and not upper.startswith('SHOW') and not upper.startswith('DESC'):
            return Response(
                {'error': '查询工单只允许 SELECT / SHOW / DESC 语句'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        success, columns, rows, count, duration, error = db_executor.execute_query(
            ds, database, sql_content,
        )

        # 保存记录
        query_order = serializer.save(
            result_count=count if success else 0,
            duration_ms=duration,
        )

        if not success:
            return Response(
                {'error': error, 'order': QueryOrderSerializer(query_order).data},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({
            'order': QueryOrderSerializer(query_order).data,
            'columns': columns,
            'rows': rows,
            'count': count,
            'duration_ms': duration,
        }, status=status.HTTP_201_CREATED)


@api_view(['POST'])
def sql_check_api(request):
    """独立的 SQL 检查接口（不创建工单）"""
    sql_content = request.data.get('sql_content', '')
    sql_type = request.data.get('sql_type', 'DML')

    if not sql_content.strip():
        return Response(
            {'error': 'SQL 内容不能为空'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    results = sql_checker.check_sql(sql_content, sql_type)
    return Response({
        'results': [item.to_dict() for item in results],
    })
