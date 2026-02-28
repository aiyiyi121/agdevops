from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'datasources', views.DataSourceViewSet)
router.register(r'orders', views.SqlOrderViewSet)
router.register(r'queries', views.QueryOrderViewSet)

urlpatterns = [
    path('check/', views.sql_check_api, name='sql-check'),
    path('', include(router.urls)),
]
