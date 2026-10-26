"""Measure simple scalp baselines on frozen gold M5 bars, after cost.

Usage:
    .venv/kronos/Scripts/python.exe -I scripts/gold_scalp_baselines.py          # in-sample
    .venv/kronos/Scripts/python.exe -I scripts/gold_scalp_baselines.py --oos NAME

PRE-REGISTERED 2026-10-26, before any run. Five fixed rules, no free parameters
to tune, no session filter beyond the broker's own daily break. In-sample picks
at most one candidate; the held-back set is then used ONCE on that candidate.
If nothing clears cost in-sample, nothing goes to the held-back set.

Units are broker POINTS (0.01 USD) because GOLDm# has digits=2, so one point is
one pip under SymbolSpec.pip_size. Contract size is 1 oz/lot, so one point on
the minimum 0.1 lot is 0.001 USD — sizing is NOT modelled here; this measures
edge per trade in points against cost in points.

Costs (conservative, stated not hidden): per-bar historical spread is not
available from copy_rates, so spread is flat at SPREAD_POINTS, set above the
live spread observed at export. Slippage is charged on both sides. Swap is
structurally zero because no position is held across the broker's daily break.
"""

from __future__ import annotations

import argparse
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fxcore.backtest import SimTrade, _atr, _ema, aggregate, fingerprint_df, save_result
from fxcore.backtest import StrategySpec

UTC = timezone.utc
CSV = ROOT / "data" / "m5" / "GOLD.csv"
OOS_START = pd.Timestamp("2026-04-01", tz="UTC")  # declared in export_gold_m5.py

POINT = 0.01
SPREAD_POINTS = 32.0      # live spread at export was 29; 32 is deliberately worse
SLIPPAGE_POINTS = 2.0     # per side
COST_POINTS = SPREAD_POINTS + 2 * SLIPPAGE_POINTS

STOP_ATR = 1.0
TARGET_ATR = 1.5
MAX_HOLD_BARS = 12        # one hour: this is a scalp, not a swing

# The broker halts GOLDm# for one hour at its own midnight: 263 sessions resume
# at 23:00 and 16 at 22:00 in exported-timestamp terms (the quality gate reports
# the same thing as 12 missing M5 bars after 21:55). Caveat: the export applies
# one measured clock offset to all history, so these labels carry a one-hour
# error for part of the year — see docs/audit/2026-10-26-gold-scalp-baselines.md
# defect 7. Blocking 20:00-23:00 covers the halt under either labelling, which
# is what makes swap structurally zero.
NO_ENTRY_FROM_HOUR = 20
NO_ENTRY_TO_HOUR = 23


def load() -> pd.DataFrame:
    df = pd.read_csv(CSV, parse_dates=["timestamps"])
    df["timestamps"] = pd.to_datetime(df["timestamps"], utc=True)
    return df.sort_values("timestamps").reset_index(drop=True)


# ── Signals ────────────────────────────────────────────────────────────────
# Each returns +1 (long), -1 (short) or 0 (stand aside) per bar index, reading
# only bars that have already closed.


def sig_mom1(c, h, l, o, ema_f, ema_s, hi20, lo20, sd20, i):
    """Continuation: follow the direction of the bar that just closed."""
    return 1 if c[i] > o[i] else -1 if c[i] < o[i] else 0


def sig_revert1(c, h, l, o, ema_f, ema_s, hi20, lo20, sd20, i):
    """Mean reversion: fade the bar that just closed."""
    return -sig_mom1(c, h, l, o, ema_f, ema_s, hi20, lo20, sd20, i)


def sig_breakout20(c, h, l, o, ema_f, ema_s, hi20, lo20, sd20, i):
    """Range break: close beyond the prior 20-bar high/low."""
    return 1 if c[i] > hi20[i] else -1 if c[i] < lo20[i] else 0


def sig_bb_revert(c, h, l, o, ema_f, ema_s, hi20, lo20, sd20, i):
    """Band fade: close more than 2 standard deviations from EMA(20)."""
    if sd20[i] <= 0:
        return 0
    z = (c[i] - ema_s[i]) / sd20[i]
    return -1 if z > 2 else 1 if z < -2 else 0


def sig_ema_cross(c, h, l, o, ema_f, ema_s, hi20, lo20, sd20, i):
    """EMA(9) crossing EMA(21)."""
    if ema_f[i - 1] <= ema_s[i - 1] and ema_f[i] > ema_s[i]:
        return 1
    if ema_f[i - 1] >= ema_s[i - 1] and ema_f[i] < ema_s[i]:
        return -1
    return 0


BASELINES = {
    "mom1": (sig_mom1, "Gold M5 continues the direction of the bar that just closed."),
    "revert1": (sig_revert1, "Gold M5 fades the direction of the bar that just closed."),
    "breakout20": (sig_breakout20, "A close beyond the prior 20-bar range continues."),
    "bb_revert": (sig_bb_revert, "A close beyond 2 sd from EMA(20) reverts."),
    "ema_cross": (sig_ema_cross, "EMA(9)/EMA(21) crosses mark tradable M5 swings."),
}


def run(df: pd.DataFrame, signal) -> list[SimTrade]:
    """Simulate one baseline. Entries at signal-bar close, intrabar exits."""
    ts = df["timestamps"].to_numpy()
    o = df["open"].to_numpy(float)
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)

    atr = _atr(h, l, c, 14)
    ema_f = _ema(c, 9)
    ema_s = _ema(c, 21)
    series = pd.Series(c)
    hi20 = pd.Series(h).rolling(20).max().shift(1).to_numpy()
    lo20 = pd.Series(l).rolling(20).min().shift(1).to_numpy()
    sd20 = series.rolling(20).std().to_numpy()
    hours = df["timestamps"].dt.hour.to_numpy()

    trades: list[SimTrade] = []
    i = 25
    n = len(df)
    while i < n - 1:
        if np.isnan(hi20[i]) or np.isnan(lo20[i]) or atr[i] <= 0:
            i += 1
            continue
        if NO_ENTRY_FROM_HOUR <= hours[i] < NO_ENTRY_TO_HOUR:
            i += 1
            continue
        side = signal(c, h, l, o, ema_f, ema_s, hi20, lo20, sd20, i)
        if side == 0:
            i += 1
            continue

        entry = c[i]
        stop = entry - side * STOP_ATR * atr[i]
        target = entry + side * TARGET_ATR * atr[i]
        trade = SimTrade(
            pd.Timestamp(ts[i]).to_pydatetime(),
            "long" if side > 0 else "short",
            entry,
            stop,
            target,
        )

        exit_price = exit_reason = None
        j = i
        for k in range(1, MAX_HOLD_BARS + 1):
            j = i + k
            if j >= n:
                break
            # Pessimistic: if the bar spans both levels, assume the stop filled.
            hit_stop = l[j] <= stop if side > 0 else h[j] >= stop
            hit_target = h[j] >= target if side > 0 else l[j] <= target
            if hit_stop:
                exit_price, exit_reason = stop, "stop"
                break
            if hit_target:
                exit_price, exit_reason = target, "target"
                break
            # Never hold across the broker's daily halt.
            if hours[j] >= NO_ENTRY_FROM_HOUR:
                exit_price, exit_reason = c[j], "session_close"
                break
        if exit_price is None:
            j = min(i + MAX_HOLD_BARS, n - 1)
            exit_price, exit_reason = c[j], "max_hold"

        gross = (exit_price - entry) * side / POINT
        trade.exit_time = pd.Timestamp(ts[j]).to_pydatetime()
        trade.exit_price = exit_price
        trade.exit_reason = exit_reason
        trade.bars_held = j - i
        trade.gross_pips = gross
        trade.cost_pips = COST_POINTS
        trade.net_pips = gross - COST_POINTS
        trades.append(trade)
        i = j + 1  # one position at a time, no overlap
    return trades


def directional_edge(df: pd.DataFrame, signal) -> dict:
    """Raw directional edge: take the signal, hold exactly MAX_HOLD_BARS, no exits.

    This separates "the signal predicts direction" from "this stop/target
    structure works". Samples are stepped by the holding period so they do not
    overlap, otherwise autocorrelation inflates the t-statistic. Gross only:
    cost is a constant subtraction and is reported beside it.
    """
    o = df["open"].to_numpy(float)
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    atr = _atr(h, l, c, 14)
    ema_f = _ema(c, 9)
    ema_s = _ema(c, 21)
    hi20 = pd.Series(h).rolling(20).max().shift(1).to_numpy()
    lo20 = pd.Series(l).rolling(20).min().shift(1).to_numpy()
    sd20 = pd.Series(c).rolling(20).std().to_numpy()
    hours = df["timestamps"].dt.hour.to_numpy()

    moves = []
    for i in range(25, len(df) - MAX_HOLD_BARS, MAX_HOLD_BARS):
        if np.isnan(hi20[i]) or np.isnan(lo20[i]) or atr[i] <= 0:
            continue
        if NO_ENTRY_FROM_HOUR <= hours[i] < NO_ENTRY_TO_HOUR:
            continue
        side = signal(c, h, l, o, ema_f, ema_s, hi20, lo20, sd20, i)
        if side == 0:
            continue
        moves.append((c[i + MAX_HOLD_BARS] - c[i]) * side / POINT)

    arr = np.array(moves)
    if len(arr) < 2:
        return {"n": len(arr), "avg": 0.0, "t": 0.0, "p": 1.0}
    mean = float(arr.mean())
    se = float(arr.std(ddof=1)) / math.sqrt(len(arr))
    t = mean / se if se > 0 else 0.0
    return {"n": len(arr), "avg": mean, "t": t, "p": math.erfc(abs(t) / math.sqrt(2))}


def stats(trades: list[SimTrade]) -> dict:
    nets = np.array([t.net_pips for t in trades])
    if len(nets) < 2:
        return {"n": len(nets), "avg": 0.0, "t": 0.0, "p": 1.0}
    mean = float(nets.mean())
    se = float(nets.std(ddof=1)) / math.sqrt(len(nets))
    t = mean / se if se > 0 else 0.0
    p = math.erfc(abs(t) / math.sqrt(2))  # two-sided normal approximation
    return {"n": len(nets), "avg": mean, "t": t, "p": p}


def spec_for(name: str, hypothesis: str, spread: float) -> StrategySpec:
    return StrategySpec(
        name=f"gold_scalp_{name}",
        version="1.0.0",
        pair="GOLD",
        timeframe="M5",
        hypothesis=f"{hypothesis} Pre-registered 2026-10-26 before any run.",
        entry_rules=(
            f"Entry at close of the signalling M5 bar. Stop {STOP_ATR}xATR(14), "
            f"target {TARGET_ATR}xATR(14), both checked intrabar on high/low with "
            "the stop assumed first when one bar spans both."
        ),
        exit_rules=f"Stop, target, {MAX_HOLD_BARS}-bar max hold, or session close.",
        no_trade_conditions=(
            f"No entry {NO_ENTRY_FROM_HOUR}:00-{NO_ENTRY_TO_HOUR}:00 exported-clock "
            "(covers the broker's one-hour daily halt at its own midnight under either "
            "DST labelling); no position held across the halt; one position at a time."
        ),
        pip_size=POINT,
        spread_pips=spread,
        slippage_pips=SLIPPAGE_POINTS,
        max_hold_bars=MAX_HOLD_BARS,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--oos", metavar="NAME", help="run one named baseline on the held-back set")
    args = parser.parse_args()

    df = load()
    is_df = df[df["timestamps"] < OOS_START].copy().reset_index(drop=True)
    oos_df = df[df["timestamps"] >= OOS_START].copy().reset_index(drop=True)

    print(f"bars total={len(df)} in_sample={len(is_df)} held_back={len(oos_df)}")
    print(f"cutoff={OOS_START.date()} cost_points={COST_POINTS:.0f} "
          f"(spread {SPREAD_POINTS:.0f} + 2x{SLIPPAGE_POINTS:.0f} slippage)")
    print(f"fingerprint_is={fingerprint_df(is_df)} fingerprint_oos={fingerprint_df(oos_df)}")
    # _atr returns PRICE units; convert to points before comparing with cost.
    atr_med = float(np.median(_atr(
        is_df["high"].to_numpy(float), is_df["low"].to_numpy(float),
        is_df["close"].to_numpy(float), 14))) / POINT
    print(f"median_atr14_points={atr_med:.0f} cost_as_pct_of_atr={COST_POINTS / atr_med:.1%}")

    if args.oos:
        name = args.oos
        if name not in BASELINES:
            raise SystemExit(f"unknown baseline {name!r}; one of {sorted(BASELINES)}")
        signal, hypothesis = BASELINES[name]
        trades = run(oos_df, signal)
        s = stats(trades)
        res = aggregate(trades, spec_for(name, hypothesis, SPREAD_POINTS), oos_df, "oos")
        print(f"\n=== HELD-BACK SET, used once: {name} ===")
        print(f"trades={s['n']} win_rate={res.win_rate:.1%} "
              f"avg_net_points={s['avg']:+.1f} total_net_points={res.total_net_pips:+.0f}")
        print(f"t_stat={s['t']:+.2f} p_value={s['p']:.4f} "
              f"max_dd_points={res.max_drawdown_pips:.0f} profit_factor={res.profit_factor:.2f}")
        print(f"saved={save_result(res).name}")
        return 0

    print(f"\nWith stop/target exits, in points per trade:")
    print(f"{'baseline':<12} {'trades':>7} {'win%':>6} {'avg_gross':>10} "
          f"{'avg_net':>9} {'total_net':>10} {'t':>7} {'p':>8} {'max_dd':>8}")
    for name, (signal, hypothesis) in BASELINES.items():
        trades = run(is_df, signal)
        s = stats(trades)
        res = aggregate(trades, spec_for(name, hypothesis, SPREAD_POINTS), is_df, "is")
        print(f"{name:<12} {s['n']:>7} {res.win_rate:>5.1%} "
              f"{s['avg'] + COST_POINTS:>+10.1f} {s['avg']:>+9.1f} "
              f"{res.total_net_pips:>+10.0f} {s['t']:>+7.2f} {s['p']:>8.4f} "
              f"{res.max_drawdown_pips:>8.0f}")

    print(f"\nRaw direction only, fixed {MAX_HOLD_BARS}-bar hold, no stop or target,"
          f" non-overlapping samples:")
    print(f"{'baseline':<12} {'samples':>8} {'avg_gross':>10} {'vs_cost':>9} {'t':>7} {'p':>8}")
    for name, (signal, _) in BASELINES.items():
        d = directional_edge(is_df, signal)
        print(f"{name:<12} {d['n']:>8} {d['avg']:>+10.1f} "
              f"{d['avg'] - COST_POINTS:>+9.1f} {d['t']:>+7.2f} {d['p']:>8.4f}")

    print(f"\nFive rules were tested, so the best in-sample p-value needs a "
          f"Bonferroni threshold of {0.05 / len(BASELINES):.3f}, not 0.05.")
    print(f"Cost to clear per round trip: {COST_POINTS:.0f} points "
          f"({COST_POINTS * POINT:.2f} USD per ounce).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
