"""
Dashboard URL configuration
"""

from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.index, name='index'),
    path('generate/', views.generate_configs, name='generate_configs'),
    path('deploy/', views.deploy_all, name='deploy_all'),
    path('validate/', views.validate_configs, name='validate_configs'),
    path('sync-routers/', views.sync_routers, name='sync_routers'),
    path('status/', views.system_status, name='system_status'),
]