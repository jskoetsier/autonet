"""
Core models for AutoNet Web UI
"""

from django.db import models
from django.utils import timezone
import hashlib


class Router(models.Model):
    """Router model representing a BGP router in the network"""
    name = models.CharField(max_length=100, unique=True)
    fqdn = models.CharField(max_length=255)
    ipv4 = models.GenericIPAddressField(protocol='IPv4')
    ipv6 = models.GenericIPAddressField(protocol='IPv6', null=True, blank=True)
    vendor = models.CharField(max_length=50, choices=[
        ('bird', 'BIRD 1.x'),
        ('bird2', 'BIRD 2.x'),
        ('cisco', 'Cisco IOS/XR'),
        ('frr', 'FRRouting'),
        ('juniper', 'Juniper JunOS'),
        ('openbgpd', 'OpenBGPD'),
    ])
    status = models.CharField(max_length=20, choices=[
        ('online', 'Online'),
        ('offline', 'Offline'),
        ('deploying', 'Deploying'),
        ('error', 'Error'),
        ('unknown', 'Unknown'),
    ], default='unknown')
    graceful_shutdown = models.BooleanField(default=False)
    maintenance_mode = models.BooleanField(default=False)
    last_deployment = models.DateTimeField(null=True, blank=True)
    last_seen = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.fqdn})"

    @property
    def is_online(self):
        return self.status == 'online'

    @property
    def needs_deployment(self):
        if not self.last_deployment:
            return True
        # Check if there are newer configurations
        latest_config = self.configurations.filter(is_active=True).first()
        return latest_config and latest_config.created_at > self.last_deployment


class Configuration(models.Model):
    """Configuration model for storing generated router configurations"""
    router = models.ForeignKey(Router, on_delete=models.CASCADE, related_name='configurations')
    config_hash = models.CharField(max_length=64, db_index=True)
    content = models.TextField()
    peer_count = models.IntegerField(default=0)
    filter_count = models.IntegerField(default=0)
    generation_duration_ms = models.IntegerField(default=0)
    is_active = models.BooleanField(default=False)
    is_validated = models.BooleanField(default=False)
    validation_errors = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Config for {self.router.name} - {self.config_hash[:8]}"

    def save(self, *args, **kwargs):
        if not self.config_hash:
            self.config_hash = hashlib.sha256(self.content.encode()).hexdigest()
        super().save(*args, **kwargs)

    @property
    def size_bytes(self):
        return len(self.content.encode('utf-8'))


class Deployment(models.Model):
    """Deployment model for tracking configuration deployments to routers"""
    configuration = models.ForeignKey(Configuration, on_delete=models.CASCADE, related_name='deployments')
    router = models.ForeignKey(Router, on_delete=models.CASCADE, related_name='deployments')
    deployment_method = models.CharField(max_length=50, choices=[
        ('ssh', 'SSH'),
        ('api', 'API'),
        ('manual', 'Manual'),
    ], default='ssh')
    status = models.CharField(max_length=20, choices=[
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('rolled_back', 'Rolled Back'),
    ], default='pending')
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.IntegerField(default=0)
    logs = models.TextField(blank=True)
    error_message = models.TextField(blank=True)
    validation_passed = models.BooleanField(default=True)
    rollback_required = models.BooleanField(default=False)
    deployed_by = models.CharField(max_length=100, default='system')

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f"Deployment to {self.router.name} - {self.status}"

    @property
    def is_running(self):
        return self.status in ['pending', 'running']

    @property
    def is_successful(self):
        return self.status == 'success'

    def mark_completed(self, success=True, error_message=''):
        self.completed_at = timezone.now()
        if self.started_at:
            duration = self.completed_at - self.started_at
            self.duration_ms = int(duration.total_seconds() * 1000)
        self.status = 'success' if success else 'failed'
        if error_message:
            self.error_message = error_message
        self.save()


class SystemEvent(models.Model):
    """System event model for tracking AutoNet operations"""
    event_type = models.CharField(max_length=50, choices=[
        ('generation_start', 'Generation Started'),
        ('generation_success', 'Generation Success'),
        ('generation_failure', 'Generation Failed'),
        ('deployment_start', 'Deployment Started'),
        ('deployment_success', 'Deployment Success'),
        ('deployment_failure', 'Deployment Failed'),
        ('validation_success', 'Validation Success'),
        ('validation_failure', 'Validation Failed'),
        ('error', 'Error'),
        ('warning', 'Warning'),
        ('info', 'Info'),
    ])
    component = models.CharField(max_length=100, default='autonet')
    message = models.TextField()
    details = models.JSONField(default=dict, blank=True)
    router = models.ForeignKey(Router, on_delete=models.SET_NULL, null=True, blank=True)
    deployment = models.ForeignKey(Deployment, on_delete=models.SET_NULL, null=True, blank=True)
    duration_ms = models.IntegerField(null=True, blank=True)
    success = models.BooleanField(default=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.event_type} - {self.message[:50]}"

    @property
    def is_error(self):
        return self.event_type in ['generation_failure', 'deployment_failure', 'validation_failure', 'error']

    @property
    def is_warning(self):
        return self.event_type == 'warning'