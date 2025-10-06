"""
Dashboard views for AutoNet Web UI
"""

from django.shortcuts import render
from django.http import JsonResponse
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from datetime import timedelta
import json

from core.models import Router, SystemEvent, Deployment
from core.autonet_service import AutoNetService


def index(request):
    """Dashboard home page"""
    autonet_service = AutoNetService()
    
    # Get system status
    status = autonet_service.get_system_status()
    
    # Get recent events
    recent_events = SystemEvent.objects.all()[:10]
    
    # Get router statistics
    total_routers = Router.objects.count()
    online_routers = Router.objects.filter(status='online').count()
    error_routers = Router.objects.filter(status='error').count()
    
    # Get deployment statistics
    recent_deployments = Deployment.objects.filter(
        started_at__gte=timezone.now() - timedelta(hours=24)
    )
    pending_deployments = recent_deployments.filter(status='pending').count()
    
    # Calculate performance metrics for the last 7 days
    week_ago = timezone.now() - timedelta(days=7)
    weekly_events = SystemEvent.objects.filter(timestamp__gte=week_ago)
    
    daily_stats = {}
    for i in range(7):
        day = timezone.now() - timedelta(days=i)
        day_str = day.strftime('%Y-%m-%d')
        day_events = weekly_events.filter(
            timestamp__date=day.date()
        )
        daily_stats[day_str] = {
            'total': day_events.count(),
            'errors': day_events.filter(success=False).count(),
            'deployments': day_events.filter(event_type__contains='deployment').count()
        }
    
    context = {
        'total_routers': total_routers,
        'active_routers': online_routers,
        'error_routers': error_routers,
        'pending_deployments': pending_deployments,
        'recent_events': recent_events,
        'recent_errors': weekly_events.filter(success=False).count(),
        'daily_stats': json.dumps(daily_stats),
        'status': status,
    }
    
    return render(request, 'dashboard/index.html', context)


@require_http_methods(["POST"])
def generate_configs(request):
    """API endpoint to generate configurations"""
    try:
        autonet_service = AutoNetService()
        
        # Get scope from request
        data = json.loads(request.body) if request.body else {}
        scope = data.get('scope', 'all')
        
        success, stdout, stderr = autonet_service.generate_configurations(scope)
        
        if success:
            messages.success(request, 'Configurations generated successfully')
            return JsonResponse({
                'success': True,
                'message': 'Configurations generated successfully',
                'output': stdout
            })
        else:
            messages.error(request, f'Configuration generation failed: {stderr}')
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


@require_http_methods(["POST"])
def deploy_all(request):
    """API endpoint to deploy to all routers"""
    try:
        autonet_service = AutoNetService()
        
        routers = Router.objects.filter(status__in=['online', 'unknown'])
        results = []
        
        for router in routers:
            success, stdout, stderr = autonet_service.deploy_to_router(router.name)
            results.append({
                'router': router.name,
                'success': success,
                'output': stdout,
                'error': stderr
            })
        
        successful = sum(1 for r in results if r['success'])
        total = len(results)
        
        if successful == total:
            messages.success(request, f'Successfully deployed to all {total} routers')
        elif successful > 0:
            messages.warning(request, f'Deployed to {successful} of {total} routers')
        else:
            messages.error(request, 'All deployments failed')
        
        return JsonResponse({
            'success': successful > 0,
            'results': results,
            'summary': f'{successful}/{total} successful'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@require_http_methods(["POST"])
def validate_configs(request):
    """API endpoint to validate configurations"""
    try:
        autonet_service = AutoNetService()
        
        success, stdout, stderr = autonet_service.validate_configurations()
        
        if success:
            messages.success(request, 'Configuration validation passed')
            return JsonResponse({
                'success': True,
                'message': 'Validation passed',
                'output': stdout
            })
        else:
            messages.error(request, f'Configuration validation failed: {stderr}')
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


@require_http_methods(["POST"])
def sync_routers(request):
    """API endpoint to sync routers from configuration"""
    try:
        autonet_service = AutoNetService()
        count = autonet_service.sync_routers()
        
        messages.success(request, f'Synchronized {count} routers from configuration')
        return JsonResponse({
            'success': True,
            'message': f'Synchronized {count} routers',
            'count': count
        })
        
    except Exception as e:
        messages.error(request, f'Router synchronization failed: {str(e)}')
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


def system_status(request):
    """API endpoint to get current system status"""
    try:
        autonet_service = AutoNetService()
        status = autonet_service.get_system_status()
        
        return JsonResponse({
            'success': True,
            'status': status
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })