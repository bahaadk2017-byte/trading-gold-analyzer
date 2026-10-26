"""Unit tests for dashboard.reader — read-only, no MT5, no network."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dashboard.reader import (
    _record_id,
    get_latest_run,
    get_run,
    infer_clock_warning,
    infer_environment,
    list_runs,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def _make_run(tmp_path: Path, stamp: str, is_real: bool, offset: float, results=None) -> Path:
    run = {
        "started_utc": f"2026-10-24T{stamp.replace('T', '')}+00:00",
        "finished_utc": f"2026-10-24T{stamp.replace('T', '')}+00:00",
        "server_offset_hours": offset,
        "account": {
            "server": "XMGlobal-MT5 12",
            "currency": "USD",
            "leverage": 1000,
            "is_real_account": is_real,
            "terminal_trade_allowed": True,
            "terminal_connected": True,
        },
        "execution_enabled": False,
        "results": results or [],
    }
    path = tmp_path / f"analysis_{stamp}.json"
    path.write_text(json.dumps(run), encoding="utf-8")
    return path


# ── infer_environment ─────────────────────────────────────────────────────────

class TestInferEnvironment:
    def test_real_account_is_live(self):
        run = {"account": {"is_real_account": True}, "execution_enabled": False}
        assert infer_environment(run) == "LIVE"

    def test_demo_account_is_demo(self):
        run = {"account": {"is_real_account": False}, "execution_enabled": False}
        assert infer_environment(run) == "DEMO"

    def test_missing_account_is_unknown(self):
        assert infer_environment({}) == "UNKNOWN"

    def test_missing_is_real_key_is_unknown(self):
        assert infer_environment({"account": {}}) == "UNKNOWN"

    def test_execution_enabled_always_false(self):
        # execution_enabled is structurally False in all run records;
        # environment label must never imply live trading is on.
        run = {"account": {"is_real_account": True}, "execution_enabled": False}
        env = infer_environment(run)
        assert env == "LIVE"                   # label says live account
        assert run["execution_enabled"] is False   # but execution is off


# ── infer_clock_warning ───────────────────────────────────────────────────────

class TestClockWarning:
    def test_normal_offset_no_warning(self):
        assert infer_clock_warning({"server_offset_hours": 3.0}) is None

    def test_large_positive_offset_warns(self):
        w = infer_clock_warning({"server_offset_hours": 13.0})
        assert w is not None
        assert "13" in w

    def test_large_negative_offset_warns(self):
        w = infer_clock_warning({"server_offset_hours": -13.0})
        assert w is not None

    def test_missing_offset_warns(self):
        w = infer_clock_warning({})
        assert w is not None

    def test_boundary_exactly_12_no_warning(self):
        assert infer_clock_warning({"server_offset_hours": 12.0}) is None
        assert infer_clock_warning({"server_offset_hours": -12.0}) is None


# ── list_runs / get_run / get_latest_run (using tmp_path) ────────────────────

class TestRunReaders:
    def test_list_runs_empty_dir(self, tmp_path):
        # patch RUNS_DIR to an empty dir
        import dashboard.reader as mod
        orig = mod.RUNS_DIR
        mod.RUNS_DIR = tmp_path
        try:
            assert list_runs() == []
        finally:
            mod.RUNS_DIR = orig

    def test_list_runs_returns_summaries(self, tmp_path):
        import dashboard.reader as mod
        _make_run(tmp_path, "101200", True, 3.0, [
            {"pair": "EURUSD", "decision": "ANALYSED"},
            {"pair": "GBPUSD", "decision": "NO_TRADE"},
        ])
        orig = mod.RUNS_DIR
        mod.RUNS_DIR = tmp_path
        try:
            runs = list_runs()
            assert len(runs) == 1
            r = runs[0]
            assert r["pair_count"] == 2
            assert r["analysed_count"] == 1
            assert r["no_trade_count"] == 1
            assert r["environment"] == "LIVE"
            assert r["execution_enabled"] is False
        finally:
            mod.RUNS_DIR = orig

    def test_get_latest_run_none_when_empty(self, tmp_path):
        import dashboard.reader as mod
        orig = mod.RUNS_DIR
        mod.RUNS_DIR = tmp_path
        try:
            assert get_latest_run() is None
        finally:
            mod.RUNS_DIR = orig

    def test_get_latest_run_returns_enriched(self, tmp_path):
        import dashboard.reader as mod
        _make_run(tmp_path, "101200", False, -10.5)
        orig = mod.RUNS_DIR
        mod.RUNS_DIR = tmp_path
        try:
            run = get_latest_run()
            assert run is not None
            assert run["environment"] == "DEMO"
            assert "record_id" in run
            assert run["execution_enabled"] is False
        finally:
            mod.RUNS_DIR = orig

    def test_get_run_not_found_returns_none(self, tmp_path):
        import dashboard.reader as mod
        orig = mod.RUNS_DIR
        mod.RUNS_DIR = tmp_path
        try:
            assert get_run("analysis_99999999T999999") is None
        finally:
            mod.RUNS_DIR = orig

    def test_get_run_by_record_id(self, tmp_path):
        import dashboard.reader as mod
        _make_run(tmp_path, "101200", True, 3.0)
        orig = mod.RUNS_DIR
        mod.RUNS_DIR = tmp_path
        try:
            run = get_run("analysis_101200")
            assert run is not None
            assert run["record_id"] == "analysis_101200"
        finally:
            mod.RUNS_DIR = orig

    def test_execution_enabled_never_true_in_any_run(self, tmp_path):
        """Structural invariant: persisted claims cannot enable execution."""
        import dashboard.reader as mod
        _make_run(tmp_path, "101200", True, 3.0)
        persisted = json.loads((tmp_path / "analysis_101200.json").read_text(encoding="utf-8"))
        persisted["execution_enabled"] = True
        (tmp_path / "analysis_101200.json").write_text(json.dumps(persisted), encoding="utf-8")
        orig = mod.RUNS_DIR
        mod.RUNS_DIR = tmp_path
        try:
            for summary in list_runs():
                assert summary["execution_enabled"] is False
            run = get_latest_run()
            assert run["execution_enabled"] is False
        finally:
            mod.RUNS_DIR = orig

    def test_no_order_functions_in_reader(self):
        """reader.py must not contain any order/execution function names."""
        source = (ROOT / "dashboard" / "reader.py").read_text(encoding="utf-8")
        forbidden = ["order_send", "order_check", "execute_trade", "place_order",
                     "buy(", "sell("]
        for token in forbidden:
            assert token not in source, f"order API token found in reader.py: {token!r}"

    def test_no_order_functions_in_app(self):
        """app.py must not contain any order/execution endpoint or function names."""
        source = (ROOT / "dashboard" / "app.py").read_text(encoding="utf-8")
        forbidden = ["order_send", "order_check", "execute_trade", "place_order",
                     "POST /api/execute", "POST /api/trade"]
        for token in forbidden:
            assert token not in source, f"order API token found in app.py: {token!r}"


# ── agents ────────────────────────────────────────────────────────────────────

class TestAgents:
    def test_list_agents_returns_14(self):
        from dashboard.agents import list_agents
        agents = list_agents()
        assert len(agents) == 14

    def test_all_agents_have_name_and_description(self):
        from dashboard.agents import list_agents
        for a in list_agents():
            assert a["name"], f"agent missing name: {a}"
            assert a["description"], f"agent {a['name']} missing description"

    def test_team_split_7_7(self):
        from dashboard.agents import list_agents
        agents = list_agents()
        system_count = sum(1 for a in agents if a["team"] == "system")
        trading_count = sum(1 for a in agents if a["team"] == "trading")
        assert system_count == 7, f"expected 7 system agents, got {system_count}"
        assert trading_count == 7, f"expected 7 trading agents, got {trading_count}"
