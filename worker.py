import os
import json
from upstash_redis import Redis
from data import DataProvider
from strategy import StevenStrategy
import pandas as pd
from datetime import datetime

# --- CONFIG ---
redis = Redis(url=os.environ.get("UPSTASH_REDIS_REST_URL"), token=os.environ.get("UPSTASH_REDIS_REST_TOKEN"))
dp = DataProvider(os.environ.get("OANDA_API_KEY"), os.environ.get("OANDA_ACCOUNT_ID"))

SYMBOLS = ["EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD", "NZD_USD", "EUR_JPY", "GBP_JPY"]
RISK_PER_TRADE = 0.005 

def run_cycle():
    now = datetime.utcnow()
    # Friday 9PM to Sunday 9PM UTC is CLOSED
    if (now.weekday() == 4 and now.hour >= 21) or now.weekday() == 5 or (now.weekday() == 6 and now.hour < 21):
        if now.weekday() == 4: # Friday night cleanup
            dp.close_all_positions()
            redis.delete("open_trades")
        redis.set("last_scan_logs", json.dumps({"System": "Market Closed"}))
        return

    # Sync balance and closed trades
    broker_pos = dp.get_all_open_positions()
    db_trades = redis.lrange("open_trades", 0, -1)
    balance = float(redis.get("balance") or 10000.0)

    for t_raw in db_trades:
        t = json.loads(t_raw)
        if t['symbol'] not in broker_pos:
            curr = dp.get_live_tick(t['symbol']) or t['entry']
            win = (curr > t['entry']) if t['side']=="BUY" else (curr < t['entry'])
            balance += (balance * 0.01) if win else -(balance * 0.005)
            redis.set("balance", balance)
            redis.lrem("open_trades", 1, t_raw)

    # Scan for new trades
    logs = {}
    for sym in SYMBOLS:
        if dp.is_position_open(sym):
            logs[sym] = "Position live."
            continue
        df_d = dp.get_ohlc(sym, granularity="D", count=250)
        df_h1 = dp.get_ohlc(sym, granularity="H1", count=100)
        if df_d is None or df_h1 is None: continue
        
        strat = StevenStrategy(df_h1, df_d)
        signal, price, sl, tp = strat.check_signals()
        if signal:
            units = int((balance * RISK_PER_TRADE) / abs(price - sl))
            if dp.place_market_order(sym, signal, units, sl, tp):
                trade = {"symbol": sym, "side": signal, "entry": round(price, 5), "sl": round(sl, 5), "tp_2r": round(tp, 5), "time": str(now)[:16]}
                redis.lpush("open_trades", json.dumps(trade))
                logs[sym] = f"TRADE: {signal}"
        else: logs[sym] = "Searching..."
    
    redis.set("last_scan_logs", json.dumps(logs))

if __name__ == "__main__":
    run_cycle()
