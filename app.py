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

redis = Redis(url=REDIS_URL, token=REDIS_TOKEN)
dp = DataProvider(OANDA_TOKEN, OANDA_ACCT)

# Global Trading Settings
SYMBOLS = ["EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD"]
INITIAL_BALANCE = 10000.0
RISK_PER_TRADE = 0.005  # 0.5% risk rule

if not redis.exists("balance"):
    redis.set("balance", INITIAL_BALANCE)

# --- MARKET CLOCK LOGIC ---

def get_market_status():
    """
    Forex closes Friday 5 PM EST, opens Sunday 5 PM EST.
    UTC: Friday 10 PM to Sunday 10 PM.
    """
    now_utc = datetime.utcnow()
    day = now_utc.weekday() # 0=Mon, 4=Fri, 5=Sat, 6=Sun
    hour = now_utc.hour

    if day == 4 and hour >= 21: return "CLOSING"
    if day == 5 or (day == 6 and hour < 21): return "CLOSED"
    return "OPEN"

# --- TRADE SETTLEMENT LOGIC ---

def sync_with_broker():
    """Checks if OANDA hit SL/TP and updates our dashboard balance"""
    try:
        broker_positions = dp.get_all_open_positions()
        db_trades = redis.lrange("open_trades", 0, -1)
        balance = float(redis.get("balance") or INITIAL_BALANCE)

        for t_raw in db_trades:
            # Handle potential bytes from Redis
            t_str = t_raw.decode('utf-8') if hasattr(t_raw, 'decode') else t_raw
            trade = json.loads(t_str)
            
            if trade['symbol'] not in broker_positions:
                # Trade hit SL or TP at broker. Determine outcome.
                curr = dp.get_live_tick(trade['symbol']) or trade['entry']
                win = (curr > trade['entry']) if trade['side']=="BUY" else (curr < trade['entry'])
                
                # Update balance (assuming 1% gain on 0.5% risk for 2R TP)
                change = (balance * 0.01) if win else -(balance * 0.005)
                redis.set("balance", balance + change)
                redis.lrem("open_trades", 1, t_raw)
                print(f"Sync: {trade['symbol']} settled as {'WIN' if win else 'LOSS'}")
    except Exception as e:
        print(f"Sync Error: {e}")

# --- WEB ROUTES ---

@app.route('/')
def home():
    """Dashboard UI"""
    try:
        mkt_status = get_market_status()
        balance = float(redis.get("balance") or INITIAL_BALANCE)
        
        # Diagnostics
        db_health = "Connected" if redis.ping() else "Disconnected"
        
        # Load Trades and Fetch Live Prices for UI
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
                               logic_status="Active" if mkt_status == "OPEN" else "Sleeping",
                               last_logs=logs)
    except Exception as e:
        return f"Dashboard Display Error: {str(e)}"

@app.route('/tick')
def tick():
    """Robot-Friendly Scan Route"""
    status = get_market_status()
    logs = {}
    
    try:
        # 1. Friday Safety Rule: Flatten all positions
        if status == "CLOSING":
            dp.close_all_positions()
            redis.delete("open_trades")
            logs["System"] = "Friday Close: All trades flattened."
        
        # 2. Weekend: Do nothing
        elif status == "CLOSED":
            logs["System"] = "Weekend: Markets closed."
        
        # 3. Normal Market Hours
        else:
            sync_with_broker()
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
                    # Calculate Lot Size
                    units = int((balance * RISK_PER_TRADE) / abs(price - sl))
                    if dp.place_market_order(sym, signal, units, sl, tp_2r):
                        trade_data = {
                            "symbol": sym, "side": signal, "entry": round(price, 5),
                            "sl": round(sl, 5), "tp_2r": round(tp_2r, 5), 
                            "status": "LIVE", "time": str(pd.Timestamp.now())
                        }
                        redis.lpush("open_trades", json.dumps(trade_data))
                        logs[sym] = f"TRADE: {signal}"
                else:
                    logs[sym] = "Searching..."

        redis.set("last_scan_logs", json.dumps(logs), ex=3600)

        # Handle Cron-job.org or Human Browser
        ua = request.headers.get('User-Agent', '')
        if "cron-job" in ua.lower():
            return jsonify({"status": "success", "market": status}), 200
        return redirect(url_for('home'))

    except Exception as e:
        print(f"Critical Bot Error: {e}")
        return jsonify({"status": "error", "msg": str(e)}), 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
