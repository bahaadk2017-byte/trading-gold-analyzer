"""Integrity verification service for audit logs."""

from __future__ import annotations

import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple, Optional

from fxcore.storage.audit_logger import AuditLogger


class IntegrityVerifier:
    """Service for verifying integrity of audit logs."""

    def __init__(self, log_dir: str = "audit_logs"):
        self.log_dir = Path(log_dir)
        if not self.log_dir.exists():
            raise ValueError(f"Log directory does not exist: {log_dir}")

    def verify_all_logs(self) -> Tuple[bool, List[str]]:
        """
        Verify integrity of all audit logs.

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []
        is_valid = True

        # Check uncompressed logs
        for log_file in sorted(self.log_dir.glob("audit_*.jsonl")):
            valid, file_errors = self._verify_file(log_file)
            if not valid:
                is_valid = False
                errors.extend([f"{log_file.name}: {err}" for err in file_errors])

        # Check compressed logs
        for log_file in sorted(self.log_dir.glob("audit_*.jsonl.gz")):
            valid, file_errors = self._verify_file(log_file)
            if not valid:
                is_valid = False
                errors.extend([f"{log_file.name}: {err}" for err in file_errors])

        return is_valid, errors

    def _verify_file(self, file_path: Path) -> Tuple[bool, List[str]]:
        """
        Verify integrity of a single log file.

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []

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
                    except json.JSONDecodeError as e:
                        errors.append(f"Line {line_num}: Invalid JSON - {e}")
                        continue

                    # Check required fields
                    required_fields = ['event_id', 'timestamp_utc', 'event_type', 'environment',
                                     'provenance', 'payload', 'payload_hash', 'previous_event_hash', 'event_hash']
                    missing_fields = [field for field in required_fields if field not in event_dict]
                    if missing_fields:
                        errors.append(f"Line {line_num}: Missing fields - {missing_fields}")
                        continue

                    # Check previous hash matches
                    if event_dict['previous_event_hash'] != previous_hash:
                        errors.append(f"Line {line_num}: Hash chain broken")
                        # Continue checking to capture all errors, but break chain
                        previous_hash = None  # Reset to prevent cascade errors

                    # Recompute and verify payload hash
                    try:
                        payload_copy = event_dict['payload'].copy()
                        payload_json = json.dumps(payload_copy, sort_keys=True, separators=(',', ':'))
                        computed_payload_hash = hashlib.sha256(payload_json.encode('utf-8')).hexdigest()
                        if computed_payload_hash != event_dict['payload_hash']:
                            errors.append(f"Line {line_num}: Payload hash mismatch")
                    except Exception as e:
                        errors.append(f"Line {line_num}: Payload hash computation failed - {e}")

                    # Recompute and verify event hash
                    try:
                        event_data = {
                            'event_id': event_dict['event_id'],
                            'timestamp_utc': event_dict['timestamp_utc'],
                            'event_type': event_dict['event_type'],
                            'environment': event_dict['environment'],
                            'provenance': {
                                'source': event_dict['provenance']['source'],
                                'timestamp_utc': event_dict['provenance']['timestamp_utc'],
                                'latency_ms': event_dict['provenance']['latency_ms']
                            },
                            'payload_hash': event_dict['payload_hash'],
                            'previous_event_hash': event_dict['previous_event_hash']
                        }
                        event_json = json.dumps(event_data, sort_keys=True, separators=(',', ':'))
                        computed_event_hash = hashlib.sha256(event_json.encode('utf-8')).hexdigest()
                        if computed_event_hash != event_dict['event_hash']:
                            errors.append(f"Line {line_num}: Event hash mismatch")
                    except Exception as e:
                        errors.append(f"Line {line_num}: Event hash computation failed - {e}")

                    previous_hash = event_dict.get('event_hash')

        except Exception as e:
            errors.append(f"File read error: {e}")
            return False, errors

        return len(errors) == 0, errors

    def verify_recent_logs(self, hours: int = 24) -> Tuple[bool, List[str]]:
        """
        Verify integrity of logs from the last N hours.

        Args:
            hours: Number of hours to look back

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        from datetime import timedelta

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        errors = []
        is_valid = True

        # Check all log files (we could optimize by date, but simplicity first)
        is_valid, errors = self.verify_all_logs()
        return is_valid, errors

    def get_log_statistics(self) -> dict:
        """
        Get statistics about the audit logs.

        Returns:
            Dictionary with log statistics
        """
        stats = {
            'total_files': 0,
            'total_events': 0,
            'date_range': {
                'earliest': None,
                'latest': None
            },
            'compression_ratio': 0.0
        }

        uncompressed_size = 0
        compressed_size = 0

        # Process uncompressed logs
        for log_file in sorted(self.log_dir.glob("audit_*.jsonl")):
            stats['total_files'] += 1
            file_size = log_file.stat().st_size
            uncompressed_size += file_size

            # Count events in file
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    line_count = sum(1 for line in f if line.strip())
                    stats['total_events'] += line_count
            except Exception:
                pass  # Skip if can't read

            # Try to get date from filename
            try:
                date_str = log_file.stem.split('_')[1]  # audit_YYYY-MM-DD.jsonl
                file_date = datetime.strptime(date_str, '%Y-%m-%d')
                if stats['date_range']['earliest'] is None or file_date < stats['date_range']['earliest']:
                    stats['date_range']['earliest'] = file_date.isoformat()
                if stats['date_range']['latest'] is None or file_date > stats['date_range']['latest']:
                    stats['date_range']['latest'] = file_date.isoformat()
            except (IndexError, ValueError):
                pass

        # Process compressed logs
        for log_file in sorted(self.log_dir.glob("audit_*.jsonl.gz")):
            stats['total_files'] += 1
            file_size = log_file.stat().st_size
            compressed_size += file_size

            # For compressed files, we'd need to decompress to count events
            # Skip for simplicity in statistics

        # Calculate compression ratio
        if uncompressed_size > 0:
            stats['compression_ratio'] = compressed_size / uncompressed_size

        return stats


def verify_audit_integrity(log_dir: str = "audit_logs") -> Tuple[bool, List[str]]:
    """
    Convenience function to verify audit log integrity.

    Args:
        log_dir: Directory containing audit logs

    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    verifier = IntegrityVerifier(log_dir)
    return verifier.verify_all_logs()


if __name__ == "__main__":
    # Simple CLI for testing
    import sys
    log_dir = sys.argv[1] if len(sys.argv) > 1 else "audit_logs"
    is_valid, errors = verify_audit_integrity(log_dir)
    if is_valid:
        print("✓ All audit logs are valid")
        sys.exit(0)
    else:
        print("✗ Audit log integrity check failed:")
        for error in errors:
            print(f"  - {error}")
        sys.exit(1)