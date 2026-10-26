"""Read-only access to runs/*.json for the dashboard.

Never writes, never calls MT5, never modifies run records.
The environment label is derived from run metadata — not injected.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "runs"

# run filenames: analysis_YYYYMMDDTHHMMSS.json
_RUN_RE = re.compile(r"^analysis_(\d{8}T\d{6})\.json$")

UTC = timezone.utc


def _record_id(path: Path) -> str:
    return path.stem  # analysis_20261024T101659


def _started_utc(run: dict) -> str:
    return run.get("started_utc", "")


def infer_environment(run: dict) -> str:
    """Derive environment label from run metadata.

    LIVE  = real account, execution disabled (current state)
    DEMO  = demo/paper account
    UNKNOWN = metadata missing

    We never label anything LIVE_TRADING because execution_enabled
    is always False in this codebase — there is no order code.
    """
    acct = run.get("account", {})
    is_real = acct.get("is_real_account")
    if is_real is True:
        return "LIVE"
    if is_real is False:
        return "DEMO"
    return "UNKNOWN"


def infer_clock_warning(run: dict) -> str | None:
    """Return a warning string if the server offset looks anomalous."""
    offset = run.get("server_offset_hours")
    if offset is None:
        return "انحراف الساعة غير معروف"
    if abs(offset) > 12:
        return f"انحراف غير معتاد: {offset:+.1f}h"
    return None


def list_runs(limit: int = 50) -> list[dict]:
    """Return run summaries sorted newest-first, up to `limit`."""
    summaries: list[dict] = []
    for path in sorted(RUNS_DIR.glob("analysis_*.json"), reverse=True)[:limit]:
        try:
            run = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        summaries.append({
            "record_id": _record_id(path),
            "started_utc": run.get("started_utc"),
            "finished_utc": run.get("finished_utc"),
            "server_offset_hours": run.get("server_offset_hours"),
            "clock_warning": infer_clock_warning(run),
            "environment": infer_environment(run),
            "execution_enabled": False,
            "pair_count": len(run.get("results", [])),
            "analysed_count": sum(
                1 for r in run.get("results", []) if r.get("decision") == "ANALYSED"
            ),
            "no_trade_count": sum(
                1 for r in run.get("results", []) if r.get("decision") == "NO_TRADE"
            ),
        })
    return summaries


def get_latest_run() -> dict | None:
    """Return the most recent run record, or None."""
    paths = sorted(RUNS_DIR.glob("analysis_*.json"), reverse=True)
    if not paths:
        return None
    return _load_run(paths[0])


def get_run(record_id: str) -> dict | None:
    """Return a specific run by record_id, or None."""
    path = RUNS_DIR / f"{record_id}.json"
    if not path.exists():
        return None
    return _load_run(path)


def _load_run(path: Path) -> dict:
    run = json.loads(path.read_text(encoding="utf-8"))
    run["record_id"] = _record_id(path)
    run["execution_enabled"] = False
    run["environment"] = infer_environment(run)
    run["clock_warning"] = infer_clock_warning(run)
    return run
