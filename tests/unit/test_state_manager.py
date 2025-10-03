#!/usr/bin/env python3
"""
Unit tests for AutoNet State Manager
"""

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

# Add lib directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from lib.state_manager import (
    DeploymentRecord,
    EventType,
    GenerationRecord,
    StateEvent,
    StateManager,
)


class TestStateManager(unittest.TestCase):
    """Test cases for StateManager"""

    def setUp(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_state.db"

        # Create state manager with test database
        self.manager = StateManager(str(self.db_path))

    def tearDown(self):
        """Clean up test environment"""
        import shutil

        shutil.rmtree(self.temp_dir)

    def test_database_initialization(self):
        """Test database initialization"""
        self.assertTrue(self.db_path.exists())

        # Check if tables exist
        import sqlite3

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]

            self.assertIn("events", tables)
            self.assertIn("generations", tables)
            self.assertIn("deployments", tables)

    def test_track_event(self):
        """Test event tracking"""
        event = StateEvent(
            event_type=EventType.GENERATION_SUCCESS,
            component="test",
            message="Test event",
            details={"test": "data"},
            duration_ms=1000,
            success=True,
        )

        event_id = self.manager.track_event(event)
        self.assertGreater(event_id, 0)

        # Retrieve and verify
        events = self.manager.get_recent_events(1)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].message, "Test event")
        self.assertEqual(events[0].details["test"], "data")

    def test_track_generation(self):
        """Test generation tracking"""
        generation = GenerationRecord(
            config_hash="test123",
            peer_count=5,
            filter_count=10,
            duration_ms=2000,
            memory_peak_mb=50.5,
            success=True,
            metadata={"test": "metadata"},
        )

        gen_id = self.manager.track_generation(generation)
        self.assertGreater(gen_id, 0)

        # Retrieve and verify
        generations = self.manager.get_recent_generations(1)
        self.assertEqual(len(generations), 1)
        self.assertEqual(generations[0].peer_count, 5)
        self.assertEqual(generations[0].config_hash, "test123")

    def test_track_deployment(self):
        """Test deployment tracking"""
        deployment = DeploymentRecord(
            generation_id=1,
            router="test-router",
            config_hash="test123",
            deployment_method="ssh",
            duration_ms=3000,
            success=True,
            validation_passed=True,
        )

        dep_id = self.manager.track_deployment(deployment)
        self.assertGreater(dep_id, 0)

        # Retrieve and verify
        deployments = self.manager.get_deployment_history(limit=1)
        self.assertEqual(len(deployments), 1)
        self.assertEqual(deployments[0].router, "test-router")
        self.assertTrue(deployments[0].success)

    def test_performance_stats(self):
        """Test performance statistics"""
        # Add some test data
        self.manager.track_generation(
            GenerationRecord(
                config_hash="test1",
                peer_count=3,
                duration_ms=1500,
                memory_peak_mb=30.0,
                success=True,
            )
        )

        self.manager.track_generation(
            GenerationRecord(
                config_hash="test2",
                peer_count=7,
                duration_ms=2500,
                memory_peak_mb=45.0,
                success=True,
            )
        )

        stats = self.manager.get_performance_stats(7)

        self.assertEqual(stats["generations"]["total"], 2)
        self.assertEqual(stats["generations"]["success_rate"], 100.0)
        self.assertEqual(stats["generations"]["avg_duration_ms"], 2000.0)

    def test_cleanup_old_data(self):
        """Test cleanup of old data"""
        # Create old event
        old_event = StateEvent(
            event_type=EventType.INFO,
            component="test",
            message="Old event",
            timestamp=datetime.now()
            - timedelta(days=40),  # Older than default retention
        )

        self.manager.track_event(old_event)

        # Cleanup
        stats = self.manager.cleanup_old_data()

        self.assertGreater(stats["events_deleted"], 0)

    def test_event_filtering_by_type(self):
        """Test event filtering by type"""
        # Track different event types
        self.manager.track_event(
            StateEvent(
                event_type=EventType.GENERATION_SUCCESS,
                component="test",
                message="Success event",
            )
        )

        self.manager.track_event(
            StateEvent(
                event_type=EventType.GENERATION_FAILURE,
                component="test",
                message="Failure event",
            )
        )

        # Get only success events
        success_events = self.manager.get_recent_events(
            10, EventType.GENERATION_SUCCESS
        )
        self.assertEqual(len(success_events), 1)
        self.assertEqual(success_events[0].message, "Success event")

        # Get only failure events
        failure_events = self.manager.get_recent_events(
            10, EventType.GENERATION_FAILURE
        )
        self.assertEqual(len(failure_events), 1)
        self.assertEqual(failure_events[0].message, "Failure event")


if __name__ == "__main__":
    unittest.main()
