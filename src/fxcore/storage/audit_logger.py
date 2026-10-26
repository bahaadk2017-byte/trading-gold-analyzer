"""Append-only audit event logger with integrity protection."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Union

from fxcore.contracts import Provenance
from fxcore.environments import Environment


class AuditEvent:
    """Immutable audit event with integrity protection."""

    def __init__(
        self,
        event_type: str,
        environment: Environment,
        provenance: Provenance,
        payload: Dict[str, Any],
        previous_event_hash: Optional[str] = None
    ):
        self.event_id = str(uuid.uuid4())
        self.timestamp_utc = datetime.now(timezone.utc).isoformat()
        self.event_type = event_type
        self.environment = environment.value
        self.provenance = provenance
        self.payload = payload
        self.previous_event_hash = previous_event_hash
        self.payload_hash = self._compute_payload_hash()
        self.event_hash = self._compute_event_hash()

    def _compute_payload_hash(self) -> str:
        """Compute SHA-256 hash of the payload."""
        payload_json = json.dumps(self.payload, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(payload_json.encode('utf-8')).hexdigest()

    def _compute_event_hash(self) -> str:
        """Compute SHA-256 hash of the entire event for chaining."""
        event_data = {
            'event_id': self.event_id,
            'timestamp_utc': self.timestamp_utc,
            'event_type': self.event_type,
            'environment': self.environment,
            'provenance': {
                'source': self.provenance.source,
                'timestamp_utc': self.provenance.retrieved_at_utc.isoformat(),
                'latency_ms': self.provenance.latency_ms
            },
            'payload_hash': self.payload_hash,
            'previous_event_hash': self.previous_event_hash
        }
        event_json = json.dumps(event_data, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(event_json.encode('utf-8')).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary for serialization."""
        return {
            'event_id': self.event_id,
            'timestamp_utc': self.timestamp_utc,
            'event_type': self.event_type,
            'environment': self.environment,
            'provenance': {
                'source': self.provenance.source,
                'timestamp_utc': self.provenance.retrieved_at_utc.isoformat(),
                'latency_ms': self.provenance.latency_ms
            },
            'payload': self.payload,
            'payload_hash': self.payload_hash,
            'previous_event_hash': self.previous_event_hash,
            'event_hash': self.event_hash
        }

    def to_json(self) -> str:
        """Convert event to JSON string."""
        return json.dumps(self.to_dict(), separators=(',', ':'))


class AuditLogger:
    """Append-only audit logger with file rotation and integrity protection."""

    def __init__(self, log_dir: Union[str, Path] = "audit_logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._current_file_handle = None
        self._current_file_path = None
        self._last_event_hash = None
        self._initialize_current_file()

    def _initialize_current_file(self) -> None:
        """Initialize or rotate to the current log file."""
        # Close existing file if open
        if self._current_file_handle:
            self._current_file_handle.close()

        # Determine current date for log file
        current_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        self._current_file_path = self.log_dir / f"audit_{current_date}.jsonl"

        # Open file for appending
        self._current_file_handle = open(
            self._current_file_path,
            'a',
            encoding='utf-8'
        )

        # If this is a new file, no previous hash
        # If file exists, we'll compute the last hash on first write
        self._last_event_hash = None

    def _rotate_if_needed(self) -> None:
        """Rotate to new file if date has changed."""
        current_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        expected_path = self.log_dir / f"audit_{current_date}.jsonl"

        if self._current_file_path != expected_path:
            self._initialize_current_file()

    def _compute_last_event_hash(self) -> Optional[str]:
        """Compute hash of the last event in the current file."""
        if not self._current_file_path.exists():
            return None

        try:
            with open(self._current_file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                if not lines:
                    return None
                last_line = lines[-1].strip()
                if not last_line:
                    return None
                last_event = json.loads(last_line)
                return last_event.get('event_hash')
        except (json.JSONDecodeError, IndexError):
            return None

    def log_event(
        self,
        event_type: str,
        environment: Environment,
        provenance: Provenance,
        payload: Dict[str, Any]
    ) -> str:
        """
        Log an audit event with integrity protection.

        Args:
            event_type: Type of event (e.g., 'agent_decision', 'data_received')
            environment: Execution environment
            provenance: Data provenance information
            payload: Event-specific data

        Returns:
            Event ID of the logged event
        """
        # Rotate file if needed
        self._rotate_if_needed()

        # Get last event hash for chaining
        if self._last_event_hash is None:
            self._last_event_hash = self._compute_last_event_hash()

        # Create event
        event = AuditEvent(
            event_type=event_type,
            environment=environment,
            provenance=provenance,
            payload=payload,
            previous_event_hash=self._last_event_hash
        )

        # Write event to file
        json_line = event.to_json()
        self._current_file_handle.write(json_line + '\n')
        self._current_file_handle.flush()

        # Update last event hash for chaining
        self._last_event_hash = event.event_hash

        return event.event_id

    def compress_old_logs(self, days_to_keep: int = 90) -> None:
        """
        Compress log files older than specified days.

        Args:
            days_to_keep: Number of days to keep uncompressed
        """
        from datetime import timedelta

        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_to_keep)

        for log_file in self.log_dir.glob("audit_*.jsonl"):
            # Extract date from filename
            try:
                date_str = log_file.stem.split('_')[1]  # audit_YYYY-MM-DD.jsonl
                file_date = datetime.strptime(date_str, '%Y-%m-%d').replace(tzinfo=timezone.utc)

                if file_date < cutoff_date:
                    # Compress the file
                    compressed_file = log_file.with_suffix('.jsonl.gz')
                    with open(log_file, 'rb') as f_in:
                        with gzip.open(compressed_file, 'wb') as f_out:
                            f_out.writelines(f_in)
                    # Remove uncompressed file
                    log_file.unlink()
            except (IndexError, ValueError):
                # Skip files that don't match expected pattern
                continue

    def verify_integrity(self) -> bool:
        """
        Verify integrity of all audit logs by checking hash chains.

        Returns:
            True if all chains are valid, False otherwise
        """
        for log_file in sorted(self.log_dir.glob("audit_*.jsonl")):
            if not self._verify_file_integrity(log_file):
                return False

        # Also check compressed files
        for log_file in sorted(self.log_dir.glob("audit_*.jsonl.gz")):
            if not self._verify_file_integrity(log_file):
                return False

        return True

    def _verify_file_integrity(self, file_path: Path) -> bool:
        """Verify integrity of a single log file (compressed or uncompressed)."""
        open_func = gzip.open if str(file_path).endswith('.gz') else open
        mode = 'rt' if str(file_path).endswith('.gz') else 'r'

        try:
            with open_func(file_path, mode, encoding='utf-8') as f:
                previous_hash = None
                line_num = 0

                for line in f:
                    line_num += 1
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        event_dict = json.loads(line)
                    except json.JSONDecodeError:
                        return False  # Invalid JSON

                    # Check previous hash matches
                    if event_dict.get('previous_event_hash') != previous_hash:
                        return False  # Chain broken

                    # Recompute the recorded event hash without creating a new event.
                    event_data = {
                        'event_id': event_dict['event_id'],
                        'timestamp_utc': event_dict['timestamp_utc'],
                        'event_type': event_dict['event_type'],
                        'environment': event_dict['environment'],
                        'provenance': event_dict['provenance'],
                        'payload_hash': event_dict['payload_hash'],
                        'previous_event_hash': event_dict['previous_event_hash'],
                    }
                    event_json = json.dumps(event_data, sort_keys=True, separators=(',', ':'))
                    event_hash = hashlib.sha256(event_json.encode('utf-8')).hexdigest()
                    if event_hash != event_dict.get('event_hash'):
                        return False  # Hash mismatch

                    previous_hash = event_dict.get('event_hash')

                return True  # File is valid

        except Exception:
            return False  # Error reading file

    def close(self) -> None:
        """Close the current file handle."""
        if self._current_file_handle:
            self._current_file_handle.close()
            self._current_file_handle = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# Global logger instance
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    """Get or create the global audit logger instance."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger


def log_audit_event(
    event_type: str,
    environment: Environment,
    provenance: Provenance,
    payload: Dict[str, Any]
) -> str:
    """
    Convenience function to log an audit event using the global logger.

    Args:
        event_type: Type of event
        environment: Execution environment
        provenance: Data provenance
        payload: Event data

    Returns:
        Event ID of the logged event
    """
    return get_audit_logger().log_event(event_type, environment, provenance, payload)