from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from . import loki_views

router = DefaultRouter()
router.register(r'hosts', views.HostViewSet)
router.register(r'deployments', views.DeploymentViewSet)
router.register(r'alerts', views.AlertViewSet)
router.register(r'logs', views.LogEntryViewSet)

urlpatterns = [
    path('dashboard/stats/', views.dashboard_stats, name='dashboard-stats'),
    # Loki 代理
    path('loki/labels/', loki_views.loki_labels, name='loki-labels'),
    path('loki/label/<str:label_name>/values/', loki_views.loki_label_values, name='loki-label-values'),
    path('loki/query_range/', loki_views.loki_query_range, name='loki-query-range'),
    path('loki/series/', loki_views.loki_series, name='loki-series'),
    path('', include(router.urls)),
]
