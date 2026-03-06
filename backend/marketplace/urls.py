from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register('templates', views.ServiceTemplateViewSet)
router.register('deployments', views.ServiceDeploymentViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('deploy/', views.deploy_service_view, name='marketplace-deploy'),
]
