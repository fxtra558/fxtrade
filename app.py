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

if not redis.exists("balance"):
    redis.set("balance", INITIAL_BALANCE)

# --- NEW: TIME MANAGEMENT LOGIC ---

def get_market_status():
    """
    Checks if the Forex market is open.
    Forex closes Friday at 5 PM EST and opens Sunday at 5 PM EST.
    (9 PM UTC Friday to 9 PM UTC Sunday)
    """
    now_utc = datetime.utcnow()
    day = now_utc.weekday() # 0=Mon, 4=Fri, 5=Sat, 6=Sun
    hour = now_utc.hour

    # Friday after 9 PM UTC -> Market is closing
    if day == 4 and hour >= 21:
        return "CLOSING"
    # Saturday and Sunday before 9 PM UTC -> Market is closed
    if day == 5 or (day == 6 and hour < 21):
        return "CLOSED"
    
    return "OPEN"

# --- CORE LOGIC ---

def settle_and_manage_exits():
    try:
        status = get_market_status()
        broker_positions = dp.get_all_open_positions()
        
        # FRIDAY EMERGENCY: If market is closing, wipe the dashboard and broker
        if status == "CLOSING":
            dp.close_all_positions()
            redis.delete("open_trades")
            print("Weekend Protection: All positions closed.")
            return

        db_trades = redis.lrange("open_trades", 0, -1)
        balance = float(redis.get("balance") or INITIAL_BALANCE)

        for t_raw in db_trades:
            trade = json.loads(t_raw.decode('utf-8') if hasattr(t_raw, 'decode') else t_raw)
            if trade['symbol'] not in broker_positions:
                # Trade finished at broker
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
        status = get_market_status()
        balance = float(redis.get("balance") or INITIAL_BALANCE)
        
        # Process trades for UI
        raw_trades = redis.lrange("open_trades", 0, -1)
        trades = []
        for t in raw_trades:
            try:
                trade = json.loads(t.decode('utf-8') if hasattr(t, 'decode') else t)
                # Only fetch ticks if market is open
                if status == "OPEN":
                    curr = dp.get_live_tick(trade['symbol'])
                    if curr:
                        trade['current_price'] = round(curr, 5)
                        diff = (curr - trade['entry']) if trade['side'] == "BUY" else (trade['entry'] - curr)
                        trade['pl_pct'] = round((diff / trade['entry']) * 100, 4)
                else:
                    trade['current_price'] = "Market Closed"
                    trade['pl_pct'] = 0.0
                trades.append(trade)
            except: continue

        logs = json.loads(redis.get("last_scan_logs") or "{}")
        
        return render_template('index.html', balance=balance, trades=trades, 
                               db_status="Connected", data_status=status, 
                               logic_status="Active" if status == "OPEN" else "Sleeping",
                               last_logs=logs)
    except Exception as e:
        return f"Dashboard Error: {e}"

@app.route('/tick')
def tick():
    """V3.2 TICK: With Weekend Circuit Breaker"""
    try:
        status = get_market_status()
        
        # 1. EMERGENCY CLOSE ON FRIDAY
        if status == "CLOSING":
            dp.close_all_positions()
            redis.delete("open_trades")
            redis.set("last_scan_logs", json.dumps({"System": "Market Closing - All trades flattened."}))
            return redirect(url_for('home'))

        # 2. DO NOTHING ON WEEKENDS
        if status == "CLOSED":
            redis.set("last_scan_logs", json.dumps({"System": "Market Closed - AI Sleeping."}))
            return redirect(url_for('home'))

        # 3. NORMAL OPERATION
        settle_and_manage_exits()
        balance = float(redis.get("balance") or INITIAL_BALANCE)
        logs = {}

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
                # Unit Sizing
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

        # Response for Cron-job
        ua = request.headers.get('User-Agent', '')
        if "cron-job" in ua.lower(): return jsonify({"status": "success"}), 200
        
    except Exception as e: print(f"Tick Crash: {e}")
        
    return redirect(url_for('home'))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
