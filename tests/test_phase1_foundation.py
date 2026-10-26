"""Tests for Phase 1 foundation and contracts."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import pytest

# Ensure fxcore package is importable
try:
    from fxcore.contracts import Provenance
except ImportError:
    # Add the src directory to sys.path if not already present
    src_path = Path(__file__).parent.parent / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))
    from fxcore.contracts import Provenance
from fxcore.environments import Environment, validate_environment_compatibility
from fxcore.storage.audit_logger import AuditLogger, AuditEvent
from fxcore.storage.integrity_verifier import IntegrityVerifier
from fxcore.storage.schema_registry import SchemaRegistry, validate_payload


def test_environment_labels_and_colors():
    """Test environment Arabic labels and display colors."""
    assert Environment.LIVE.arabic_label() == "مباشر"
    assert Environment.SIMULATED.arabic_label() == "محاكاة"
    assert Environment.LIVE.display_color() == "#DC2626"
    assert Environment.SIMULATED.display_color() == "#16A34A"


def test_environment_compatibility():
    """Test environment compatibility rules (fail-closed)."""
    # Same environment is compatible
    assert validate_environment_compatibility(Environment.SIMULATED, Environment.SIMULATED) is True

    # Experimental data never flows to decisions
    assert validate_environment_compatibility(Environment.EXPERIMENTAL, Environment.LIVE) is False
    assert validate_environment_compatibility(Environment.EXPERIMENTAL, Environment.SIMULATED) is False

    # Backtest cannot flow to live/demo
    assert validate_environment_compatibility(Environment.BACKTEST, Environment.LIVE) is False
    assert validate_environment_compatibility(Environment.BACKTEST, Environment.DEMO) is False


def test_audit_logger_and_integrity():
    """Test audit logging with hash chain integrity verification."""
    with tempfile.TemporaryDirectory() as temp_dir:
        logger = AuditLogger(log_dir=temp_dir)

        prov = Provenance(
            source="MT5",
            license="test-license",
            retrieved_at_utc=datetime.now(timezone.utc),
            latency_ms=12,
            completeness=1.0,
            approved_for_decisions=False
        )

        # Log a few events
        event_id_1 = logger.log_event(
            event_type="test_event_1",
            environment=Environment.SIMULATED,
            provenance=prov,
            payload={"action": "start"}
        )

        event_id_2 = logger.log_event(
            event_type="test_event_2",
            environment=Environment.SIMULATED,
            provenance=prov,
            payload={"action": "complete"}
        )

        logger.close()

        # Verify integrity
        verifier = IntegrityVerifier(log_dir=temp_dir)
        is_valid, errors = verifier.verify_all_logs()

        assert is_valid is True
        assert len(errors) == 0
        assert logger.verify_integrity() is True

        stats = verifier.get_log_statistics()
        assert stats['total_events'] == 2


def test_schema_registry_validation():
    """Test JSON schema validation for telemetry and messages."""
    registry = SchemaRegistry()

    # Valid telemetry payload
    valid_telemetry = {
        "agent_id": "agent-001",
        "agent_name": "risk-guardian",
        "status": "IDLE",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "latency_ms": 15,
        "performance_metrics": {
            "win_rate": 0.65,
            "avg_profit_pips": 12.5,
            "total_trades": 42
        },
        "environment": "simulated"
    }

    is_valid, err = registry.validate("agent_telemetry", valid_telemetry)
    assert is_valid is True
    assert err is None

    # Invalid telemetry payload (missing required field)
    invalid_telemetry = {
        "agent_id": "agent-001",
        # missing agent_name
        "status": "IDLE",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "environment": "simulated"
    }

    is_valid, err = registry.validate("agent_telemetry", invalid_telemetry)
    assert is_valid is False
    assert err is not None
