"""FastAPI dashboard server — read-only monitoring interface.

Endpoints:
  GET /                          → index.html (RTL Arabic dashboard)
  GET /api/runs                  → list of run summaries
  GET /api/runs/latest           → latest run record
  GET /api/runs/{record_id}      → specific run
  GET /api/agents                → agent definitions from frontmatter
  GET /api/news                  → all news (cached 5 min)
  GET /api/news/pairs            → news for ?pairs=EURUSD,GBPUSD
  GET /api/system                → system status from latest run
  GET /api/backtests             → backtest run list + per-pair summary
  GET /api/backtests/{record_id} → backtest detail with equity curve
  GET /api/contexts/{pair}        → latest context-only view for one pair

No POST, no PUT, no DELETE, no execution endpoints.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .agents import list_agents
from .backtest_reader import equity_curve, get_backtest_run, list_backtest_runs, pair_summary
from .context_reader import get_context_view
from .deliberation_reader import get_deliberation, list_deliberations
from .gold_analyzer import GoldLiveAnalyzer
from .news_cache import fetch_all, fetch_relevant
from .reader import get_latest_run, get_run, list_runs

app = FastAPI(
    title="FX Analysis Dashboard",
    description="Read-only monitoring. Execution is DISABLED system-wide.",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url=None,
)

STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

# Initialize Gold Analyzer
gold_analyzer = GoldLiveAnalyzer()

# Alpine evaluates the local templates with Function(). Inline scripts remain blocked.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self' https://cdn.jsdelivr.net 'unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; "
    "frame-src https://www.tradingview.com https://s.tradingview.com; "
    "connect-src 'self'; "
    "img-src 'self' data:; "
    "base-uri 'self'; object-src 'none'; frame-ancestors 'self'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(str(STATIC / "index.html"))


@app.get("/gold", include_in_schema=False)
def gold() -> FileResponse:
    return FileResponse(str(STATIC / "gold.html"))


# ---------- runs --------------------------------------------------------------


@app.get("/api/runs")
def api_list_runs(limit: int = Query(default=20, ge=1, le=100)) -> JSONResponse:
    return JSONResponse({"runs": list_runs(limit)})


@app.get("/api/runs/latest")
def api_latest_run() -> JSONResponse:
    run = get_latest_run()
    if run is None:
        raise HTTPException(status_code=404, detail="لا توجد تشغيلات مسجّلة")
    return JSONResponse(run)


@app.get("/api/runs/{record_id}")
def api_get_run(record_id: str) -> JSONResponse:
    run = get_run(record_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"التشغيل {record_id!r} غير موجود")
    return JSONResponse(run)


# ---------- agents ------------------------------------------------------------


@app.get("/api/agents")
def api_agents() -> JSONResponse:
    return JSONResponse({"agents": list_agents()})


# ---------- news --------------------------------------------------------------


@app.get("/api/news")
def api_news() -> JSONResponse:
    try:
        return JSONResponse(fetch_all())
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc), "classification": "untrusted"}, status_code=503)


@app.get("/api/news/pairs")
def api_news_pairs(pairs: str = Query(description="Comma-separated pair list, e.g. EURUSD,GBPUSD")) -> JSONResponse:
    pair_list = [p.strip().upper() for p in pairs.split(",") if p.strip()]
    if not pair_list:
        raise HTTPException(status_code=422, detail="يجب تحديد زوج واحد على الأقل")
    try:
        return JSONResponse(fetch_relevant(pair_list))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc), "classification": "untrusted"}, status_code=503)


# ---------- system status -----------------------------------------------------


@app.get("/api/system")
def api_system() -> JSONResponse:
    run = get_latest_run()
    if run is None:
        return JSONResponse({
            "status": "DATA_MISSING",
            "message": "لا توجد تشغيلات مسجّلة. شغّل scripts/analyze.py أولًا.",
        })
    acct = run.get("account", {})
    return JSONResponse({
        "status": "ok",
        "environment": run.get("environment"),
        "execution_enabled": False,
        "server": acct.get("server"),
        "currency": acct.get("currency"),
        "leverage": acct.get("leverage"),
        "is_real_account": acct.get("is_real_account"),
        "terminal_connected": acct.get("terminal_connected"),
        "terminal_trade_allowed": acct.get("terminal_trade_allowed"),
        "server_offset_hours": run.get("server_offset_hours"),
        "clock_warning": run.get("clock_warning"),
        "last_run_utc": run.get("started_utc"),
        "record_id": run.get("record_id"),
    })


# ---------- context-only integrations -----------------------------------------


@app.get("/api/contexts/{pair}")
def api_context(pair: str) -> JSONResponse:
    context = get_context_view(pair)
    if context is None:
        raise HTTPException(status_code=404, detail=f"context for {pair!r} not found")
    return JSONResponse(context)


# ---------- deliberations -----------------------------------------------------


@app.get("/api/deliberations")
def api_list_deliberations(limit: int = Query(default=30, ge=1, le=200)) -> JSONResponse:
    """List strategy deliberation records (static role assessments, not live communication)."""
    runs = list_deliberations(limit)
    return JSONResponse({
        "runs": runs,
        "disclaimer_ar": "سجل ثابت لمداولات الأدوار — ليس محادثة وكلاء حية، ولا يشكل قرار تداول أو موافقة تنفيذ",
    })


@app.get("/api/deliberations/{record_id}")
def api_get_deliberation(record_id: str) -> JSONResponse:
    """Get a specific deliberation record with full role assessments."""
    delib = get_deliberation(record_id)
    if delib is None:
        raise HTTPException(status_code=404, detail=f"deliberation {record_id!r} not found")
    return JSONResponse(delib)


# ---------- backtests ---------------------------------------------------------


@app.get("/api/backtests")
def api_list_backtests(limit: int = Query(default=30, ge=1, le=200)) -> JSONResponse:
    runs = list_backtest_runs(limit)
    return JSONResponse({
        "runs": runs,
        "pair_summary": pair_summary(runs),
    })


@app.get("/api/backtests/{record_id}")
def api_get_backtest(record_id: str) -> JSONResponse:
    bt = get_backtest_run(record_id)
    if bt is None:
        raise HTTPException(status_code=404, detail=f"backtest {record_id!r} not found")
    trades = bt.get("trades", [])
    bt["equity_curve"] = equity_curve(trades)
    return JSONResponse(bt)


# ---------- gold analysis --------------------------------------------------------


@app.get("/api/gold/analysis")
def api_gold_analysis() -> JSONResponse:
    """Get complete Gold (XAUUSD) analysis with Price Action, Volume Profile, Order Flow."""
    try:
        # Return cached analysis directly
        result = gold_analyzer.cache
        if result:
            return JSONResponse(result)
        # If no cache yet, return empty (initialization hasn't run)
        return JSONResponse({
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "current_price": 0,
            "bars": [],
            "price_action": {},
            "volume_profile": {},
            "order_flow": {},
            "levels": {},
            "signals": [],
            "technicals": {},
        })
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.exception("Gold analysis error: %s", exc)
        return JSONResponse(
            {"error": str(exc), "status": "error"},
            status_code=503
        )


@app.get("/api/gold/signals")
def api_gold_signals() -> JSONResponse:
    """Get only the trade signals for Gold."""
    try:
        result = gold_analyzer.cache or {}
        return JSONResponse({
            "timestamp": result.get("timestamp", datetime.utcnow().isoformat() + "Z"),
            "current_price": result.get("current_price", 0),
            "signals": result.get("signals", []),
        })
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            {"error": str(exc), "status": "error"},
            status_code=503
        )


@app.get("/api/gold/chart-data")
def api_gold_chart_data() -> JSONResponse:
    """Get chart data (OHLCV + technicals) for Gold."""
    try:
        result = gold_analyzer.cache or {}
        return JSONResponse({
            "timestamp": result.get("timestamp", datetime.utcnow().isoformat() + "Z"),
            "bars": result.get("bars", []),
            "technicals": result.get("technicals", {}),
            "levels": result.get("levels", {}),
        })
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            {"error": str(exc), "status": "error"},
            status_code=503
        )
