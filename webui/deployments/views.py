from django.shortcuts import render
from core.models import Deployment

def deployment_list(request):
    """List all deployments"""
    deployments = Deployment.objects.all()[:50]
    return render(request, 'deployments/list.html', {'deployments': deployments})