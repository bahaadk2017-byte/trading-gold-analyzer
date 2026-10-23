import json, datetime as dt
import MetaTrader5 as mt5
UTC = dt.timezone.utc
mt5.initialize()
out={}
# which forex symbols exist / naming & suffixes
syms = mt5.symbols_get()
fx = [s.name for s in syms if s.path.lower().startswith("forex")]
out["forex_count"] = len(fx)
out["forex_sample"] = fx[:40]
out["paths_sample"] = sorted({s.path.rsplit("\\",1)[0] for s in syms})[:25]
# tradable majors?
tradable = [s.name for s in syms if s.path.lower().startswith("forex") and s.trade_mode!=0]
out["forex_tradable_count"] = len(tradable)
out["forex_tradable_sample"] = tradable[:20]
# history depth per timeframe for EURUSD after select
mt5.symbol_select("EURUSD", True)
res={}
for tfname, tf in (("M1",mt5.TIMEFRAME_M1),("M15",mt5.TIMEFRAME_M15),("H1",mt5.TIMEFRAME_H1),("H4",mt5.TIMEFRAME_H4),("D1",mt5.TIMEFRAME_D1)):
    r = mt5.copy_rates_from_pos("EURUSD", tf, 0, 5)
    res[tfname] = {"n": 0 if r is None else len(r),
                   "newest_utc": str(dt.datetime.fromtimestamp(int(r[-1][0]), UTC)) if r is not None and len(r) else None,
                   "err": mt5.last_error() if r is None else None}
out["eurusd_tf_newest"] = res
# explicit recent range request (forces history fetch)
now = dt.datetime.now(UTC)
r = mt5.copy_rates_range("EURUSD", mt5.TIMEFRAME_H1, now - dt.timedelta(days=5), now)
out["range_last5d_H1"] = {"n": 0 if r is None else len(r),
    "newest_utc": str(dt.datetime.fromtimestamp(int(r[-1][0]), UTC)) if r is not None and len(r) else None,
    "err": mt5.last_error() if r is None else None}
out["now_utc"] = str(now)
out["account_trade_mode_meaning"] = {0:"DEMO",1:"CONTEST",2:"REAL"}.get(mt5.account_info().trade_mode)
mt5.shutdown()
print(json.dumps(out, indent=2, default=str))
