"""Dashboard content-security policy regressions."""

from dashboard.app import CONTENT_SECURITY_POLICY


def test_csp_allows_alpine_expressions_without_inline_scripts():
    """The trusted local Alpine template needs eval, never inline script execution."""
    assert "'unsafe-eval'" in CONTENT_SECURITY_POLICY
    assert "'unsafe-inline'" not in CONTENT_SECURITY_POLICY
    assert "script-src 'self' https://cdn.jsdelivr.net" in CONTENT_SECURITY_POLICY


def test_csp_limits_embedded_content_to_tradingview():
    assert "frame-src https://s.tradingview.com" in CONTENT_SECURITY_POLICY
    assert "frame-src *" not in CONTENT_SECURITY_POLICY
