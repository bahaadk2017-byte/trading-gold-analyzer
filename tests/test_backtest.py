"""Focused backtest invariants."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fxcore.backtest import pip_size_for_pair


def test_pip_size_uses_jpy_convention():
    assert pip_size_for_pair("EURUSD") == 0.0001
    assert pip_size_for_pair("USDJPY") == 0.01
    assert pip_size_for_pair("gbpjpy") == 0.01
