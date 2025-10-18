#!/usr/bin/env python3
"""
AutoNet Custom Exceptions

Centralized exception definitions to avoid circular imports.
"""


class ConfigurationError(Exception):
    """Configuration-related errors"""
    pass


class ValidationError(Exception):
    """Validation-related errors"""
    pass


class APIError(Exception):
    """API-related errors"""
    pass


class DeploymentError(Exception):
    """Deployment-related errors"""
    pass


class PluginError(Exception):
    """Plugin-related errors"""
    pass


class StateError(Exception):
    """State management errors"""
    pass
