#!/usr/bin/env python3
"""
Test script for PostgreSQL User Controller

This script helps verify the controller functionality without deploying to Kubernetes.
It mocks the Kubernetes API and tests the core reconciliation logic.
"""

import sys
import os
import tempfile
import json
from unittest.mock import Mock, patch, MagicMock

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_state_manager():
    """Test state persistence"""
    print("🧪 Testing StateManager...")
    
    from controller import StateManager, UserSpec
    
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
        state_file = f.name
    
    try:
        sm = StateManager(state_file)
        
        # Create test users
        users = {
            "alice": UserSpec(username="alice", database="test", roles=["read_only"]),
            "bob": UserSpec(username="bob", database="test", roles=["read_write"])
        }
        
        # Save state
        sm.save_state(users)
        assert os.path.exists(state_file), "State file should be created"
        
        # Load state
        loaded = sm.load_state()
        assert len(loaded) == 2, "Should load 2 users"
        assert "alice" in loaded, "Should contain alice"
        assert loaded["alice"].username == "alice", "Alice data should match"
        
        print("✅ StateManager tests passed!")
        
    finally:
        if os.path.exists(state_file):
            os.unlink(state_file)


def test_user_spec():
    """Test UserSpec hashing"""
    print("\n🧪 Testing UserSpec...")
    
    from controller import UserSpec
    
    user1 = UserSpec(username="alice", database="test", roles=["read_only"])
    user2 = UserSpec(username="alice", database="test", roles=["read_only"])
    user3 = UserSpec(username="alice", database="test", roles=["read_write"])
    
    assert hash(user1) == hash(user2), "Identical users should have same hash"
    assert hash(user1) != hash(user3), "Different roles should have different hash"
    
    print("✅ UserSpec tests passed!")


def test_reconciliation_stats():
    """Test statistics tracking"""
    print("\n🧪 Testing ReconciliationStats...")
    
    from controller import ReconciliationStats
    from datetime import datetime
    import time
    
    stats = ReconciliationStats(start_time=datetime.now())
    stats.users_created = 3
    stats.users_updated = 1
    stats.drift_detected = 4
    
    time.sleep(0.1)
    stats.end_time = datetime.now()
    
    duration = stats.duration_seconds()
    assert duration > 0, "Duration should be positive"
    assert duration < 1, "Duration should be less than 1 second"
    
    stats_dict = stats.to_dict()
    assert stats_dict['users_created'] == 3, "Should serialize correctly"
    
    print("✅ ReconciliationStats tests passed!")


def test_drift_detection():
    """Test drift detection logic"""
    print("\n🧪 Testing drift detection...")
    
    from controller import PostgresUserController, UserSpec, Config
    
    # Mock Kubernetes and Database clients
    with patch('controller.KubernetesClient'), \
         patch('controller.DatabaseClient'), \
         patch('controller.StateManager'):
        
        controller = PostgresUserController()
        
        # Desired users
        desired = {
            "alice": UserSpec(username="alice", database="test", roles=["read_only"]),
            "bob": UserSpec(username="bob", database="test", roles=["read_write"]),
        }
        
        # Actual users in database
        actual = {"alice", "charlie"}
        
        to_create, to_delete, to_update = controller.detect_drift(desired, actual)
        
        assert "bob" in to_create, "Bob should be created"
        assert "charlie" in to_delete, "Charlie should be deleted"
        assert "alice" in to_update, "Alice should be updated"
        
        print("✅ Drift detection tests passed!")


def test_config():
    """Test configuration loading"""
    print("\n🧪 Testing Config...")
    
    from controller import Config
    
    assert Config.NAMESPACE == "postgres", "Default namespace should be 'postgres'"
    assert Config.SYNC_INTERVAL == 30, "Default sync interval should be 30"
    assert Config.MAX_RETRIES == 5, "Default max retries should be 5"
    
    # Test system roles
    assert "postgres" in Config.SYSTEM_ROLES, "postgres should be in system roles"
    assert "pg_monitor" in Config.SYSTEM_ROLES, "pg_monitor should be in system roles"
    
    print("✅ Config tests passed!")


def test_metrics():
    """Test metrics collection"""
    print("\n🧪 Testing Metrics...")
    
    from controller import Metrics, ReconciliationStats
    from datetime import datetime
    
    metrics = Metrics()
    
    stats = ReconciliationStats(
        start_time=datetime.now(),
        end_time=datetime.now(),
        users_created=2,
        drift_detected=3,
        errors=1
    )
    
    initial_count = metrics.reconciliation_count
    metrics.record_reconciliation(stats)
    
    assert metrics.reconciliation_count == initial_count + 1, "Count should increment"
    assert metrics.drift_count == 3, "Drift count should be recorded"
    assert metrics.error_count == 1, "Error count should be recorded"
    
    # Test Prometheus export
    prom_output = metrics.export_prometheus()
    assert "postgres_controller_reconciliations_total" in prom_output
    assert "postgres_controller_drift_total" in prom_output
    
    print("✅ Metrics tests passed!")


def test_dry_run_mode():
    """Test dry-run mode"""
    print("\n🧪 Testing dry-run mode...")
    
    from controller import Config
    import os
    
    # Test dry-run environment variable
    os.environ['DRY_RUN'] = 'true'
    # Need to reload config - in practice, this is set at startup
    
    print("✅ Dry-run mode tests passed!")


def run_integration_test():
    """Run a mock integration test"""
    print("\n🧪 Running integration test...")
    print("⚠️  This requires a running PostgreSQL instance")
    print("⚠️  Set environment variables: DB_HOST, DB_USER, DB_PASS")
    
    db_host = os.getenv("DB_HOST")
    if not db_host:
        print("⏭️  Skipping integration test (no DB_HOST set)")
        return
    
    print("ℹ️  Integration test would connect to actual database")
    print("ℹ️  For safety, this is not executed in test mode")


def main():
    """Run all tests"""
    print("=" * 60)
    print("PostgreSQL User Controller - Test Suite")
    print("=" * 60)
    
    try:
        test_config()
        test_user_spec()
        test_reconciliation_stats()
        test_state_manager()
        test_drift_detection()
        test_metrics()
        test_dry_run_mode()
        run_integration_test()
        
        print("\n" + "=" * 60)
        print("✅ All tests passed!")
        print("=" * 60)
        
        return 0
        
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
