import json, datetime as dt
import MetaTrader5 as mt5
UTC = dt.timezone.utc
mt5.initialize()
out={}
# 1) measure server-vs-UTC offset from a live tick
mt5.symbol_select("EURUSDm#", True)
t = mt5.symbol_info_tick("EURUSDm#")
if t:
    srv = dt.datetime.fromtimestamp(t.time, UTC)   # naive-as-UTC reading of server stamp
    real = dt.datetime.now(UTC)
    out["server_minus_utc_hours"] = round((srv-real).total_seconds()/3600, 2)
    out["tick_raw_epoch"] = t.time
    out["tick_read_as_utc"] = str(srv)
    out["true_utc_now"] = str(real)
# 2) tradable majors specs
majors=[]
for s in ("EURUSDm#","GBPUSDm#","USDJPYm#","AUDUSDm#","USDCADm#","USDCHFm#","NZDUSDm#","XAUUSDm#","EURUSD"):
    si = mt5.symbol_info(s)
    if si is None: majors.append({"symbol":s,"found":False}); continue
    mt5.symbol_select(s, True)
    tk = mt5.symbol_info_tick(s)
    r = mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_H1, 0, 2)
    majors.append({"symbol":s,"found":True,"trade_mode":si.trade_mode,
      "digits":si.digits,"point":si.point,"spread_pts":si.spread,"spread_float":si.spread_float,
      "contract_size":si.trade_contract_size,"vol_min":si.volume_min,"vol_max":si.volume_max,"vol_step":si.volume_step,
      "swap_long":si.swap_long,"swap_short":si.swap_short,"swap_mode":si.swap_mode,
      "stops_level":si.trade_stops_level,"freeze_level":si.trade_freeze_level,
      "margin_initial":si.margin_initial,"currency_profit":si.currency_profit,"currency_margin":si.currency_margin,
      "bid":getattr(tk,"bid",None),"ask":getattr(tk,"ask",None),
      "newest_H1_srv":str(dt.datetime.fromtimestamp(int(r[-1][0]),UTC)) if r is not None and len(r) else None,
      "tick_vol":int(r[-1][5]) if r is not None and len(r) else None,
      "real_vol":int(r[-1][6]) if r is not None and len(r) else None,
      "session_deals":si.session_deals,"session_volume":si.session_volume})
out["majors"]=majors
out["trade_mode_map"]={0:"DISABLED",1:"LONGONLY",2:"SHORTONLY",3:"CLOSEONLY",4:"FULL"}
# 3) history depth available
r = mt5.copy_rates_from_pos("EURUSDm#", mt5.TIMEFRAME_D1, 0, 100000)
out["eurusdm_D1_bars"]= 0 if r is None else len(r)
if r is not None and len(r):
    out["eurusdm_D1_oldest"]=str(dt.datetime.fromtimestamp(int(r[0][0]),UTC))
r = mt5.copy_rates_from_pos("EURUSDm#", mt5.TIMEFRAME_M1, 0, 500000)
out["eurusdm_M1_bars"]= 0 if r is None else len(r)
if r is not None and len(r):
    out["eurusdm_M1_oldest"]=str(dt.datetime.fromtimestamp(int(r[0][0]),UTC))
mt5.shutdown()
print(json.dumps(out, indent=2, default=str))
