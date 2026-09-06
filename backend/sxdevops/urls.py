"""
URL configuration for sxdevops project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include, re_path
from . import frontend_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('rbac.urls')),
    path('api/', include('ops.urls')),
    path('api/sqlaudit/', include('sqlaudit.urls')),
    path('api/aiops/', include('aiops.urls')),
    path('api/', include('eventwall.urls')),
    re_path(r'^(assets/.*|promo/.*|favicon\.svg)$', frontend_views.frontend_asset),
    path('', frontend_views.frontend_index),
    re_path(r'^(?!api/|admin/|ws/).*$' , frontend_views.frontend_index),
]
