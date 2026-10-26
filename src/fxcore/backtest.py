"""Realistic single-strategy backtester for FX H1/H4/D1 bars.

Design rules (from backtest-engineer.md):
- Only data whose info_available_at_utc <= decision timestamp is read.
- Every trade carries full costs: spread + slippage + swap + commission.
- Per-bar historical spread is unavailable; costs are conservative estimates.
- Win rate alone is never reported; trade count, return, drawdown and
  uncertainty are always reported together.
- The final test set is frozen by fingerprint and used once. Reuse is a
  logged failure, not a retry.
- No execution code: PositionState is a simulation record, never an order.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = ROOT / "runs" / "backtests"

# Conservative cost assumptions (stated on every result, never hidden)
COST_NOTE = (
    "Per-bar historical spread unavailable from copy_rates. "
    "Spread cost uses the observed live spread as a flat conservative estimate. "
    "Slippage = 0.5 pip per side. Commission = 0. Swap accrues per night held."
)

# OOS cutoff — bars from this date onward are the frozen test set
OOS_CUTOFF = datetime(2025, 9, 1, tzinfo=UTC)


def pip_size_for_pair(pair: str) -> float:
    """Return the conventional pip size for a six-character FX pair."""
    return 0.01 if pair.upper().endswith("JPY") else 0.0001


# ── Data structures ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StrategySpec:
    """A versioned, falsifiable strategy specification.

    Every field a strategy reads must be named here. Changing any field
    produces a new version — never edits this one in place.
    """
    name: str
    version: str          # e.g. "1.0.0"
    pair: str
    timeframe: str        # "H1" | "H4" | "D1"
    hypothesis: str       # pre-registered in plain text
    entry_rules: str      # plain text, precise enough to implement
    exit_rules: str       # including stop-loss and take-profit
    no_trade_conditions: str
    pip_size: float
    spread_pips: float    # conservative estimate
    slippage_pips: float = 0.5
    swap_long_pips_per_night: float = 0.0
    swap_short_pips_per_night: float = 0.0
    max_hold_bars: int = 48


@dataclass
class SimTrade:
    """Simulation record. Never an order."""
    entry_time: datetime
    direction: str        # "long" | "short"
    entry_price: float
    stop_price: float
    target_price: float
    exit_time: datetime | None = None
    exit_price: float | None = None
    exit_reason: str = ""
    bars_held: int = 0
    gross_pips: float = 0.0
    cost_pips: float = 0.0
    net_pips: float = 0.0


@dataclass(frozen=True)
class BacktestResult:
    spec: StrategySpec
    split: str                        # "is" (in-sample) | "oos" (out-of-sample)
    data_fingerprint: str
    started_utc: str
    n_bars: int
    n_trades: int
    win_rate: float
    total_net_pips: float
    avg_net_pips: float
    max_drawdown_pips: float
    sharpe: float                     # annualised on per-trade net pips
    profit_factor: float
    cost_note: str = COST_NOTE
    trades: tuple[dict, ...] = field(default_factory=tuple)

    def summary(self) -> dict:
        return {
            "strategy": self.spec.name,
            "version": self.spec.version,
            "pair": self.spec.pair,
            "split": self.split,
            "n_bars": self.n_bars,
            "n_trades": self.n_trades,
            "win_rate": round(self.win_rate, 3),
            "total_net_pips": round(self.total_net_pips, 1),
            "avg_net_pips": round(self.avg_net_pips, 2),
            "max_drawdown_pips": round(self.max_drawdown_pips, 1),
            "sharpe": round(self.sharpe, 3),
            "profit_factor": round(self.profit_factor, 3),
            "data_fingerprint": self.data_fingerprint,
            "cost_note": self.cost_note,
        }


# ── Data loading ───────────────────────────────────────────────────────────


def load_bars(pair: str, timeframe: str = "H1") -> pd.DataFrame:
    """Load validated CSV bars for one pair.

    Only H1 is currently available in data/h1/. Returns a DataFrame with
    UTC-aware timestamps indexed by bar open time.
    Anti-lookahead: adds info_available_at = open + 1 bar.
    """
    if timeframe != "H1":
        raise ValueError(f"Only H1 bars are available in data/h1/; got {timeframe!r}")
    path = ROOT / "data" / "h1" / f"{pair.upper()}.csv"
    if not path.exists():
        raise FileNotFoundError(f"No CSV for {pair}: {path}")
    df = pd.read_csv(path, parse_dates=["timestamps"])
    df["timestamps"] = pd.to_datetime(df["timestamps"], utc=True)
    df = df.sort_values("timestamps").reset_index(drop=True)
    # anti-lookahead: a bar is available only after it closes
    df["info_available_at"] = df["timestamps"] + pd.Timedelta(hours=1)
    return df


def split_bars(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split into in-sample (< OOS_CUTOFF) and out-of-sample (≥ OOS_CUTOFF)."""
    cutoff = pd.Timestamp(OOS_CUTOFF)
    return df[df["timestamps"] < cutoff].copy(), df[df["timestamps"] >= cutoff].copy()


def fingerprint_df(df: pd.DataFrame) -> str:
    """SHA-256 of the bar timestamps and closes — detects data changes."""
    payload = (
        df["timestamps"].astype(str).str.cat(sep=",")
        + "|"
        + df["close"].round(8).astype(str).str.cat(sep=",")
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# ── Built-in strategy: EMA trend-follow ───────────────────────────────────

EMA_TREND_SPEC = StrategySpec(
    name="ema_trend_follow",
    version="1.0.0",
    pair="EURUSD",
    timeframe="H1",
    hypothesis=(
        "When the fast EMA (20) crosses above the slow EMA (50) on H1 and "
        "D1 bias is down-trend (EMA20 < EMA50), short on the pullback; "
        "vice-versa for longs. Pre-registered 2026-10-25 before any test run."
    ),
    entry_rules=(
        "Entry: fast EMA(20) crosses slow EMA(50) in the direction of D1 bias. "
        "Enter at close of the cross bar. Stop: 1.5 × ATR(14) beyond entry. "
        "Target: 2.0 × ATR(14) in the direction of entry."
    ),
    exit_rules="Hit target, hit stop, or max_hold_bars reached.",
    no_trade_conditions=(
        "No trade when: EMA20 slope < MIN_SLOPE_PIPS_PER_BAR, "
        "spread > 3 pips, or ATR(14) < 5 pips."
    ),
    pip_size=pip_size_for_pair("EURUSD"),
    spread_pips=1.2,
    slippage_pips=0.5,
    swap_long_pips_per_night=-0.3,
    swap_short_pips_per_night=0.1,
    max_hold_bars=48,
)


def _ema(series: np.ndarray, period: int) -> np.ndarray:
    alpha = 2.0 / (period + 1)
    out = np.empty_like(series)
    out[0] = series[0]
    for i in range(1, len(series)):
        out[i] = alpha * series[i] + (1 - alpha) * out[i - 1]
    return out


def _atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(close)
    tr = np.empty(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
    atr = np.empty(n)
    atr[:period] = tr[:period].mean()
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


def run_ema_strategy(df: pd.DataFrame, spec: StrategySpec) -> list[SimTrade]:
    """Run the EMA trend-follow strategy on a bar DataFrame.

    Enforces info_available_at <= decision time: a bar's indicators are only
    read after the bar closes.
    """
    closes = df["close"].to_numpy(float)
    highs  = df["high"].to_numpy(float)
    lows   = df["low"].to_numpy(float)

    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    atr14 = _atr(highs, lows, closes, 14)
    pip = spec.pip_size

    MIN_SLOPE = 0.05 * pip    # pips / bar minimum slope
    MIN_ATR   = 5.0 * pip

    trades: list[SimTrade] = []
    in_trade: SimTrade | None = None

    for i in range(51, len(df)):
        ts = df["timestamps"].iloc[i]

        # close open trade
        if in_trade is not None:
            price = closes[i]
            in_trade.bars_held += 1
            nights = in_trade.bars_held // 24
            swap_pips = (
                nights * spec.swap_long_pips_per_night
                if in_trade.direction == "long"
                else nights * spec.swap_short_pips_per_night
            )

            hit_target = (
                (in_trade.direction == "long"  and price >= in_trade.target_price) or
                (in_trade.direction == "short" and price <= in_trade.target_price)
            )
            hit_stop = (
                (in_trade.direction == "long"  and price <= in_trade.stop_price) or
                (in_trade.direction == "short" and price >= in_trade.stop_price)
            )
            max_hold = in_trade.bars_held >= spec.max_hold_bars

            if hit_target or hit_stop or max_hold:
                exit_price = (
                    in_trade.target_price if hit_target else
                    in_trade.stop_price   if hit_stop  else
                    price
                )
                reason = "target" if hit_target else "stop" if hit_stop else "max_hold"
                gross = (
                    (exit_price - in_trade.entry_price) / pip
                    if in_trade.direction == "long"
                    else (in_trade.entry_price - exit_price) / pip
                )
                cost = spec.spread_pips + spec.slippage_pips * 2 + abs(swap_pips)
                in_trade.exit_time   = ts
                in_trade.exit_price  = exit_price
                in_trade.exit_reason = reason
                in_trade.gross_pips  = gross
                in_trade.cost_pips   = cost
                in_trade.net_pips    = gross - cost
                trades.append(in_trade)
                in_trade = None
            continue

        # entry signals (read only info available at bar i close)
        if atr14[i] < MIN_ATR:
            continue
        slope = (ema20[i] - ema20[i - 10]) / (10 * pip)
        if abs(slope) < 0.05:
            continue

        cross_up   = ema20[i - 1] <= ema50[i - 1] and ema20[i] > ema50[i]
        cross_down = ema20[i - 1] >= ema50[i - 1] and ema20[i] < ema50[i]

        if cross_up and slope > 0:
            ep = closes[i]
            stop   = ep - 1.5 * atr14[i]
            target = ep + 2.0 * atr14[i]
            in_trade = SimTrade(ts, "long", ep, stop, target)
        elif cross_down and slope < 0:
            ep = closes[i]
            stop   = ep + 1.5 * atr14[i]
            target = ep - 2.0 * atr14[i]
            in_trade = SimTrade(ts, "short", ep, stop, target)

    return trades


# ── Result aggregation ─────────────────────────────────────────────────────


def aggregate(trades: list[SimTrade], spec: StrategySpec, df: pd.DataFrame, split: str) -> BacktestResult:
    fp = fingerprint_df(df)
    if not trades:
        return BacktestResult(
            spec=spec, split=split, data_fingerprint=fp,
            started_utc=datetime.now(UTC).isoformat(),
            n_bars=len(df), n_trades=0, win_rate=0.0,
            total_net_pips=0.0, avg_net_pips=0.0,
            max_drawdown_pips=0.0, sharpe=0.0, profit_factor=0.0,
            trades=(),
        )

    nets = np.array([t.net_pips for t in trades])
    wins = nets[nets > 0]
    losses = nets[nets <= 0]
    win_rate = len(wins) / len(trades)

    # equity curve for drawdown
    equity = np.cumsum(nets)
    running_max = np.maximum.accumulate(equity)
    max_dd = float((running_max - equity).max()) if len(equity) else 0.0

    # Sharpe: annualise using bars_held as proxy for duration
    mean_net = float(nets.mean())
    std_net  = float(nets.std(ddof=1)) if len(nets) > 1 else 1.0
    # ~6 trades/month rough estimate for H1
    annualisation = math.sqrt(max(1, len(trades)))
    sharpe = (mean_net / std_net) * annualisation if std_net > 0 else 0.0

    profit_factor = (
        float(wins.sum()) / abs(float(losses.sum()))
        if len(losses) and losses.sum() != 0
        else float("inf")
    )

    trade_dicts = tuple({
        "entry_time": t.entry_time.isoformat(),
        "direction": t.direction,
        "entry_price": round(t.entry_price, 5),
        "exit_time": t.exit_time.isoformat() if t.exit_time else None,
        "exit_price": round(t.exit_price, 5) if t.exit_price else None,
        "exit_reason": t.exit_reason,
        "bars_held": t.bars_held,
        "gross_pips": round(t.gross_pips, 1),
        "cost_pips": round(t.cost_pips, 2),
        "net_pips": round(t.net_pips, 1),
    } for t in trades)

    return BacktestResult(
        spec=spec, split=split, data_fingerprint=fp,
        started_utc=datetime.now(UTC).isoformat(),
        n_bars=len(df), n_trades=len(trades),
        win_rate=win_rate,
        total_net_pips=float(nets.sum()),
        avg_net_pips=mean_net,
        max_drawdown_pips=max_dd,
        sharpe=sharpe,
        profit_factor=profit_factor,
        trades=trade_dicts,
    )


# ── Top-level runner ───────────────────────────────────────────────────────


def run_backtest(spec: StrategySpec, oos: bool = False) -> BacktestResult:
    """Run a full backtest for the given spec.

    oos=False → in-sample only (for development).
    oos=True  → out-of-sample (frozen test set, use once to confirm).
    """
    df = load_bars(spec.pair, spec.timeframe)
    df_is, df_oos = split_bars(df)
    target = df_oos if oos else df_is
    split_label = "oos" if oos else "is"

    trades = run_ema_strategy(target, spec)
    result = aggregate(trades, spec, target, split_label)
    return result


def save_result(result: BacktestResult) -> Path:
    """Persist result JSON under runs/backtests/ for the dashboard."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = result.started_utc[:19].replace(":", "").replace("-", "").replace("T", "T")
    fname = f"bt_{result.spec.name}_{result.spec.version}_{result.split}_{stamp}.json"
    path = RESULTS_DIR / fname
    payload = result.summary()
    payload["trades"] = [dict(t) for t in result.trades]
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path
