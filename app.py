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
            # Fix common Redis decoding issues
            t_str = t.decode('utf-8') if isinstance(t, bytes) else t
            clean_trades.append(json.loads(t_str))
        except: continue
    return clean_trades

def fetch_data(symbol, period="5d", interval="1h"):
    """Fetches and cleans data to prevent 'Offline' errors"""
    try:
        df = yf.download(tickers=symbol, period=period, interval=interval, progress=False)
        if df.empty:
            return None
        
        # FIX: Flatten Multi-Index columns (This is the 'Offline' fix)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        df.columns = [str(col).lower() for col in df.columns]
        return df
    except:
        return None

# --- ROUTES ---

@app.route('/')
def home():
    """The Main Dashboard with Improved Diagnostics"""
    try:
        # 1. Database Diagnostic
        db_health = "Connected" if redis.ping() else "Disconnected"
        
        # 2. Market Feed Diagnostic (Checking a wider range for stability)
        test_df = fetch_data("EURUSD=X")
        data_health = "Online" if test_df is not None else "Offline"
        
        # 3. Logic Engine Diagnostic
        logic_health = "Operational" if (test_df is not None and 'close' in test_df.columns) else "Waiting"

        # 4. Financial Stats
        bal_raw = redis.get("balance")
        balance = float(bal_raw) if bal_raw else INITIAL_BALANCE
        trades = get_clean_trades()

        return render_template('index.html', 
                               balance=balance, 
                               trades=trades,
                               db_status=db_health,
                               data_status=data_health,
                               logic_status=logic_health)
    except Exception as e:
        return f"Diagnostic Failure: {str(e)}"

@app.route('/tick')
def tick():
    """The AI Bot Heartbeat"""
    for sym in SYMBOLS:
        df = fetch_data(sym)
        if df is None: continue
        
        try:
            strat = StevenStrategy(df)
            signal, price, atr = strat.check_signals()
            
            if signal:
                trade_data = {
                    "symbol": sym.replace("=X", ""),
                    "side": signal,
                    "entry": round(float(price), 5),
                    "sl": round(float(price - (1.5 * atr) if signal == "BUY" else price + (1.5 * atr)), 5),
                    "tp": round(float(price + (3.0 * atr) if signal == "BUY" else price - (3.0 * atr)), 5),
                    "time": pd.Timestamp.now().strftime('%m-%d %H:%M')
                }
                redis.lpush("open_trades", json.dumps(trade_data))
        except Exception as e:
            print(f"Strategy Error on {sym}: {e}")

    return redirect(url_for('home'))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
