"""JSON Schema validation and versioning service."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import jsonschema
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False


class SchemaRegistry:
    """Registry for JSON Schemas with validation support."""

    def __init__(self, schema_dir: Union[str, Path] = "schemas/v1"):
        self.schema_dir = Path(schema_dir)
        self.schemas: Dict[str, Dict[str, Any]] = {}
        self._load_schemas()

    def _load_schemas(self) -> None:
        """Load all JSON schemas from the schema directory."""
        if not self.schema_dir.exists():
            # Create directory if it doesn't exist
            self.schema_dir.mkdir(parents=True, exist_ok=True)
            return

        for schema_file in self.schema_dir.glob("*.json"):
            try:
                schema_name = schema_file.stem
                with open(schema_file, 'r', encoding='utf-8') as f:
                    schema_data = json.load(f)
                    self.schemas[schema_name] = schema_data
            except Exception as e:
                print(f"Error loading schema {schema_file.name}: {e}")

    def register_schema(self, name: str, schema: Dict[str, Any]) -> None:
        """
        Register a new schema or update an existing one.

        Args:
            name: Schema name (e.g., 'agent_telemetry')
            schema: JSON Schema dictionary
        """
        self.schemas[name] = schema

        # Save to disk
        self.schema_dir.mkdir(parents=True, exist_ok=True)
        schema_path = self.schema_dir / f"{name}.json"
        with open(schema_path, 'w', encoding='utf-8') as f:
            json.dump(schema, f, indent=2)

    def validate(self, schema_name: str, data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Validate data against a registered schema.

        Args:
            schema_name: Name of the schema to validate against
            data: Data dictionary to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not HAS_JSONSCHEMA:
            # Fallback if jsonschema not installed
            return True, None

        if schema_name not in self.schemas:
            return False, f"Schema not found: {schema_name}"

        try:
            schema = self.schemas[schema_name]
            jsonschema.validate(instance=data, schema=schema)
            return True, None
        except jsonschema.exceptions.ValidationError as e:
            return False, str(e)
        except Exception as e:
            return False, f"Validation error: {e}"

    def get_schema(self, schema_name: str) -> Optional[Dict[str, Any]]:
        """Get a registered schema by name."""
        return self.schemas.get(schema_name)

    def list_schemas(self) -> List[str]:
        """List all registered schema names."""
        return list(self.schemas.keys())


# Global schema registry instance
_schema_registry: Optional[SchemaRegistry] = None


def get_schema_registry() -> SchemaRegistry:
    """Get or create the global schema registry instance."""
    global _schema_registry
    if _schema_registry is None:
        _schema_registry = SchemaRegistry()
    return _schema_registry


def validate_payload(schema_name: str, data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Convenience function to validate data against a schema using the global registry.

    Args:
        schema_name: Name of the schema
        data: Data to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    return get_schema_registry().validate(schema_name, data)


# Default schemas to create on startup
AGENT_TELEMETRY_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "AgentTelemetry",
    "type": "object",
    "properties": {
        "agent_id": {"type": "string"},
        "agent_name": {"type": "string"},
        "status": {"enum": ["IDLE", "ANALYZING", "WAITING", "ERROR"]},
        "timestamp_utc": {"type": "string", "format": "date-time"},
        "latency_ms": {"type": "integer", "minimum": 0},
        "performance_metrics": {
            "type": "object",
            "properties": {
                "win_rate": {"type": "number", "minimum": 0, "maximum": 1},
                "avg_profit_pips": {"type": "number"},
                "total_trades": {"type": "integer", "minimum": 0}
            },
            "required": ["win_rate", "avg_profit_pips", "total_trades"]
        },
        "environment": {"enum": ["live", "demo", "simulated", "backtest", "experimental"]}
    },
    "required": ["agent_id", "agent_name", "status", "timestamp_utc", "environment"]
}

MESSAGE_EVENT_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "MessageEvent",
    "type": "object",
    "properties": {
        "message_id": {"type": "string"},
        "correlation_id": {"type": "string"},
        "sender": {"type": "string"},
        "recipient": {"type": "string"},
        "timestamp_utc": {"type": "string", "format": "date-time"},
        "payload_type": {"type": "string"},
        "payload": {"type": "object"},
        "environment": {"enum": ["live", "demo", "simulated", "backtest", "experimental"]}
    },
    "required": ["message_id", "correlation_id", "sender", "recipient", "timestamp_utc", "payload_type", "payload", "environment"]
}

LEARNING_RECORD_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "LearningRecord",
    "type": "object",
    "properties": {
        "record_id": {"type": "string"},
        "strategy_name": {"type": "string"},
        "version": {"type": "string"},
        "changed_by": {"type": "string"},
        "timestamp_utc": {"type": "string", "format": "date-time"},
        "change_reason": {"type": "string"},
        "environment": {"enum": ["live", "demo", "simulated", "backtest", "experimental"]},
        "changes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "parameter": {"type": "string"},
                    "old_value": {},
                    "new_value": {}
                },
                "required": ["parameter", "old_value", "new_value"]
            }
        }
    },
    "required": ["record_id", "strategy_name", "version", "changed_by", "timestamp_utc", "change_reason", "environment", "changes"]
}


def initialize_default_schemas() -> None:
    """Initialize default schemas in the registry."""
    registry = get_schema_registry()
    registry.register_schema("agent_telemetry", AGENT_TELEMETRY_SCHEMA)
    registry.register_schema("message_event", MESSAGE_EVENT_SCHEMA)
    registry.register_schema("learning_record", LEARNING_RECORD_SCHEMA)


# Initialize default schemas on module load
initialize_default_schemas()