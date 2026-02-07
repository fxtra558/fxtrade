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

# EXPANDED SYMBOL LIST (Higher Frequency)
SYMBOLS = ["EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD", "NZD_USD", "EUR_JPY", "GBP_JPY"]
INITIAL_BALANCE = 10000.0
RISK_PER_TRADE = 0.005 # 0.5% risk rule

if not redis.exists("balance"):
    redis.set("balance", INITIAL_BALANCE)

# --- UTILITY ---

def get_market_status():
    """UTC: Fri 9 PM to Sun 9 PM is closed/closing"""
    now_utc = datetime.utcnow()
    day = now_utc.weekday()
    hour = now_utc.hour
    if day == 4 and hour >= 21: return "CLOSING"
    if day == 5 or (day == 6 and hour < 21): return "CLOSED"
    return "OPEN"

def calculate_units(price, sl, balance):
    try:
        risk_amount = balance * RISK_PER_TRADE
        stop_dist = abs(price - sl)
        return int(risk_amount / stop_dist) if stop_dist > 0 else 1000
    except: return 1000

# --- TRADE MANAGEMENT ---

def settle_and_sync():
    """Auto-detects closed trades at OANDA and settles paper balance"""
    try:
        broker_positions = dp.get_all_open_positions()
        db_trades = redis.lrange("open_trades", 0, -1)
        balance = float(redis.get("balance") or INITIAL_BALANCE)

        for t_raw in db_trades:
            t_str = t_raw.decode('utf-8') if hasattr(t_raw, 'decode') else t_raw
            trade = json.loads(t_str)
            
            if trade['symbol'] not in broker_positions:
                curr = dp.get_live_tick(trade['symbol']) or trade['entry']
                win = (curr > trade['entry']) if trade['side']=="BUY" else (curr < trade['entry'])
                # Profit calculation: 2R reward = 1% gain (since 0.5% risk)
                change = (balance * 0.01) if win else -(balance * 0.005)
                redis.set("balance", balance + change)
                redis.lrem("open_trades", 1, t_raw)
    except Exception as e:
        print(f"Settle Error: {e}")

# --- ROUTES ---

@app.route('/')
def home():
    try:
        status = get_market_status()
        balance = float(redis.get("balance") or INITIAL_BALANCE)
        db_health = "Connected" if redis.ping() else "Disconnected"
        
        raw_trades = redis.lrange("open_trades", 0, -1)
        processed_trades = []
        for t in raw_trades:
            try:
                t_str = t.decode('utf-8') if hasattr(t, 'decode') else t
                trade = json.loads(t_str)
                if status == "OPEN":
                    curr = dp.get_live_tick(trade['symbol'])
                    if curr:
                        trade['current_price'] = round(curr, 5)
                        diff = (curr - trade['entry']) if trade['side'] == "BUY" else (trade['entry'] - curr)
                        trade['pl_pct'] = round((diff / trade['entry']) * 100, 4)
                processed_trades.append(trade)
            except: continue

        logs = json.loads(redis.get("last_scan_logs") or "{}")
        return render_template('index.html', balance=balance, trades=processed_trades, 
                               db_status=db_health, data_status=status, 
                               logic_status="High Frequency", last_logs=logs)
    except Exception as e: return f"Dashboard Error: {e}"

@app.route('/tick')
def tick():
    """THE SNIPER HEARTBEAT"""
    status = get_market_status()
    logs = {}
    actions = []
    
    try:
        if status == "CLOSING":
            dp.close_all_positions()
            redis.delete("open_trades")
            logs["System"] = "Friday Settlement: All positions flattened."
        elif status == "CLOSED":
            logs["System"] = "Weekend: Markets closed."
        else:
            settle_and_sync()
            balance = float(redis.get("balance") or INITIAL_BALANCE)
            
            for sym in SYMBOLS:
                if dp.is_position_open(sym):
                    logs[sym] = "Position live."
                    continue

                # Fetch 2 timeframes for bias and momentum
                df_d = dp.get_ohlc(sym, granularity="D", count=250)
                df_h1 = dp.get_ohlc(sym, granularity="H1", count=100)
                
                if df_d is None or df_h1 is None:
                    logs[sym] = "Feed Offline."
                    continue
                
                strat = StevenStrategy(df_h1, df_d)
                signal, price, sl, tp = strat.check_signals()
                
                if signal:
                    units = calculate_units(price, sl, balance)
                    if dp.place_market_order(sym, signal, units, sl, tp):
                        trade_data = {
                            "symbol": sym, "side": signal, "entry": round(price, 5),
                            "sl": round(sl, 5), "tp_2r": round(tp, 5), 
                            "status": "LIVE", "time": str(pd.Timestamp.now())[:16]
                        }
                        redis.lpush("open_trades", json.dumps(trade_data))
                        actions.append(f"ENTERED {sym}")
                        logs[sym] = f"SUCCESS: {signal}"
                else:
                    logs[sym] = "Searching..."

        redis.set("last_scan_logs", json.dumps(logs), ex=3600)
        
        # Robot Success Response
        ua = request.headers.get('User-Agent', '')
        if "cron-job" in ua.lower(): return jsonify({"status": "success"}), 200
        
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 200

    return redirect(url_for('home'))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
