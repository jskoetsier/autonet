from django.shortcuts import render
from core.models import SystemEvent

def event_list(request):
    """List all system events"""
    events = SystemEvent.objects.all()[:100]
    return render(request, 'monitoring/events.html', {'events': events})