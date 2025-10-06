"""
Router views for AutoNet Web UI
"""

from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.contrib import messages
from django.views.decorators.http import require_http_methods

from core.models import Router, Configuration, Deployment
from core.autonet_service import AutoNetService


def router_list(request):
    """List all routers"""
    routers = Router.objects.all()
    
    context = {
        'routers': routers,
        'total_routers': routers.count(),
        'online_routers': routers.filter(status='online').count(),
        'offline_routers': routers.filter(status='offline').count(),
        'error_routers': routers.filter(status='error').count(),
    }
    
    return render(request, 'routers/list.html', context)


def router_detail(request, router_id):
    """Router detail view"""
    router = get_object_or_404(Router, pk=router_id)
    
    # Get recent configurations
    recent_configs = router.configurations.all()[:10]
    
    # Get recent deployments
    recent_deployments = router.deployments.all()[:10]
    
    context = {
        'router': router,
        'recent_configs': recent_configs,
        'recent_deployments': recent_deployments,
    }
    
    return render(request, 'routers/detail.html', context)


@require_http_methods(["POST"])
def deploy_to_router(request, router_id):
    """Deploy configuration to specific router"""
    try:
        router = get_object_or_404(Router, pk=router_id)
        autonet_service = AutoNetService()
        
        success, stdout, stderr = autonet_service.deploy_to_router(router.name)
        
        if success:
            messages.success(request, f'Successfully deployed to {router.name}')
            return JsonResponse({
                'success': True,
                'message': f'Deployed to {router.name}',
                'output': stdout
            })
        else:
            messages.error(request, f'Deployment to {router.name} failed: {stderr}')
            return JsonResponse({
                'success': False,
                'error': stderr,
                'output': stdout
            })
            
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })