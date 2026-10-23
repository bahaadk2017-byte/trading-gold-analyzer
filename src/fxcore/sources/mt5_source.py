"""Read-only MT5 market data adapter.

SAFETY: this module contains no order functions. It never calls order_send,
order_check or any position/trade API, and it must stay that way. The account
measured on 2026-10-23 is a REAL XM Global account at 1:1000 leverage with
terminal trade_allowed=true, so a stray write here reaches live money.

Reference: docs/audit/2026-10-23-state-and-sources.md
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from ..clock import ServerClock, is_fx_market_closed
from ..contracts import (
    Bar,
    MarketSnapshot,
    MarketState,
    Provenance,
    Quote,
    SymbolSpec,
    TradeMode,
)

UTC = timezone.utc

# Seconds per MT5 timeframe. Names match the broker's own labels.
TIMEFRAMES = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H4": 14400,
    "D1": 86400,
}

_LICENSE = "broker-account-data"  # our own account's feed at our own broker


class MT5Error(RuntimeError):
    pass


class MT5Source:
    """Fetches validated snapshots from a running, logged-in MT5 terminal."""

    def __init__(self) -> None:
        import MetaTrader5 as mt5  # imported lazily: Windows-only dependency

        self._mt5 = mt5
        self._clock: ServerClock | None = None
        self._server = "unknown"

    # --- lifecycle ---------------------------------------------------------

    def __enter__(self) -> MT5Source:
        if not self._mt5.initialize():
            raise MT5Error(f"initialize failed: {self._mt5.last_error()}")
        info = self._mt5.account_info()
        if info is not None:
            self._server = info.server
        return self

    def __exit__(self, *exc: object) -> None:
        self._mt5.shutdown()

    @property
    def source_id(self) -> str:
        return f"mt5:{self._server}"

    def account_summary(self) -> dict[str, object]:
        """Read-only account facts, including whether this is a REAL account."""
        info = self._mt5.account_info()
        term = self._mt5.terminal_info()
        if info is None:
            raise MT5Error(f"account_info unavailable: {self._mt5.last_error()}")
        return {
            "login": info.login,
            "server": info.server,
            "currency": info.currency,
            "leverage": info.leverage,
            "is_real_account": info.trade_mode == 2,
            "terminal_trade_allowed": bool(term.trade_allowed) if term else None,
            "terminal_connected": bool(term.connected) if term else None,
        }

    # --- clock -------------------------------------------------------------

    def measure_clock(self, reference_symbol: str) -> ServerClock:
        """Measure the server/UTC offset from a live tick (defect 1)."""
        self._select(reference_symbol)
        tick = self._mt5.symbol_info_tick(reference_symbol)
        if tick is None or not tick.time:
            raise MT5Error(f"no tick for {reference_symbol}: {self._mt5.last_error()}")
        self._clock = ServerClock.measure(tick.time, datetime.now(UTC))
        return self._clock

    @property
    def clock(self) -> ServerClock | None:
        return self._clock

    # --- symbol resolution -------------------------------------------------

    def resolve_broker_symbol(self, analysis_symbol: str) -> str:
        """Map a plain name like EURUSD to the one tradable broker symbol.

        Defect 2: `EURUSD` exists but is DISABLED with contract_size 100_000,
        while `EURUSDm#` is tradable with contract_size 1_000. Guessing between
        them is a 100x sizing error, so ambiguity raises instead of picking.
        """
        wanted = analysis_symbol.upper()
        matches = [
            s.name
            for s in self._mt5.symbols_get()
            if s.trade_mode == TradeMode.FULL.value
            and "".join(ch for ch in s.name.upper() if ch.isalpha()).startswith(wanted)
            and len(s.name) - len(wanted) <= 3  # tolerate a short suffix only
        ]
        exact = [m for m in matches if m.upper() == wanted]
        if exact:
            return exact[0]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise MT5Error(f"no tradable broker symbol for {analysis_symbol!r}")
        raise MT5Error(
            f"ambiguous broker symbols for {analysis_symbol!r}: {sorted(matches)} "
            "— name one explicitly rather than let the system guess"
        )

    def symbol_spec(self, analysis_symbol: str, broker_symbol: str) -> SymbolSpec:
        self._select(broker_symbol)
        si = self._mt5.symbol_info(broker_symbol)
        if si is None:
            raise MT5Error(f"symbol_info failed for {broker_symbol}")
        return SymbolSpec(
            analysis_symbol=analysis_symbol.upper(),
            broker_symbol=broker_symbol,
            digits=si.digits,
            point=si.point,
            contract_size=si.trade_contract_size,
            volume_min=si.volume_min,
            volume_max=si.volume_max,
            volume_step=si.volume_step,
            trade_mode=TradeMode(si.trade_mode),
            spread_points=si.spread,
            spread_float=bool(si.spread_float),
            swap_long=si.swap_long,
            swap_short=si.swap_short,
            currency_profit=si.currency_profit,
            currency_margin=si.currency_margin,
            stops_level_points=si.trade_stops_level,
        )

    # --- data --------------------------------------------------------------

    def fetch(
        self,
        analysis_symbol: str,
        timeframe: str,
        n_bars: int,
        broker_symbol: str | None = None,
    ) -> MarketSnapshot:
        """Fetch a snapshot with provenance. Validation is the caller's gate run."""
        if timeframe not in TIMEFRAMES:
            raise ValueError(f"unknown timeframe {timeframe!r}, expected {list(TIMEFRAMES)}")
        tf_seconds = TIMEFRAMES[timeframe]
        broker_symbol = broker_symbol or self.resolve_broker_symbol(analysis_symbol)

        if self._clock is None:
            self.measure_clock(broker_symbol)
        clock = self._clock
        assert clock is not None

        spec = self.symbol_spec(analysis_symbol, broker_symbol)

        started = time.perf_counter()
        rates = self._mt5.copy_rates_from_pos(
            broker_symbol, self._tf_const(timeframe), 0, n_bars
        )
        tick = self._mt5.symbol_info_tick(broker_symbol)
        latency_ms = int((time.perf_counter() - started) * 1000)
        now = datetime.now(UTC)

        # Defect 6: a too-large request returns an empty result, not an error.
        bars = tuple(
            Bar(
                event_time_utc=clock.to_utc(int(r[0])),
                timeframe_seconds=tf_seconds,
                open=float(r[1]),
                high=float(r[2]),
                low=float(r[3]),
                close=float(r[4]),
                tick_updates=int(r[5]),  # broker price updates, NOT volume
            )
            for r in (rates if rates is not None else [])
        )

        quote = None
        if tick is not None and tick.bid and tick.ask:
            quote = Quote(bid=tick.bid, ask=tick.ask, event_time_utc=clock.to_utc(tick.time))

        notes = []
        if rates is None:
            notes.append(f"copy_rates_from_pos returned None: {self._mt5.last_error()}")
        elif len(bars) < n_bars:
            notes.append(f"requested {n_bars} bars, received {len(bars)}")

        return MarketSnapshot(
            spec=spec,
            provenance=Provenance(
                source=self.source_id,
                license=_LICENSE,
                retrieved_at_utc=now,
                latency_ms=latency_ms,
                completeness=(len(bars) / n_bars) if n_bars else 0.0,
                approved_for_decisions=True,
            ),
            market_state=self._market_state(quote, now),
            bars=bars,
            quote=quote,
            margin_required=self._margin(broker_symbol, spec),
            notes=tuple(notes),
        )

    @property
    def max_bars(self) -> int:
        """The terminal's `Max bars in chart` setting. Measured: 100_000.

        Requesting exactly this many, or more, returns zero bars rather than a
        truncated series or an error (measured: 99_000 -> 99_000 bars,
        100_000 -> 0, 200_000 -> 0). It is a cliff, not a ceiling.
        """
        term = self._mt5.terminal_info()
        return int(getattr(term, "maxbars", 0)) if term else 0

    def history_depth(self, broker_symbol: str, timeframe: str) -> dict[str, object]:
        """Report how much history exists, staying under the silent-zero cliff.

        A single request just below the cap returns everything available, so no
        search is needed. An earlier doubling probe reported 65536 bars for every
        M15 series — that was 2^16, the last power of two under the 100_000 cap,
        not the real depth.
        """
        self._select(broker_symbol)
        cap = self.max_bars
        if cap <= 0:
            raise MT5Error("terminal maxbars unavailable; cannot bound the request")
        request = cap - 1000
        rates = self._mt5.copy_rates_from_pos(
            broker_symbol, self._tf_const(timeframe), 0, request
        )
        count = 0 if rates is None else len(rates)
        clock = self._clock
        to_utc = clock.to_utc if clock else (lambda _e: None)
        return {
            "symbol": broker_symbol,
            "timeframe": timeframe,
            "bars": count,
            "oldest_utc": to_utc(int(rates[0][0])) if count else None,
            "newest_utc": to_utc(int(rates[-1][0])) if count else None,
            "cap_limited": count >= request,  # true depth may exceed this
            "terminal_max_bars": cap,
        }

    # --- internals ---------------------------------------------------------

    def _select(self, broker_symbol: str) -> None:
        """Defect 3: without symbol_select the first read returned 2024 bars
        alongside live ticks, with a clean last_error()."""
        if not self._mt5.symbol_select(broker_symbol, True):
            raise MT5Error(
                f"symbol_select failed for {broker_symbol}: {self._mt5.last_error()}"
            )

    def _tf_const(self, timeframe: str) -> int:
        return getattr(self._mt5, f"TIMEFRAME_{timeframe}")

    def _margin(self, broker_symbol: str, spec: SymbolSpec) -> float | None:
        """Defect 5: symbol_info.margin_initial reads 0.0 and is not the margin.

        order_calc_margin is a pure calculation; it places nothing.
        """
        tick = self._mt5.symbol_info_tick(broker_symbol)
        if tick is None or not tick.ask:
            return None
        margin = self._mt5.order_calc_margin(
            self._mt5.ORDER_TYPE_BUY, broker_symbol, spec.volume_min, tick.ask
        )
        return float(margin) if margin else None

    def _market_state(self, quote: Quote | None, now: datetime) -> MarketState:
        if quote is not None and (now - quote.event_time_utc).total_seconds() < 120:
            return MarketState.OPEN
        if is_fx_market_closed(now):
            return MarketState.CLOSED
        return MarketState.UNKNOWN
