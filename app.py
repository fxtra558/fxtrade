import os
import json
from flask import Flask, render_template, jsonify, redirect, url_for
from upstash_redis import Redis
import yfinance as yf
import pandas as pd
from strategy import StevenStrategy

app = Flask(__name__)

# --- SECURE DATABASE CONNECTION ---
REDIS_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
redis = Redis(url=REDIS_URL, token=REDIS_TOKEN)

# --- CONFIGURATION ---
SYMBOLS = ["EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X", "USDCAD=X"]
INITIAL_BALANCE = 10000.0

if not redis.exists("balance"):
    redis.set("balance", INITIAL_BALANCE)

def get_clean_trades():
    raw_trades = redis.lrange("open_trades", 0, -1)
    clean_trades = []
    for t in raw_trades:
        try:
            item = json.loads(t) if isinstance(t, str) else json.loads(t.decode('utf-8'))
            clean_trades.append(item)
        except: continue
    return clean_trades

# --- ROUTES ---

@app.route('/')
def home():
    """The Main Dashboard with System Diagnostics"""
    try:
        # 1. System Health Checks
        db_health = "Connected" if redis.ping() else "Disconnected"
        
        # Enhanced Health Check for Yahoo Finance (Checking 2 days to avoid weekend gaps)
        test_data = yf.download(tickers="EURUSD=X", period="2d", interval="1h", progress=False)
        data_health = "Online" if not test_data.empty else "Offline"
        
        logic_health = "Operational" if data_health == "Online" else "Waiting"

        # 2. Financial Data
        balance_val = redis.get("balance")
        balance = float(balance_val) if balance_val else INITIAL_BALANCE
        trades = get_clean_trades()

        return render_template('index.html', 
                               balance=balance, 
                               trades=trades,
                               db_status=db_health,
                               data_status=data_health,
                               logic_status=logic_health)
    except Exception as e:
        return f"System Dashboard Error: {str(e)}"

@app.route('/tick')
def tick():
    """The AI Bot Heartbeat - Scans and Redirects back to Home"""
    for sym in SYMBOLS:
        try:
            # Fetch Market Data
            df = yf.download(tickers=sym, period="5d", interval="1h", progress=False)
            if df.empty: continue
            
            # Standardize Columns
            df.columns = [col[0].lower() if isinstance(col, tuple) else col.lower() for col in df.columns]
            
            # Run Steven's Strategy Logic
            strat = StevenStrategy(df)
            signal, price, atr = strat.check_signals()
            
            if signal:
                trade_data = {
                    "symbol": sym.replace("=X", ""),
                    "side": signal,
                    "entry": round(float(price), 5),
                    "sl": round(float(price - (1.5 * atr) if signal == "BUY" else price + (1.5 * atr)), 5),
                    "tp": round(float(price + (3.0 * atr) if signal == "BUY" else price - (3.0 * atr)), 5),
                    "time": pd.Timestamp.now().strftime('%H:%M')
                }
                redis.lpush("open_trades", json.dumps(trade_data))

        except Exception as e:
            print(f"Error on {sym}: {e}")

    # THIS IS THE FIX: Instead of showing JSON, go back to the dashboard
    return redirect(url_for('home'))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
