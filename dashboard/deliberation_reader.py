"""Read-only access to deliberations/*.json for the dashboard.

Never writes, never modifies deliberation records.
Enforces invariants: is_live_agent_communication=false, execution_enabled=false, strategy_promoted=false.
Rejects records with sender/recipient/status/latency_ms (these imply live communication).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DELIBERATIONS_DIR = ROOT / "runs" / "deliberations"

# Deliberation filenames: delib_*.json
_RECORD_ID_RE = re.compile(r"^delib_[A-Za-z0-9_.-]+$")

UTC = timezone.utc

# Forbidden fields that imply live communication
_FORBIDDEN_FIELDS = {"sender", "recipient", "status", "latency_ms", "message_id", "correlation_id"}

# Required invariants for all deliberation records
_REQUIRED_INVARIANTS = {
    "is_live_agent_communication": False,
    "non_authoritative": True,
    "execution_enabled": False,
    "strategy_promoted": False,
}


def _record_id(path: Path) -> str:
    """Extract record ID from filename."""
    return path.stem  # delib_ema_trend_follow_1.0.0_eurusd_is_20261025T120000


def _validate_id(record_id: str) -> bool:
    """Strict validation: only accept delib_* pattern, reject traversal."""
    if not record_id:
        return False
    if ".." in record_id or "/" in record_id or "\\" in record_id:
        return False
    return bool(_RECORD_ID_RE.match(record_id))


def _validate_invariants(record: dict) -> tuple[bool, str | None]:
    """Check that record enforces all required invariants."""
    for key, expected_value in _REQUIRED_INVARIANTS.items():
        actual = record.get(key)
        if actual != expected_value:
            return False, f"invariant violation: {key}={actual}, expected {expected_value}"

    # Check for forbidden fields
    for forbidden in _FORBIDDEN_FIELDS:
        if forbidden in record:
            return False, f"forbidden field present: {forbidden}"

    # Verify mode
    mode = record.get("mode")
    if mode != "static_role_deliberation":
        return False, f"invalid mode: {mode}, expected static_role_deliberation"

    return True, None


def list_deliberations(limit: int = 50) -> list[dict]:
    """Return deliberation summaries sorted newest-first, up to `limit`."""
    summaries: list[dict] = []

    if not DELIBERATIONS_DIR.exists():
        return summaries

    for path in sorted(DELIBERATIONS_DIR.glob("delib_*.json"), reverse=True)[:limit]:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue

        # Validate invariants
        valid, error = _validate_invariants(record)
        if not valid:
            continue  # Skip invalid records

        summaries.append({
            "record_id": _record_id(path),
            "created_at_utc": record.get("created_at_utc"),
            "strategy_name": record.get("strategy_ref", {}).get("name"),
            "strategy_version": record.get("strategy_ref", {}).get("version"),
            "pair": record.get("strategy_ref", {}).get("pair"),
            "split": record.get("backtest_ref", {}).get("split"),
            "environment": record.get("environment"),
            "non_authoritative": True,
            "is_live_agent_communication": False,
            "execution_enabled": False,
        })

    return summaries


def get_deliberation(record_id: str) -> dict | None:
    """Return a specific deliberation by record_id, or None.

    Validates ID strictly. Returns None for:
    - Invalid ID format (traversal, slashes, etc.)
    - Missing file
    - Invalid JSON
    - Invariant violations
    """
    if not _validate_id(record_id):
        return None

    path = DELIBERATIONS_DIR / f"{record_id}.json"
    if not path.exists():
        return None

    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None

    # Validate invariants before returning
    valid, _error = _validate_invariants(record)
    if not valid:
        return None

    # Enrich with record_id
    record["record_id"] = _record_id(path)
    return record


def get_latest_deliberation() -> dict | None:
    """Return the most recent deliberation record, or None."""
    if not DELIBERATIONS_DIR.exists():
        return None

    paths = sorted(DELIBERATIONS_DIR.glob("delib_*.json"), reverse=True)
    if not paths:
        return None

    return get_deliberation(_record_id(paths[0]))
