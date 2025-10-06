"""AutoNet Web UI URL Configuration"""
from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', lambda request: redirect('dashboard:index')),
    path('dashboard/', include('dashboard.urls')),
    path('routers/', include('routers.urls')),
    path('configurations/', include('configurations.urls')),
    path('deployments/', include('deployments.urls')),
    path('monitoring/', include('monitoring.urls')),
    path('api/', include('core.api_urls')),
]