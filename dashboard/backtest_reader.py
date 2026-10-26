"""Read backtest results from runs/backtests/*.json for the dashboard."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BT_DIR = ROOT / "runs" / "backtests"
_RECORD_ID_RE = re.compile(r"^bt_[A-Za-z0-9_.-]+$")


def list_backtest_runs(limit: int = 50) -> list[dict]:
    """Return backtest summaries sorted newest-first."""
    results: list[dict] = []
    for path in sorted(BT_DIR.glob("bt_*.json"), reverse=True)[:limit]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        # summary without the full trade list
        summary = {k: v for k, v in data.items() if k != "trades"}
        summary["record_id"] = path.stem
        summary["trade_count_from_file"] = len(data.get("trades", []))
        results.append(summary)
    return results


def get_backtest_run(record_id: str) -> dict | None:
    """Return one persisted backtest, accepting only generated record IDs."""
    if not _RECORD_ID_RE.fullmatch(record_id):
        return None
    path = BT_DIR / f"{record_id}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    data["record_id"] = record_id
    return data


def equity_curve(trades: list[dict]) -> list[dict]:
    """Build cumulative net-pips equity curve from trade list."""
    cumulative = 0.0
    curve: list[dict] = []
    for t in trades:
        cumulative += t.get("net_pips", 0.0)
        curve.append({
            "t": t.get("exit_time") or t.get("entry_time"),
            "equity": round(cumulative, 1),
            "net": round(t.get("net_pips", 0.0), 1),
            "direction": t.get("direction"),
            "exit_reason": t.get("exit_reason"),
        })
    return curve


def pair_summary(runs: list[dict]) -> list[dict]:
    """Aggregate latest IS run per pair for the overview table."""
    seen: dict[str, dict] = {}
    for r in runs:
        pair = r.get("pair")
        split = r.get("split")
        if pair and split == "is" and pair not in seen:
            seen[pair] = r
    return list(seen.values())
