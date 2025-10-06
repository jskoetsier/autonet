"""
Router URL configuration
"""

from django.urls import path
from . import views

app_name = 'routers'

urlpatterns = [
    path('', views.router_list, name='list'),
    path('<int:router_id>/', views.router_detail, name='detail'),
    path('<int:router_id>/deploy/', views.deploy_to_router, name='deploy'),
]