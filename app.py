import os
import json
from flask import Flask, render_template, redirect, url_for, jsonify, request
from upstash_redis import Redis
from data import DataProvider
from strategy import StevenStrategy
import pandas as pd
from datetime import datetime

app = Flask(__name__)

# --- SECURE CONFIG ---
REDIS_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
OANDA_TOKEN = os.environ.get("OANDA_API_KEY")
OANDA_ACCT = os.environ.get("OANDA_ACCOUNT_ID")

redis = Redis(url=REDIS_URL, token=REDIS_TOKEN)
dp = DataProvider(OANDA_TOKEN, OANDA_ACCT)

SYMBOLS = ["EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD"]
INITIAL_BALANCE = 10000.0
RISK_PER_TRADE = 0.005 

# --- MARKET TIME MANAGEMENT ---

def get_market_status():
    """
    Forex closes Friday 5 PM EST, opens Sunday 5 PM EST.
    UTC Translation: Fri 10 PM to Sun 10 PM UTC.
    """
    now_utc = datetime.utcnow()
    day = now_utc.weekday() # 0=Mon, 4=Fri, 5=Sat, 6=Sun
    hour = now_utc.hour

    if day == 4 and hour >= 21: return "CLOSING"
    if day == 5 or (day == 6 and hour < 21): return "CLOSED"
    return "OPEN"

# --- CORE SETTLEMENT LOGIC ---

def settle_and_sync():
    """Cleans up closed trades and updates balance"""
    try:
        broker_positions = dp.get_all_open_positions()
        db_trades = redis.lrange("open_trades", 0, -1)
        balance = float(redis.get("balance") or INITIAL_BALANCE)

        for t_raw in db_trades:
            trade = json.loads(t_raw.decode('utf-8') if hasattr(t_raw, 'decode') else t_raw)
            if trade['symbol'] not in broker_positions:
                # Trade finished on OANDA app
                curr = dp.get_live_tick(trade['symbol']) or trade['entry']
                win = (curr > trade['entry']) if trade['side']=="BUY" else (curr < trade['entry'])
                change = (balance * 0.01) if win else -(balance * 0.005)
                redis.set("balance", balance + change)
                redis.lrem("open_trades", 1, t_raw)
    except Exception as e:
        redis.set("sys_error", f"Sync Error: {str(e)}")

# --- ROUTES ---

@app.route('/')
def home():
    try:
        status = get_market_status()
        balance = float(redis.get("balance") or INITIAL_BALANCE)
        trades = []
        
        for t in redis.lrange("open_trades", 0, -1):
            try:
                trade = json.loads(t.decode('utf-8') if hasattr(t, 'decode') else t)
                if status == "OPEN":
                    curr = dp.get_live_tick(trade['symbol'])
                    if curr:
                        trade['current_price'] = round(curr, 5)
                        diff = (curr - trade['entry']) if trade['side'] == "BUY" else (trade['entry'] - curr)
                        trade['pl_pct'] = round((diff / trade['entry']) * 100, 4)
                trades.append(trade)
            except: continue

        logs = json.loads(redis.get("last_scan_logs") or "{}")
        err = redis.get("sys_error")
        
        return render_template('index.html', balance=balance, trades=trades, 
                               db_status="Connected", data_status=status, 
                               logic_status="Active" if status == "OPEN" else "Sleeping",
                               last_logs=logs, error=err)
    except Exception as e:
        return f"UI Crash: {e}"

@app.route('/tick')
def tick():
    """
    ROBOT-OPTIMIZED ROUTE
    Returns JSON 200 immediately to Cron-job.org to prevent 'Failed' errors.
    """
    status = get_market_status()
    logs = {}
    
    # 1. Friday Safety
    if status == "CLOSING":
        dp.close_all_positions()
        redis.delete("open_trades")
        logs["System"] = "Friday Close: All trades flattened."
    
    # 2. Weekend Sleep
    elif status == "CLOSED":
        logs["System"] = "Weekend: Markets closed."
    
    # 3. Active Trading
    else:
        settle_and_sync()
        balance = float(redis.get("balance") or INITIAL_BALANCE)
        for sym in SYMBOLS:
            if dp.is_position_open(sym):
                logs[sym] = "Position live."
                continue

            df_d = dp.get_ohlc(sym, granularity="D", count=250)
            df_h1 = dp.get_ohlc(sym, granularity="H1", count=100)
            if not df_d or not df_h1: continue
            
            strat = StevenStrategy(df_h1, df_d)
            signal, price, sl, tp_2r = strat.check_signals()
            
            if signal:
                units = int((balance * RISK_PER_TRADE) / abs(price - sl))
                if dp.place_market_order(sym, signal, units, sl, tp_2r):
                    trade_data = {"symbol": sym, "side": signal, "entry": round(price, 5),
                                  "sl": round(sl, 5), "tp_2r": round(tp_2r, 5), 
                                  "status": "LIVE", "time": str(pd.Timestamp.now())}
                    redis.lpush("open_trades", json.dumps(trade_data))
                    logs[sym] = f"TRADE: {signal}"
            else:
                logs[sym] = "No setup."

    redis.set("last_scan_logs", json.dumps(logs), ex=3600)

    # --- THE FIX FOR CRON-JOB.ORG ---
    # We return a clean JSON response with a 200 status code. 
    # This prevents the 'HTTP error' on the cron dashboard.
    return jsonify({"status": "success", "market": status}), 200

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
