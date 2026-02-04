import os
import json
from flask import Flask, render_template, redirect, url_for, jsonify, request
from upstash_redis import Redis
from data import DataProvider
from strategy import StevenStrategy
import pandas as pd
from datetime import datetime

app = Flask(__name__)

# --- SECURE CONFIG & SECRETS ---
REDIS_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
OANDA_TOKEN = os.environ.get("OANDA_API_KEY")
OANDA_ACCT = os.environ.get("OANDA_ACCOUNT_ID")

# Connect to database and broker
redis = Redis(url=REDIS_URL, token=REDIS_TOKEN)
dp = DataProvider(OANDA_TOKEN, OANDA_ACCT)

# Global Settings
SYMBOLS = ["EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD"]
INITIAL_BALANCE = 10000.0
RISK_PER_TRADE = 0.005  # Institutional 0.5% risk

if not redis.exists("balance"):
    redis.set("balance", INITIAL_BALANCE)

# --- UTILITY & MARKET CLOCK ---

def get_market_status():
    """Checks if market is OPEN, CLOSED, or CLOSING (Friday Safety)"""
    now_utc = datetime.utcnow()
    day = now_utc.weekday() # 0=Mon, 4=Fri, 5=Sat, 6=Sun
    hour = now_utc.hour
    if day == 4 and hour >= 21: return "CLOSING"
    if day == 5 or (day == 6 and hour < 21): return "CLOSED"
    return "OPEN"

def calculate_units(price, sl, balance):
    """Calculates exact units for 0.5% risk"""
    try:
        risk_amount = balance * RISK_PER_TRADE
        stop_dist = abs(price - sl)
        if stop_dist == 0: return 1000
        return int(risk_amount / stop_dist)
    except: return 1000

# --- TRADE SETTLEMENT LOGIC ---

def sync_trades_and_balance():
    """Compares Broker to Dashboard. If OANDA closed a trade, we update balance."""
    try:
        broker_positions = dp.get_all_open_positions()
        db_trades = redis.lrange("open_trades", 0, -1)
        balance = float(redis.get("balance") or INITIAL_BALANCE)

        for t_raw in db_trades:
            t_str = t_raw.decode('utf-8') if hasattr(t_raw, 'decode') else t_raw
            trade = json.loads(t_str)
            
            if trade['symbol'] not in broker_positions:
                # Trade hit SL or TP at broker app
                curr = dp.get_live_tick(trade['symbol']) or trade['entry']
                win = (curr > trade['entry']) if trade['side']=="BUY" else (curr < trade['entry'])
                
                # Math: 2R payoff = 1% gain on account (since risk is 0.5%)
                change = (balance * 0.01) if win else -(balance * 0.005)
                redis.set("balance", balance + change)
                redis.lrem("open_trades", 1, t_raw)
                print(f"Settled {trade['symbol']}: {'WIN' if win else 'LOSS'}")
    except Exception as e:
        print(f"Sync Error: {e}")

# --- WEB ROUTES ---

@app.route('/')
def home():
    """The Professional UI Dashboard"""
    try:
        mkt_status = get_market_status()
        balance = float(redis.get("balance") or INITIAL_BALANCE)
        
        # Diagnostics
        db_health = "Connected" if redis.ping() else "Disconnected"
        
        # Process trades for display with Live Ticks
        raw_trades = redis.lrange("open_trades", 0, -1)
        trades_list = []
        for t in raw_trades:
            try:
                t_str = t.decode('utf-8') if hasattr(t, 'decode') else t
                trade = json.loads(t_str)
                if mkt_status == "OPEN":
                    curr = dp.get_live_tick(trade['symbol'])
                    if curr:
                        trade['current_price'] = round(curr, 5)
                        diff = (curr - trade['entry']) if trade['side']=="BUY" else (trade['entry'] - curr)
                        trade['pl_pct'] = round((diff / trade['entry']) * 100, 4)
                trades_list.append(trade)
            except: continue

        logs = json.loads(redis.get("last_scan_logs") or "{}")
        return render_template('index.html', balance=balance, trades=trades_list, 
                               db_status=db_health, data_status=mkt_status, 
                               logic_status="V3 Sniper", last_logs=logs)
    except Exception as e:
        return f"UI Logic Error: {str(e)}"

@app.route('/tick')
def tick():
    """The Core Execution Engine"""
    status = get_market_status()
    logs = {}
    actions = []
    
    try:
        # 1. Friday Settlement
        if status == "CLOSING":
            dp.close_all_positions()
            redis.delete("open_trades")
            logs["System"] = "Friday Close: All trades flattened."
        
        # 2. Weekend Pause
        elif status == "CLOSED":
            logs["System"] = "Market Closed. AI Sleeping."
        
        # 3. Normal Hunt
        else:
            sync_trades_and_balance()
            balance = float(redis.get("balance") or INITIAL_BALANCE)
            
            for sym in SYMBOLS:
                if dp.is_position_open(sym):
                    logs[sym] = "Position live."
                    continue

                # Fetch Multi-Timeframe Data
                df_d = dp.get_ohlc(sym, granularity="D", count=250)
                df_h1 = dp.get_ohlc(sym, granularity="H1", count=100)
                
                if df_d is None or df_h1 is None:
                    logs[sym] = "Feed offline."
                    continue
                
                # Analyze Strategy
                strat = StevenStrategy(df_h1, df_d)
                signal, price, sl, tp_2r = strat.check_signals()
                
                if signal:
                    units = calculate_units(price, sl, balance)
                    if dp.place_market_order(sym, signal, units, sl, tp_2r):
                        trade_data = {
                            "symbol": sym, "side": signal, "entry": round(price, 5),
                            "sl": round(sl, 5), "tp_2r": round(tp_2r, 5), 
                            "status": "LIVE", "time": str(pd.Timestamp.now())[:16]
                        }
                        redis.lpush("open_trades", json.dumps(trade_data))
                        actions.append(f"Opened {sym}")
                        logs[sym] = f"SUCCESS: {signal}"
                else:
                    logs[sym] = "No setup."

        redis.set("last_scan_logs", json.dumps(logs), ex=3600)
        
        # Response logic for Cron-job.org
        ua = request.headers.get('User-Agent', '')
        if "cron-job" in ua.lower():
            return jsonify({"status": "success", "market": status}), 200
        
    except Exception as e:
        print(f"Tick Logic Error: {e}")
        return jsonify({"status": "error", "msg": str(e)}), 200

    return redirect(url_for('home'))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
