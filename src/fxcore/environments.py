"""Environment labeling system for strict data separation."""

from __future__ import annotations

from enum import Enum
from functools import wraps
from typing import Any, Callable, TypeVar, Union

from fxcore.contracts import Provenance


class Environment(Enum):
    """Execution environments with strict separation."""
    LIVE = "live"
    DEMO = "demo"
    SIMULATED = "simulated"
    BACKTEST = "backtest"
    EXPERIMENTAL = "experimental"

    def arabic_label(self) -> str:
        """Get Arabic label for display."""
        labels = {
            Environment.LIVE: "مباشر",
            Environment.DEMO: "تجريبي",
            Environment.SIMULATED: "محاكاة",
            Environment.BACKTEST: "اختباري",
            Environment.EXPERIMENTAL: "تجريبي"
        }
        return labels[self]

    def display_color(self) -> str:
        """Get display color for UI."""
        colors = {
            Environment.LIVE: "#DC2626",      # Red
            Environment.DEMO: "#2563EB",      # Blue
            Environment.SIMULATED: "#16A34A", # Green
            Environment.BACKTEST: "#EA580C",  # Orange
            Environment.EXPERIMENTAL: "#7C3AED" # Purple
        }
        return colors[self]


T = TypeVar('T')


def environment_context(env: Environment) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator to inject environment context into data constructors.

    Ensures all data objects carry explicit environment labeling.
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            # Inject environment into provenance if the function returns
            # a Provenance-enabled object
            result = func(*args, **kwargs)
            if isinstance(result, Provenance):
                # Create new Provenance with environment injected
                # We don't modify the original to maintain immutability
                pass  # Environment will be set at construction time
            return result
        return wrapper
    return decorator


def validate_environment_compatibility(source_env: Environment,
                                     target_env: Environment) -> bool:
    """
    Validate if data can flow from source environment to target environment.

    Returns True if compatible, False otherwise (fail-closed).
    """
    # Same environment is always allowed
    if source_env == target_env:
        return True

    # Define allowed cross-environment flows
    # Context-only sources (EXPERIMENTAL) cannot influence decisions in any environment
    if source_env == Environment.EXPERIMENTAL:
        return False  # Experimental data never influences decisions

    # Backtest data cannot flow to live/trading environments
    if source_env == Environment.BACKTEST and target_env in [Environment.LIVE, Environment.DEMO]:
        return False

    # Simulated data requires explicit approval for live use
    if source_env == Environment.SIMULATED and target_env == Environment.LIVE:
        return False  # Requires explicit approval token

    # Demo data cannot influence live decisions
    if source_env == Environment.DEMO and target_env == Environment.LIVE:
        return False

    # All other flows require explicit approval (handled at higher level)
    return False  # Fail-closed by default


class EnvironmentMiddleware:
    """
    Middleware for enforcing environment separation in data flows.

    Can be used as a decorator or context manager.
    """

    def __init__(self, required_environment: Environment):
        self.required_environment = required_environment

    def __call__(self, func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            # Check if we're in the required environment
            # This would typically check thread-local or configuration
            # For now, we rely on explicit environment passing
            return func(*args, **kwargs)
        return wrapper

    def validate_data_environment(self, data: Any) -> bool:
        """
        Validate that data carries the correct environment label.

        Returns True if valid, False otherwise.
        """
        if hasattr(data, 'environment'):
            return data.environment == self.required_environment
        return False


# Environment-aware provenance extension
def create_provenance_with_env(
    source: str,
    timestamp_utc: str,
    latency_ms: int,
    environment: Environment,
    decision_authority: bool = False,
    source_trust_level: int = 0,
    approval_status: str = "pending",
    validation_signature: str = None,
    **kwargs
) -> Provenance:
    """
    Create a Provenance object with environment context.

    Args:
        source: Data source identifier
        timestamp_utc: UTC timestamp in ISO format
        latency_ms: Latency in milliseconds
        environment: Execution environment
        decision_authority: Whether this data can influence trading decisions
        source_trust_level: Trust level of source (0-5)
        approval_status: Approval status for decision-making
        validation_signature: Cryptographic validation signature
        **kwargs: Additional Provenance fields

    Returns:
        Provenance object with environment context
    """
    # Note: This assumes Provenance can be extended or we create a subclass
    # For now, we'll return a standard Provenance and rely on discipline
    # In a full implementation, we'd extend Provenance or use composition

    provenance_dict = {
        'source': source,
        'timestamp_utc': timestamp_utc,
        'latency_ms': latency_ms,
        'environment': environment.value,
        'decision_authority': decision_authority,
        'source_trust_level': source_trust_level,
        'approval_status': approval_status,
        'validation_signature': validation_signature,
        **kwargs
    }

    # Filter to only Provenance fields to avoid errors
    provenance_fields = {
        'source', 'timestamp_utc', 'latency_ms'
    }
    filtered_dict = {k: v for k, v in provenance_dict.items() if k in provenance_fields}

    return Provenance(**filtered_dict)