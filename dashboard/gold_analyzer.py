"""Gold (XAUUSD) Live Analyzer — Price Action + Volume Profile + Order Flow.

Provides real-time analysis with:
- Price Action patterns (Rejection, Engulfing, Pin Bars, Double Top)
- Volume Profile (VPOC levels)
- Order Flow (buying/selling pressure)
- Support/Resistance levels
- Trade signals with R/R ratios
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


class GoldLiveAnalyzer:
    """Real-time Gold analysis engine."""

    def __init__(self, tv_client=None):
        """Initialize analyzer with optional TradingView client."""
        self.tv = tv_client
        self.update_interval = 30  # seconds
        self.last_update: datetime | None = None
        # Initialize with demo data
        self.cache = self._generate_demo_analysis()
        self.last_update = datetime.utcnow()

    def _generate_demo_analysis(self) -> dict[str, Any]:
        """Generate realistic demo data for development."""
        bars = self._generate_mock_bars(50)

        return {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "current_price": 4020.5,
            "bars": bars[-10:],  # Last 10 for chart
            "price_action": {
                "patterns": [
                    {"type": "rejection_candle", "direction": "down", "strength": 1.8},
                    {"type": "pin_bar", "direction": "rejection"},
                ],
                "trend": "down",
                "volatility": 8.5,
            },
            "volume_profile": {
                "vpoc": [
                    {"price": 4024.325, "volume": 5268, "strength": 5},
                    {"price": 4023.24, "volume": 5216, "strength": 5},
                    {"price": 4022.165, "volume": 4718, "strength": 4},
                    {"price": 4021.935, "volume": 4514, "strength": 4},
                    {"price": 4020.87, "volume": 3586, "strength": 3},
                ],
                "highest_volume": 5268,
                "avg_volume": 3200,
            },
            "order_flow": {
                "buying_pressure": 4200,
                "selling_pressure": 6800,
                "dominance": "sell",
                "strength": 0.24,
            },
            "levels": {
                "support": [
                    {"price": 4015.0, "strength": "medium", "type": "recent_low"},
                    {"price": 4010.0, "strength": "vpoc", "type": "vpoc"},
                    {"price": 4005.0, "strength": "strong", "type": "vpoc"},
                ],
                "resistance": [
                    {"price": 4025.795, "strength": "strong", "type": "recent_high"},
                    {"price": 4024.325, "strength": "vpoc", "type": "vpoc"},
                    {"price": 4023.24, "strength": "vpoc", "type": "vpoc"},
                ],
                "current_price": 4020.5,
            },
            "signals": [
                {
                    "type": "SELL",
                    "entry": 4018.0,
                    "target_1": 4015.0,
                    "target_2": 4010.0,
                    "stop_loss": 4025.0,
                    "risk_reward": 1.67,
                    "confidence": 0.68,
                    "reason": "Rejection Candle from 4025 + Volume Profile break + Strong Sell Pressure",
                    "status": "ACTIVE",
                },
                {
                    "type": "BUY",
                    "entry": 4022.0,
                    "target_1": 4025.0,
                    "target_2": 4030.0,
                    "stop_loss": 4018.0,
                    "risk_reward": 1.25,
                    "confidence": 0.35,
                    "reason": "Potential bounce from support + Uptrend signal",
                    "status": "PENDING",
                },
            ],
            "technicals": {
                "rsi": 42.5,
                "macd": -2.1,
                "stoch_k": 35.2,
                "stoch_d": 42.8,
                "cci": -45.3,
                "adx": 28.5,
            },
        }

    def should_refresh(self) -> bool:
        """Check if cache should be refreshed."""
        if self.last_update is None:
            return True
        return (datetime.utcnow() - self.last_update).total_seconds() > self.update_interval

    def analyze(self) -> dict[str, Any]:
        """Run complete analysis on XAUUSD (synchronous)."""
        if not self.should_refresh():
            return self.cache

        try:
            # 1. Fetch OHLCV data
            bars = self._fetch_bars()
            if not bars:
                logger.warning("No bars fetched, returning cached data")
                return self.cache

            # 2. Calculate technical indicators
            technicals = self._fetch_technicals()

            # 3. Price Action analysis
            price_action = self._analyze_price_action(bars)

            # 4. Volume Profile
            volume_profile = self._calculate_volume_profile(bars)

            # 5. Order Flow
            order_flow = self._analyze_order_flow(bars)

            # 6. Support/Resistance levels
            levels = self._calculate_levels(bars, volume_profile)

            # 7. Generate trade signals
            signals = self._generate_signals(
                bars, technicals, price_action, order_flow, levels
            )

            # 8. Update cache
            self.cache = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "current_price": float(bars[-1]["c"]) if bars else None,
                "bars": bars[-10:],  # Last 10 candles for chart
                "price_action": price_action,
                "volume_profile": volume_profile,
                "order_flow": order_flow,
                "levels": levels,
                "signals": signals,
                "technicals": technicals,
            }
            self.last_update = datetime.utcnow()
            return self.cache

        except Exception as e:
            logger.exception("Analysis failed: %s", e)
            return self.cache

    def _fetch_bars(self, count: int = 100) -> list[dict]:
        """Fetch OHLCV bars from TradingView or return mock data."""
        try:
            # Try to use TradingView if available
            if self.tv:
                result = self.tv.get_ohlcv(
                    symbol="OANDA:XAUUSD",
                    interval="5m",
                    count=count,
                )
                bars = []
                for bar in result.get("bars", []):
                    bars.append({
                        "t": bar["t"],
                        "o": bar["o"],
                        "h": bar["h"],
                        "l": bar["l"],
                        "c": bar["c"],
                        "v": bar["v"],
                    })
                return bars
        except Exception as e:
            logger.error("Failed to fetch bars from TradingView: %s", e)

        # Return mock data for demo purposes
        return self._generate_mock_bars(count)

    def _generate_mock_bars(self, count: int = 100) -> list[dict]:
        """Generate mock OHLCV bars for demonstration."""
        bars = []
        current_price = 4020.0
        timestamp = int(datetime.utcnow().timestamp())

        for i in range(count):
            # Generate realistic candles
            change = random.uniform(-2, 2)
            open_price = current_price
            close_price = open_price + change
            high_price = max(open_price, close_price) + random.uniform(0, 2)
            low_price = min(open_price, close_price) - random.uniform(0, 2)
            volume = random.randint(1500, 5000)

            bars.append({
                "t": timestamp + (i * 300),
                "o": round(open_price, 2),
                "h": round(high_price, 2),
                "l": round(low_price, 2),
                "c": round(close_price, 2),
                "v": volume,
            })

            current_price = close_price

        return bars

    def _fetch_technicals(self) -> dict[str, float]:
        """Fetch technical indicators from TradingView."""
        if not self.tv:
            return {}

        try:
            result = self.tv.get_technicals_rating(
                symbol="OANDA:XAUUSD",
                interval="5m",
            )
            return {
                "rsi": result.get("RSI", 50),
                "macd": result.get("MACD", {"value": 0}).get("value", 0),
                "stoch_k": result.get("Stoch K", 50),
                "stoch_d": result.get("Stoch D", 50),
                "cci": result.get("CCI20", 0),
                "adx": result.get("ADX", 0),
            }
        except Exception as e:
            logger.error("Failed to fetch technicals: %s", e)
            return {}

    def _analyze_price_action(self, bars: list[dict]) -> dict[str, Any]:
        """Analyze price action patterns."""
        if len(bars) < 3:
            return {}

        patterns = []

        # Analyze last 5 candles
        for i in range(max(0, len(bars) - 5), len(bars) - 1):
            bar = bars[i]

            # Rejection Candle
            high_wick = bar["h"] - max(bar["o"], bar["c"])
            body_size = abs(bar["c"] - bar["o"])

            if high_wick > body_size * 1.5:
                patterns.append({
                    "type": "rejection_candle",
                    "direction": "down" if bar["c"] < bar["o"] else "up",
                    "strength": high_wick / body_size if body_size > 0 else 1,
                })

            # Pin Bar
            if high_wick > body_size * 2 or (bar["l"] - min(bar["o"], bar["c"])) > body_size * 2:
                patterns.append({"type": "pin_bar", "direction": "rejection"})

        # Double Top detection
        if len(bars) >= 4:
            bar1 = bars[-4]
            bar2 = bars[-2]
            if abs(bar1["h"] - bar2["h"]) < 5 and bars[-3]["c"] < bar1["h"] - 5:
                patterns.append({
                    "type": "double_top",
                    "price": (bar1["h"] + bar2["h"]) / 2,
                    "strength": "strong",
                })

        return {
            "patterns": patterns,
            "trend": "up" if bars[-1]["c"] > bars[-5]["c"] else "down",
            "volatility": max(b["h"] - b["l"] for b in bars[-10:]) if bars else 0,
        }

    def _calculate_volume_profile(self, bars: list[dict]) -> dict[str, Any]:
        """Calculate Volume Point of Control (VPOC) levels."""
        price_volumes = {}

        for bar in bars:
            price_level = round(bar["c"] * 2) / 2
            if price_level not in price_volumes:
                price_volumes[price_level] = 0
            price_volumes[price_level] += bar["v"]

        sorted_levels = sorted(price_volumes.items(), key=lambda x: x[1], reverse=True)

        vpoc_levels = [
            {
                "price": float(price),
                "volume": int(vol),
                "strength": min(5, max(1, int(vol / 1000))),
            }
            for price, vol in sorted_levels[:5]
        ]

        return {
            "vpoc": vpoc_levels,
            "highest_volume": int(sorted_levels[0][1]) if sorted_levels else 0,
            "avg_volume": int(sum(v for _, v in price_volumes.items()) / len(price_volumes))
            if price_volumes else 0,
        }

    def _analyze_order_flow(self, bars: list[dict]) -> dict[str, Any]:
        """Analyze order flow (buying vs selling pressure)."""
        if not bars:
            return {}

        buying_pressure = 0
        selling_pressure = 0

        for bar in bars[-5:]:
            close_ratio = (bar["c"] - bar["l"]) / (bar["h"] - bar["l"]) if bar["h"] > bar["l"] else 0.5

            if close_ratio > 0.7:
                buying_pressure += bar["v"]
            elif close_ratio < 0.3:
                selling_pressure += bar["v"]

        total = buying_pressure + selling_pressure

        return {
            "buying_pressure": int(buying_pressure),
            "selling_pressure": int(selling_pressure),
            "dominance": "buy" if buying_pressure > selling_pressure else "sell",
            "strength": (
                abs(buying_pressure - selling_pressure) / total
                if total > 0
                else 0
            ),
        }

    def _calculate_levels(self, bars: list[dict], volume_profile: dict) -> dict[str, list]:
        """Calculate support and resistance levels."""
        if not bars:
            return {}

        recent_high = max(b["h"] for b in bars[-20:])
        recent_low = min(b["l"] for b in bars[-20:])
        current = bars[-1]["c"]

        support = []
        if current > recent_low:
            support.append({
                "price": round(recent_low, 2),
                "strength": "strong",
                "type": "recent_low"
            })

        for vpoc in volume_profile.get("vpoc", []):
            if vpoc["price"] < current:
                support.append({
                    "price": vpoc["price"],
                    "strength": "vpoc",
                    "type": "vpoc"
                })

        resistance = []
        if current < recent_high:
            resistance.append({
                "price": round(recent_high, 2),
                "strength": "strong",
                "type": "recent_high",
            })

        for vpoc in volume_profile.get("vpoc", []):
            if vpoc["price"] > current:
                resistance.append({
                    "price": vpoc["price"],
                    "strength": "vpoc",
                    "type": "vpoc"
                })

        return {
            "support": sorted(support, key=lambda x: x["price"], reverse=True)[:3],
            "resistance": sorted(resistance, key=lambda x: x["price"])[:3],
            "current_price": round(current, 2),
        }

    def _generate_signals(
        self, bars: list[dict], technicals: dict, price_action: dict,
        order_flow: dict, levels: dict,
    ) -> list[dict]:
        """Generate trade signals based on all analysis."""
        signals = []
        current = bars[-1]["c"] if bars else 0
        rsi = technicals.get("rsi", 50)
        macd = technicals.get("macd", 0)

        # SELL signal
        if (
            rsi < 35 and macd < 0 and order_flow.get("dominance") == "sell"
            and any(p.get("type") == "rejection_candle" for p in price_action.get("patterns", []))
        ):
            support_levels = levels.get("support", [])
            target_1 = support_levels[0]["price"] if support_levels else current - 5
            target_2 = support_levels[1]["price"] if len(support_levels) > 1 else current - 10

            entry = round(current, 2)
            stop = round(max(b["h"] for b in bars[-5:]), 2) + 2
            r_r = (entry - target_1) / (stop - entry) if stop > entry else 0

            signals.append({
                "type": "SELL",
                "entry": entry,
                "target_1": round(target_1, 2),
                "target_2": round(target_2, 2),
                "stop_loss": stop,
                "risk_reward": round(r_r, 2),
                "confidence": min(0.9, 0.6 + abs(order_flow.get("strength", 0))),
                "reason": "Rejection Candle + Strong Sell Pressure + Volume Break",
                "status": "ACTIVE" if r_r >= 1.5 else "PENDING",
            })

        # BUY signal
        if (
            rsi > 65 and macd > 0 and order_flow.get("dominance") == "buy"
            and price_action.get("trend") == "up"
        ):
            resistance_levels = levels.get("resistance", [])
            target_1 = resistance_levels[0]["price"] if resistance_levels else current + 5
            target_2 = resistance_levels[1]["price"] if len(resistance_levels) > 1 else current + 10

            entry = round(current, 2)
            stop = round(min(b["l"] for b in bars[-5:]), 2) - 2
            r_r = (target_1 - entry) / (entry - stop) if entry > stop else 0

            signals.append({
                "type": "BUY",
                "entry": entry,
                "target_1": round(target_1, 2),
                "target_2": round(target_2, 2),
                "stop_loss": stop,
                "risk_reward": round(r_r, 2),
                "confidence": min(0.9, 0.6 + abs(order_flow.get("strength", 0))),
                "reason": "Uptrend + Strong Buy Pressure + VPOC Support",
                "status": "ACTIVE" if r_r >= 1.5 else "PENDING",
            })

        return signals
