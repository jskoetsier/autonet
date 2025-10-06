from django.urls import path
from . import views

app_name = 'deployments'

urlpatterns = [
    path('', views.deployment_list, name='list'),
]