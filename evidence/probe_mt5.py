import json, datetime as dt
try:
    import MetaTrader5 as mt5
except Exception as e:
    print(json.dumps({"import_error": repr(e)})); raise SystemExit(0)

out = {"import": "ok"}
ok = mt5.initialize()
out["initialize"] = bool(ok)
if not ok:
    out["last_error"] = mt5.last_error()
    print(json.dumps(out, default=str)); raise SystemExit(0)

ti = mt5.terminal_info()
ai = mt5.account_info()
out["terminal"] = {k: getattr(ti, k, None) for k in ("company","name","connected","trade_allowed","build","data_path")} if ti else None
out["account"] = {"login": ai.login, "server": ai.server, "currency": ai.currency,
                  "trade_mode": ai.trade_mode, "leverage": ai.leverage,
                  "margin_mode": ai.margin_so_mode} if ai else None
out["symbols_total"] = mt5.symbols_total()
probe = []
for s in ("EURUSD","GBPUSD","USDJPY","XAUUSD"):
    si = mt5.symbol_info(s)
    if si is None:
        probe.append({"symbol": s, "found": False}); continue
    t = mt5.symbol_info_tick(s)
    rates = mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_H1, 0, 3)
    probe.append({
        "symbol": s, "found": True, "visible": si.visible, "digits": si.digits,
        "point": si.point, "spread": si.spread, "trade_mode": si.trade_mode,
        "volume_min": si.volume_min, "volume_step": si.volume_step,
        "swap_long": si.swap_long, "swap_short": si.swap_short,
        "tick_bid": getattr(t, "bid", None), "tick_ask": getattr(t, "ask", None),
        "tick_time_utc": str(dt.datetime.utcfromtimestamp(t.time)) if t else None,
        "bars_returned": 0 if rates is None else len(rates),
        "last_bar_utc": str(dt.datetime.utcfromtimestamp(int(rates[-1][0]))) if rates is not None and len(rates) else None,
        "last_bar_tick_volume": int(rates[-1][5]) if rates is not None and len(rates) else None,
        "last_bar_real_volume": int(rates[-1][6]) if rates is not None and len(rates) and len(rates[-1])>6 else None,
    })
out["probe"] = probe
out["now_utc"] = str(dt.datetime.utcnow())
mt5.shutdown()
print(json.dumps(out, indent=2, default=str))
