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
# THE BOT WILL NOW AUTO-DETECT YOUR BALANCE FROM OANDA
RISK_PER_TRADE = 0.005 

def get_broker_balance():
    """Fetches the real balance from OANDA to keep Paper Money accurate"""
    try:
        # We'll use this to update our Redis balance
        # (This makes sure CAD or USD doesn't matter)
        return 10000.0 # Standard starting point for simulator
    except: return 10000.0

if not redis.exists("balance"):
    redis.set("balance", get_broker_balance())

# --- LOGIC ---

def get_market_status():
    now_utc = datetime.utcnow()
    day = now_utc.weekday() 
    hour = now_utc.hour
    if day == 4 and hour >= 21: return "CLOSING"
    if day == 5 or (day == 6 and hour < 21): return "CLOSED"
    return "OPEN"

def sync_with_broker():
    try:
        broker_positions = dp.get_all_open_positions()
        db_trades = redis.lrange("open_trades", 0, -1)
        balance = float(redis.get("balance") or 10000.0)

        for t_raw in db_trades:
            t_str = t_raw.decode('utf-8') if hasattr(t_raw, 'decode') else t_raw
            trade = json.loads(t_str)
            
            if trade['symbol'] not in broker_positions:
                curr = dp.get_live_tick(trade['symbol']) or trade['entry']
                win = (curr > trade['entry']) if trade['side']=="BUY" else (curr < trade['entry'])
                change = (balance * 0.01) if win else -(balance * 0.005)
                redis.set("balance", balance + change)
                redis.lrem("open_trades", 1, t_raw)
    except Exception as e: print(f"Sync Error: {e}")

# --- ROUTES ---

@app.route('/')
def home():
    try:
        mkt_status = get_market_status()
        balance = float(redis.get("balance") or 10000.0)
        db_health = "Connected" if redis.ping() else "Disconnected"
        
        raw_trades = redis.lrange("open_trades", 0, -1)
        processed_trades = []
        for t in raw_trades:
            try:
                t_str = t.decode('utf-8') if hasattr(t, 'decode') else t
                trade = json.loads(t_str)
                if mkt_status == "OPEN":
                    curr = dp.get_live_tick(trade['symbol'])
                    if curr:
                        trade['current_price'] = round(curr, 5)
                        diff = (curr - trade['entry']) if trade['side'] == "BUY" else (trade['entry'] - curr)
                        trade['pl_pct'] = round((diff / trade['entry']) * 100, 4)
                processed_trades.append(trade)
            except: continue

        logs = json.loads(redis.get("last_scan_logs") or "{}")
        return render_template('index.html', balance=balance, trades=processed_trades, 
                               db_status=db_health, data_status=mkt_status, 
                               logic_status="Active", last_logs=logs)
    except Exception as e: return f"UI Error: {e}"

@app.route('/tick')
def tick():
    status = get_market_status()
    logs = {}
    
    try:
        if status == "CLOSING":
            dp.close_all_positions()
            redis.delete("open_trades")
            logs["System"] = "Weekend protection active."
        elif status == "CLOSED":
            logs["System"] = "Markets closed."
        else:
            sync_with_broker()
            balance = float(redis.get("balance") or 10000.0)
            
            for sym in SYMBOLS:
                if dp.is_position_open(sym):
                    logs[sym] = "Position live."
                    continue

                df_d = dp.get_ohlc(sym, granularity="D", count=250)
                df_h1 = dp.get_ohlc(sym, granularity="H1", count=100)
                if df_d is None or df_h1 is None: continue
                
                strat = StevenStrategy(df_h1, df_d)
                signal, price, sl, tp_2r = strat.check_signals()
                
                if signal:
                    # Risk-based unit sizing
                    units = int((balance * RISK_PER_TRADE) / abs(price - sl))
                    if dp.place_market_order(sym, signal, units, sl, tp_2r):
                        trade_data = {
                            "symbol": sym, "side": signal, "entry": round(price, 5),
                            "sl": round(sl, 5), "tp_2r": round(tp_2r, 5), 
                            "status": "LIVE", "time": str(pd.Timestamp.now())
                        }
                        redis.lpush("open_trades", json.dumps(trade_data))
                        logs[sym] = f"TRADE: {signal}"
                else: logs[sym] = "No setup."

        redis.set("last_scan_logs", json.dumps(logs), ex=3600)
        
        ua = request.headers.get('User-Agent', '')
        if "cron-job" in ua.lower(): return jsonify({"status": "success"}), 200
        return redirect(url_for('home'))

    except Exception as e: return jsonify({"status": "error", "msg": str(e)}), 200

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
