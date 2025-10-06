"""
AutoNet Service for integrating with the AutoNet CLI and backend
"""

import json
import subprocess
import yaml
from pathlib import Path
from django.conf import settings
from django.utils import timezone
from .models import Router, Configuration, Deployment, SystemEvent
import logging

logger = logging.getLogger(__name__)


class AutoNetService:
    """Service class for interacting with AutoNet CLI and managing data"""
    
    def __init__(self):
        self.autonet_cli = settings.AUTONET_CLI_PATH
        self.config_dir = settings.AUTONET_CONFIG_DIR
        self.state_db = settings.AUTONET_STATE_DB
    
    def load_routers_from_config(self):
        """Load router information from AutoNet configuration files"""
        try:
            generic_config_path = self.config_dir / 'generic.yml'
            if not generic_config_path.exists():
                logger.error(f"Generic config not found: {generic_config_path}")
                return []
            
            with open(generic_config_path, 'r') as f:
                config = yaml.safe_load(f)
            
            routers = []
            bgp_config = config.get('bgp', {})
            
            for router_name, router_config in bgp_config.items():
                router_data = {
                    'name': router_name,
                    'fqdn': router_config.get('fqdn', ''),
                    'ipv4': router_config.get('ipv4', ''),
                    'ipv6': router_config.get('ipv6', ''),
                    'vendor': router_config.get('vendor', 'bird'),
                    'graceful_shutdown': router_config.get('graceful_shutdown', False),
                    'maintenance_mode': router_config.get('maintenance_mode', False),
                }
                routers.append(router_data)
            
            return routers
            
        except Exception as e:
            logger.error(f"Error loading routers from config: {e}")
            return []
    
    def sync_routers(self):
        """Synchronize routers from configuration files to database"""
        try:
            config_routers = self.load_routers_from_config()
            synced_count = 0
            
            for router_data in config_routers:
                router, created = Router.objects.get_or_create(
                    name=router_data['name'],
                    defaults=router_data
                )
                
                if not created:
                    # Update existing router
                    for key, value in router_data.items():
                        if key != 'name':
                            setattr(router, key, value)
                    router.save()
                
                synced_count += 1
            
            logger.info(f"Synchronized {synced_count} routers")
            return synced_count
            
        except Exception as e:
            logger.error(f"Error syncing routers: {e}")
            raise
    
    def generate_configurations(self, scope='all', routers=None):
        """Generate configurations using AutoNet CLI"""
        try:
            # Create system event
            event = SystemEvent.objects.create(
                event_type='generation_start',
                component='autonet_web',
                message=f'Starting configuration generation for scope: {scope}',
                details={'scope': scope, 'routers': routers}
            )
            
            # Build command
            cmd = [str(self.autonet_cli), 'generate', scope]
            
            # Execute command
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                timeout=300,  # 5 minute timeout
                cwd=settings.AUTONET_ROOT
            )
            
            success = result.returncode == 0
            
            # Update event
            event.success = success
            event.message = 'Configuration generation completed' if success else 'Configuration generation failed'
            event.details.update({
                'return_code': result.returncode,
                'stdout': result.stdout,
                'stderr': result.stderr
            })
            event.save()
            
            if success:
                # Parse output and create configuration records
                self._process_generation_output(result.stdout)
            
            return success, result.stdout, result.stderr
            
        except subprocess.TimeoutExpired:
            logger.error("Configuration generation timed out")
            return False, "", "Generation timed out after 5 minutes"
        except Exception as e:
            logger.error(f"Error generating configurations: {e}")
            return False, "", str(e)
    
    def deploy_to_router(self, router_name, config_id=None):
        """Deploy configuration to a specific router"""
        try:
            router = Router.objects.get(name=router_name)
            
            # Get the configuration to deploy
            if config_id:
                config = Configuration.objects.get(id=config_id, router=router)
            else:
                config = router.configurations.filter(is_active=True).first()
            
            if not config:
                return False, "", "No configuration found to deploy"
            
            # Create deployment record
            deployment = Deployment.objects.create(
                configuration=config,
                router=router,
                status='pending',
                deployed_by='web_ui'
            )
            
            # Create system event
            SystemEvent.objects.create(
                event_type='deployment_start',
                component='autonet_web',
                message=f'Starting deployment to {router_name}',
                router=router,
                deployment=deployment
            )
            
            # Update router status
            router.status = 'deploying'
            router.save()
            
            # Execute deployment
            cmd = [str(self.autonet_cli), 'deploy', 'push', '--router', router.fqdn]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=180,  # 3 minute timeout
                cwd=settings.AUTONET_ROOT
            )
            
            success = result.returncode == 0
            
            # Update deployment
            deployment.mark_completed(success, result.stderr if not success else '')
            deployment.logs = result.stdout
            deployment.save()
            
            # Update router
            if success:
                router.status = 'online'
                router.last_deployment = timezone.now()
            else:
                router.status = 'error'
            router.save()
            
            # Create completion event
            SystemEvent.objects.create(
                event_type='deployment_success' if success else 'deployment_failure',
                component='autonet_web',
                message=f'Deployment to {router_name} {"completed successfully" if success else "failed"}',
                router=router,
                deployment=deployment,
                success=success,
                details={
                    'return_code': result.returncode,
                    'duration_ms': deployment.duration_ms
                }
            )
            
            return success, result.stdout, result.stderr
            
        except Router.DoesNotExist:
            return False, "", f"Router {router_name} not found"
        except subprocess.TimeoutExpired:
            logger.error(f"Deployment to {router_name} timed out")
            return False, "", "Deployment timed out after 3 minutes"
        except Exception as e:
            logger.error(f"Error deploying to router {router_name}: {e}")
            return False, "", str(e)
    
    def validate_configurations(self):
        """Validate all configurations using AutoNet CLI"""
        try:
            cmd = [str(self.autonet_cli), 'deploy', 'check']
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,  # 2 minute timeout
                cwd=settings.AUTONET_ROOT
            )
            
            success = result.returncode == 0
            
            # Create system event
            SystemEvent.objects.create(
                event_type='validation_success' if success else 'validation_failure',
                component='autonet_web',
                message=f'Configuration validation {"passed" if success else "failed"}',
                success=success,
                details={
                    'return_code': result.returncode,
                    'stdout': result.stdout,
                    'stderr': result.stderr
                }
            )
            
            return success, result.stdout, result.stderr
            
        except subprocess.TimeoutExpired:
            logger.error("Configuration validation timed out")
            return False, "", "Validation timed out after 2 minutes"
        except Exception as e:
            logger.error(f"Error validating configurations: {e}")
            return False, "", str(e)
    
    def get_system_status(self):
        """Get system status information"""
        try:
            # Get router statistics
            total_routers = Router.objects.count()
            online_routers = Router.objects.filter(status='online').count()
            offline_routers = Router.objects.filter(status='offline').count()
            error_routers = Router.objects.filter(status='error').count()
            
            # Get recent events
            recent_events = SystemEvent.objects.filter(
                timestamp__gte=timezone.now() - timezone.timedelta(hours=24)
            )
            recent_errors = recent_events.filter(success=False).count()
            
            # Get deployment statistics
            recent_deployments = Deployment.objects.filter(
                started_at__gte=timezone.now() - timezone.timedelta(hours=24)
            )
            pending_deployments = recent_deployments.filter(status='pending').count()
            
            return {
                'routers': {
                    'total': total_routers,
                    'online': online_routers,
                    'offline': offline_routers,
                    'error': error_routers,
                },
                'events': {
                    'recent_errors': recent_errors,
                },
                'deployments': {
                    'pending': pending_deployments,
                    'recent_total': recent_deployments.count(),
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting system status: {e}")
            return {}
    
    def _process_generation_output(self, output):
        """Process the output from configuration generation and create records"""
        # This would parse the AutoNet CLI output and create Configuration objects
        # For now, we'll just log the output
        logger.info(f"Configuration generation output: {output}")
        
        # TODO: Parse output and create Configuration objects
        # This would depend on the exact format of the AutoNet CLI output