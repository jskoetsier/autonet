from django.urls import path
from . import views

app_name = 'configurations'

urlpatterns = [
    path('', views.configuration_list, name='list'),
]