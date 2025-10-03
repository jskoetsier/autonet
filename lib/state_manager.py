#!/usr/bin/env python3
"""
AutoNet State Management System

Database-backed state management with event tracking, generation history,
and performance monitoring.
"""

import os
import sys
import sqlite3
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass, asdict
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class EventType(Enum):
    """Types of events that can be tracked"""
    GENERATION_START = "generation_start"
    GENERATION_SUCCESS = "generation_success"
    GENERATION_FAILURE = "generation_failure"
    DEPLOYMENT_START = "deployment_start"
    DEPLOYMENT_SUCCESS = "deployment_success"
    DEPLOYMENT_FAILURE = "deployment_failure"
    VALIDATION_SUCCESS = "validation_success"
    VALIDATION_FAILURE = "validation_failure"
    API_CALL_SUCCESS = "api_call_success"
    API_CALL_FAILURE = "api_call_failure"
    CONFIG_RELOAD = "config_reload"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class StateEvent:
    """State event data structure"""
    id: Optional[int] = None
    timestamp: Optional[datetime] = None
    event_type: EventType = EventType.INFO
    component: str = "autonet"
    message: str = ""
    details: Dict[str, Any] = None
    duration_ms: Optional[int] = None
    success: bool = True

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
        if self.details is None:
            self.details = {}
        if isinstance(self.event_type, str):
            self.event_type = EventType(self.event_type)


@dataclass
class GenerationRecord:
    """Configuration generation record"""
    id: Optional[int] = None
    timestamp: Optional[datetime] = None
    config_hash: str = ""
    peer_count: int = 0
    filter_count: int = 0
    duration_ms: int = 0
    memory_peak_mb: float = 0.0
    success: bool = True
    error_message: str = ""
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
        if self.metadata is None:
            self.metadata = {}


@dataclass
class DeploymentRecord:
    """Configuration deployment record"""
    id: Optional[int] = None
    generation_id: Optional[int] = None
    timestamp: Optional[datetime] = None
    router: str = ""
    config_hash: str = ""
    deployment_method: str = "ssh"
    duration_ms: int = 0
    success: bool = True
    error_message: str = ""
    validation_passed: bool = True
    rollback_required: bool = False

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


class StateManager:
    """
    Database-backed state management system

    Features:
    - Event tracking with detailed metadata
    - Generation history with performance metrics
    - Deployment tracking with rollback support
    - Configuration change tracking
    - Performance monitoring and analytics
    - Automatic cleanup and retention policies
    """

    def __init__(self, database_path: str = None, config: Dict[str, Any] = None):
        self.config = config or {}

        # Database configuration
        if database_path:
            self.db_path = Path(database_path)
        else:
            default_path = self.config.get('state', {}).get('database', {}).get('path', '/var/lib/autonet/state.db')
            self.db_path = Path(default_path)

        # Ensure database directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Retention settings
        retention_config = self.config.get('state', {}).get('retention', {})
        self.max_generations = retention_config.get('generations', 100)
        self.max_days = retention_config.get('days', 30)
        self.cleanup_frequency = retention_config.get('cleanup_frequency', 'daily')

        # Event tracking settings
        events_config = self.config.get('state', {}).get('events', {})
        self.track_generations = events_config.get('track_generations', True)
        self.track_deployments = events_config.get('track_deployments', True)
        self.track_errors = events_config.get('track_errors', True)
        self.track_performance = events_config.get('track_performance', True)

        # Initialize database
        self._init_database()

        # Track last cleanup time
        self._last_cleanup = None

    def _init_database(self) -> None:
        """Initialize SQLite database with required tables"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("PRAGMA foreign_keys = ON")

                # Events table
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        event_type TEXT NOT NULL,
                        component TEXT NOT NULL,
                        message TEXT,
                        details TEXT,  -- JSON
                        duration_ms INTEGER,
                        success BOOLEAN DEFAULT 1
                    )
                """)

                # Generations table
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS generations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        config_hash TEXT NOT NULL,
                        peer_count INTEGER DEFAULT 0,
                        filter_count INTEGER DEFAULT 0,
                        duration_ms INTEGER DEFAULT 0,
                        memory_peak_mb REAL DEFAULT 0.0,
                        success BOOLEAN DEFAULT 1,
                        error_message TEXT,
                        metadata TEXT  -- JSON
                    )
                """)

                # Deployments table
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS deployments (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        generation_id INTEGER,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        router TEXT NOT NULL,
                        config_hash TEXT NOT NULL,
                        deployment_method TEXT DEFAULT 'ssh',
                        duration_ms INTEGER DEFAULT 0,
                        success BOOLEAN DEFAULT 1,
                        error_message TEXT,
                        validation_passed BOOLEAN DEFAULT 1,
                        rollback_required BOOLEAN DEFAULT 0,
                        FOREIGN KEY (generation_id) REFERENCES generations (id)
                    )
                """)

                # Create indexes for performance
                conn.execute("CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_generations_timestamp ON generations(timestamp)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_deployments_timestamp ON deployments(timestamp)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_deployments_router ON deployments(router)")

                conn.commit()

            logger.info(f"State database initialized: {self.db_path}")

        except Exception as e:
            logger.error(f"Failed to initialize state database: {e}")
            raise

    def track_event(self, event: StateEvent) -> int:
        """
        Track a state event

        Args:
            event: StateEvent to track

        Returns:
            Event ID
        """
        if not self._should_track_event(event.event_type):
            return 0

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    INSERT INTO events (timestamp, event_type, component, message, details, duration_ms, success)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    event.timestamp.isoformat(),
                    event.event_type.value,
                    event.component,
                    event.message,
                    json.dumps(event.details) if event.details else None,
                    event.duration_ms,
                    event.success
                ))

                event_id = cursor.lastrowid
                conn.commit()

                logger.debug(f"Tracked event: {event.event_type.value} (ID: {event_id})")
                return event_id

        except Exception as e:
            logger.error(f"Failed to track event: {e}")
            return 0

    def track_generation(self, generation: GenerationRecord) -> int:
        """
        Track a configuration generation

        Args:
            generation: GenerationRecord to track

        Returns:
            Generation ID
        """
        if not self.track_generations:
            return 0

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    INSERT INTO generations (timestamp, config_hash, peer_count, filter_count,
                                          duration_ms, memory_peak_mb, success, error_message, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    generation.timestamp.isoformat(),
                    generation.config_hash,
                    generation.peer_count,
                    generation.filter_count,
                    generation.duration_ms,
                    generation.memory_peak_mb,
                    generation.success,
                    generation.error_message,
                    json.dumps(generation.metadata) if generation.metadata else None
                ))

                generation_id = cursor.lastrowid
                conn.commit()

                # Track corresponding event
                if generation.success:
                    event = StateEvent(
                        event_type=EventType.GENERATION_SUCCESS,
                        component="peering_filters",
                        message=f"Generated configuration for {generation.peer_count} peers",
                        details={
                            "generation_id": generation_id,
                            "peer_count": generation.peer_count,
                            "filter_count": generation.filter_count,
                            "duration_ms": generation.duration_ms,
                            "memory_peak_mb": generation.memory_peak_mb
                        },
                        duration_ms=generation.duration_ms
                    )
                else:
                    event = StateEvent(
                        event_type=EventType.GENERATION_FAILURE,
                        component="peering_filters",
                        message=f"Generation failed: {generation.error_message}",
                        details={"generation_id": generation_id},
                        success=False
                    )

                self.track_event(event)

                logger.info(f"Tracked generation: ID {generation_id}")
                return generation_id

        except Exception as e:
            logger.error(f"Failed to track generation: {e}")
            return 0

    def track_deployment(self, deployment: DeploymentRecord) -> int:
        """
        Track a configuration deployment

        Args:
            deployment: DeploymentRecord to track

        Returns:
            Deployment ID
        """
        if not self.track_deployments:
            return 0

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    INSERT INTO deployments (generation_id, timestamp, router, config_hash,
                                           deployment_method, duration_ms, success, error_message,
                                           validation_passed, rollback_required)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    deployment.generation_id,
                    deployment.timestamp.isoformat(),
                    deployment.router,
                    deployment.config_hash,
                    deployment.deployment_method,
                    deployment.duration_ms,
                    deployment.success,
                    deployment.error_message,
                    deployment.validation_passed,
                    deployment.rollback_required
                ))

                deployment_id = cursor.lastrowid
                conn.commit()

                # Track corresponding event
                if deployment.success:
                    event = StateEvent(
                        event_type=EventType.DEPLOYMENT_SUCCESS,
                        component="update-routers",
                        message=f"Deployed configuration to {deployment.router}",
                        details={
                            "deployment_id": deployment_id,
                            "router": deployment.router,
                            "method": deployment.deployment_method,
                            "duration_ms": deployment.duration_ms,
                            "validation_passed": deployment.validation_passed
                        },
                        duration_ms=deployment.duration_ms
                    )
                else:
                    event = StateEvent(
                        event_type=EventType.DEPLOYMENT_FAILURE,
                        component="update-routers",
                        message=f"Deployment to {deployment.router} failed: {deployment.error_message}",
                        details={
                            "deployment_id": deployment_id,
                            "router": deployment.router,
                            "rollback_required": deployment.rollback_required
                        },
                        success=False
                    )

                self.track_event(event)

                logger.info(f"Tracked deployment: ID {deployment_id} to {deployment.router}")
                return deployment_id

        except Exception as e:
            logger.error(f"Failed to track deployment: {e}")
            return 0

    def get_recent_events(self, limit: int = 100, event_type: EventType = None) -> List[StateEvent]:
        """Get recent events, optionally filtered by type"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                if event_type:
                    cursor = conn.execute("""
                        SELECT id, timestamp, event_type, component, message, details, duration_ms, success
                        FROM events
                        WHERE event_type = ?
                        ORDER BY timestamp DESC
                        LIMIT ?
                    """, (event_type.value, limit))
                else:
                    cursor = conn.execute("""
                        SELECT id, timestamp, event_type, component, message, details, duration_ms, success
                        FROM events
                        ORDER BY timestamp DESC
                        LIMIT ?
                    """, (limit,))

                events = []
                for row in cursor.fetchall():
                    event = StateEvent(
                        id=row[0],
                        timestamp=datetime.fromisoformat(row[1]),
                        event_type=EventType(row[2]),
                        component=row[3],
                        message=row[4],
                        details=json.loads(row[5]) if row[5] else {},
                        duration_ms=row[6],
                        success=bool(row[7])
                    )
                    events.append(event)

                return events

        except Exception as e:
            logger.error(f"Failed to get recent events: {e}")
            return []

    def get_recent_generations(self, limit: int = 50) -> List[GenerationRecord]:
        """Get recent configuration generations"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT id, timestamp, config_hash, peer_count, filter_count,
                           duration_ms, memory_peak_mb, success, error_message, metadata
                    FROM generations
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (limit,))

                generations = []
                for row in cursor.fetchall():
                    generation = GenerationRecord(
                        id=row[0],
                        timestamp=datetime.fromisoformat(row[1]),
                        config_hash=row[2],
                        peer_count=row[3],
                        filter_count=row[4],
                        duration_ms=row[5],
                        memory_peak_mb=row[6],
                        success=bool(row[7]),
                        error_message=row[8] or "",
                        metadata=json.loads(row[9]) if row[9] else {}
                    )
                    generations.append(generation)

                return generations

        except Exception as e:
            logger.error(f"Failed to get recent generations: {e}")
            return []

    def get_deployment_history(self, router: str = None, limit: int = 50) -> List[DeploymentRecord]:
        """Get deployment history, optionally filtered by router"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                if router:
                    cursor = conn.execute("""
                        SELECT id, generation_id, timestamp, router, config_hash,
                               deployment_method, duration_ms, success, error_message,
                               validation_passed, rollback_required
                        FROM deployments
                        WHERE router = ?
                        ORDER BY timestamp DESC
                        LIMIT ?
                    """, (router, limit))
                else:
                    cursor = conn.execute("""
                        SELECT id, generation_id, timestamp, router, config_hash,
                               deployment_method, duration_ms, success, error_message,
                               validation_passed, rollback_required
                        FROM deployments
                        ORDER BY timestamp DESC
                        LIMIT ?
                    """, (limit,))

                deployments = []
                for row in cursor.fetchall():
                    deployment = DeploymentRecord(
                        id=row[0],
                        generation_id=row[1],
                        timestamp=datetime.fromisoformat(row[2]),
                        router=row[3],
                        config_hash=row[4],
                        deployment_method=row[5],
                        duration_ms=row[6],
                        success=bool(row[7]),
                        error_message=row[8] or "",
                        validation_passed=bool(row[9]),
                        rollback_required=bool(row[10])
                    )
                    deployments.append(deployment)

                return deployments

        except Exception as e:
            logger.error(f"Failed to get deployment history: {e}")
            return []

    def get_performance_stats(self, days: int = 7) -> Dict[str, Any]:
        """Get performance statistics for the last N days"""
        try:
            since = datetime.now() - timedelta(days=days)

            with sqlite3.connect(self.db_path) as conn:
                # Generation stats
                cursor = conn.execute("""
                    SELECT COUNT(*) as total,
                           AVG(duration_ms) as avg_duration,
                           MAX(duration_ms) as max_duration,
                           AVG(memory_peak_mb) as avg_memory,
                           MAX(memory_peak_mb) as max_memory,
                           SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful
                    FROM generations
                    WHERE timestamp >= ?
                """, (since.isoformat(),))

                gen_stats = cursor.fetchone()

                # Deployment stats
                cursor = conn.execute("""
                    SELECT COUNT(*) as total,
                           AVG(duration_ms) as avg_duration,
                           SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful,
                           COUNT(DISTINCT router) as routers
                    FROM deployments
                    WHERE timestamp >= ?
                """, (since.isoformat(),))

                deploy_stats = cursor.fetchone()

                # Error stats
                cursor = conn.execute("""
                    SELECT event_type, COUNT(*) as count
                    FROM events
                    WHERE timestamp >= ? AND success = 0
                    GROUP BY event_type
                    ORDER BY count DESC
                """, (since.isoformat(),))

                error_stats = dict(cursor.fetchall())

                return {
                    'period_days': days,
                    'generations': {
                        'total': gen_stats[0] or 0,
                        'avg_duration_ms': round(gen_stats[1] or 0, 2),
                        'max_duration_ms': gen_stats[2] or 0,
                        'avg_memory_mb': round(gen_stats[3] or 0, 2),
                        'max_memory_mb': round(gen_stats[4] or 0, 2),
                        'success_rate': round((gen_stats[5] or 0) / max(gen_stats[0] or 1, 1) * 100, 2)
                    },
                    'deployments': {
                        'total': deploy_stats[0] or 0,
                        'avg_duration_ms': round(deploy_stats[1] or 0, 2),
                        'success_rate': round((deploy_stats[2] or 0) / max(deploy_stats[0] or 1, 1) * 100, 2),
                        'routers_count': deploy_stats[3] or 0
                    },
                    'errors': error_stats
                }

        except Exception as e:
            logger.error(f"Failed to get performance stats: {e}")
            return {}

    def cleanup_old_data(self) -> Dict[str, int]:
        """Clean up old data based on retention policies"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                # Clean up old events
                cutoff_date = datetime.now() - timedelta(days=self.max_days)
                cursor = conn.execute("DELETE FROM events WHERE timestamp < ?", (cutoff_date.isoformat(),))
                events_deleted = cursor.rowcount

                # Clean up old generations (keep only the latest N)
                cursor = conn.execute("""
                    DELETE FROM generations
                    WHERE id NOT IN (
                        SELECT id FROM generations
                        ORDER BY timestamp DESC
                        LIMIT ?
                    )
                """, (self.max_generations,))
                generations_deleted = cursor.rowcount

                # Clean up orphaned deployments
                cursor = conn.execute("""
                    DELETE FROM deployments
                    WHERE generation_id NOT IN (SELECT id FROM generations)
                """)
                deployments_deleted = cursor.rowcount

                conn.commit()

                cleanup_stats = {
                    'events_deleted': events_deleted,
                    'generations_deleted': generations_deleted,
                    'deployments_deleted': deployments_deleted
                }

                logger.info(f"Cleanup completed: {cleanup_stats}")
                return cleanup_stats

        except Exception as e:
            logger.error(f"Failed to cleanup old data: {e}")
            return {}

    def _should_track_event(self, event_type: EventType) -> bool:
        """Check if event type should be tracked based on configuration"""
        if event_type in [EventType.GENERATION_START, EventType.GENERATION_SUCCESS, EventType.GENERATION_FAILURE]:
            return self.track_generations
        elif event_type in [EventType.DEPLOYMENT_START, EventType.DEPLOYMENT_SUCCESS, EventType.DEPLOYMENT_FAILURE]:
            return self.track_deployments
        elif event_type in [EventType.ERROR, EventType.WARNING]:
            return self.track_errors
        else:
            return True  # Track other events by default

    def export_data(self, output_file: str, format: str = "json") -> bool:
        """Export state data to file"""
        try:
            data = {
                'events': [asdict(event) for event in self.get_recent_events(1000)],
                'generations': [asdict(gen) for gen in self.get_recent_generations(100)],
                'deployments': [asdict(dep) for dep in self.get_deployment_history(limit=100)],
                'stats': self.get_performance_stats(30)
            }

            # Convert datetime objects to strings for JSON serialization
            def datetime_converter(obj):
                if isinstance(obj, datetime):
                    return obj.isoformat()
                return obj

            with open(output_file, 'w') as f:
                if format.lower() == 'json':
                    json.dump(data, f, indent=2, default=datetime_converter)
                else:
                    # Could add other formats (CSV, etc.)
                    raise ValueError(f"Unsupported format: {format}")

            logger.info(f"Exported state data to {output_file}")
            return True

        except Exception as e:
            logger.error(f"Failed to export data: {e}")
            return False


# Global state manager instance
_state_manager: Optional[StateManager] = None


def get_state_manager(database_path: str = None, config: Dict[str, Any] = None) -> StateManager:
    """Get or create global state manager instance"""
    global _state_manager

    if _state_manager is None:
        _state_manager = StateManager(database_path, config)

    return _state_manager


def track_event(event_type: EventType, component: str, message: str,
                details: Dict[str, Any] = None, duration_ms: int = None,
                success: bool = True) -> int:
    """Convenience function to track an event"""
    manager = get_state_manager()
    event = StateEvent(
        event_type=event_type,
        component=component,
        message=message,
        details=details,
        duration_ms=duration_ms,
        success=success
    )
    return manager.track_event(event)


if __name__ == "__main__":
    # CLI interface for state management
    import argparse

    parser = argparse.ArgumentParser(description="AutoNet State Manager")
    parser.add_argument("--database", "-d", help="Database file path")
    parser.add_argument("--events", "-e", type=int, default=50, help="Show recent events")
    parser.add_argument("--generations", "-g", type=int, default=20, help="Show recent generations")
    parser.add_argument("--deployments", "-D", type=int, default=20, help="Show recent deployments")
    parser.add_argument("--stats", "-s", type=int, default=7, help="Show performance stats for N days")
    parser.add_argument("--cleanup", "-c", action="store_true", help="Clean up old data")
    parser.add_argument("--export", help="Export data to file")
    parser.add_argument("--router", "-r", help="Filter deployments by router")

    args = parser.parse_args()

    try:
        manager = get_state_manager(args.database)

        if args.cleanup:
            stats = manager.cleanup_old_data()
            print(f"Cleanup completed: {stats}")

        elif args.export:
            if manager.export_data(args.export):
                print(f"✓ Data exported to {args.export}")
            else:
                print("✗ Export failed")
                sys.exit(1)

        elif args.events:
            events = manager.get_recent_events(args.events)
            print(f"Recent {len(events)} events:")
            for event in events:
                status = "✓" if event.success else "✗"
                print(f"  {status} {event.timestamp.strftime('%Y-%m-%d %H:%M:%S')} "
                     f"[{event.component}] {event.event_type.value}: {event.message}")

        elif args.generations:
            generations = manager.get_recent_generations(args.generations)
            print(f"Recent {len(generations)} generations:")
            for gen in generations:
                status = "✓" if gen.success else "✗"
                duration = f"{gen.duration_ms/1000:.1f}s" if gen.duration_ms else "N/A"
                memory = f"{gen.memory_peak_mb:.1f}MB" if gen.memory_peak_mb else "N/A"
                print(f"  {status} {gen.timestamp.strftime('%Y-%m-%d %H:%M:%S')} "
                     f"Peers: {gen.peer_count}, Filters: {gen.filter_count}, "
                     f"Duration: {duration}, Memory: {memory}")

        elif args.deployments:
            deployments = manager.get_deployment_history(args.router, args.deployments)
            print(f"Recent {len(deployments)} deployments:")
            for dep in deployments:
                status = "✓" if dep.success else "✗"
                duration = f"{dep.duration_ms/1000:.1f}s" if dep.duration_ms else "N/A"
                print(f"  {status} {dep.timestamp.strftime('%Y-%m-%d %H:%M:%S')} "
                     f"{dep.router} ({dep.deployment_method}) Duration: {duration}")

        elif args.stats:
            stats = manager.get_performance_stats(args.stats)
            print(f"Performance stats for last {args.stats} days:")
            print(json.dumps(stats, indent=2))

        else:
            # Show summary
            events = manager.get_recent_events(10)
            generations = manager.get_recent_generations(5)
            deployments = manager.get_deployment_history(limit=5)

            print(f"AutoNet State Summary:")
            print(f"  Database: {manager.db_path}")
            print(f"  Recent events: {len(events)}")
            print(f"  Recent generations: {len(generations)}")
            print(f"  Recent deployments: {len(deployments)}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
