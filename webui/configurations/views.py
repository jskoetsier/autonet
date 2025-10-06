from django.shortcuts import render
from core.models import Configuration

def configuration_list(request):
    """List all configurations"""
    configurations = Configuration.objects.all()[:50]
    return render(request, 'configurations/list.html', {'configurations': configurations})