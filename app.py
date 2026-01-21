import os
import json
from flask import Flask, render_template, jsonify
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
    """Retrieves open trades and fixes formatting for the UI"""
    raw_trades = redis.lrange("open_trades", 0, -1)
    clean_trades = []
    for t in raw_trades:
        try:
            # Convert string from database back to dictionary
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
        
        test_data = yf.download(tickers="EURUSD=X", period="1d", interval="1h", progress=False)
        data_health = "Online" if not test_data.empty else "Offline"
        
        logic_health = "Operational" if data_health == "Online" else "Waiting"

        # 2. Financial Data
        balance = float(redis.get("balance"))
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
    """The AI Bot Heartbeat (Triggered by Cron-job.org)"""
    actions = []
    
    for sym in SYMBOLS:
        try:
            # A. Fetch Market Data
            df = yf.download(tickers=sym, period="5d", interval="1h", progress=False)
            if df.empty: continue
            
            # B. Standardize Columns
            df.columns = [col[0].lower() if isinstance(col, tuple) else col.lower() for col in df.columns]
            
            # C. Run Steven's Strategy Logic
            strat = StevenStrategy(df)
            signal, price, atr = strat.check_signals()
            
            if signal:
                # D. Objective Risk Mgmt (1.5x ATR SL / 3x ATR TP)
                sl = price - (1.5 * atr) if signal == "BUY" else price + (1.5 * atr)
                tp = price + (3.0 * atr) if signal == "BUY" else price - (3.0 * atr)
                
                trade_data = {
                    "symbol": sym.replace("=X", ""),
                    "side": signal,
                    "entry": round(float(price), 5),
                    "sl": round(float(sl), 5),
                    "tp": round(float(tp), 5),
                    "time": pd.Timestamp.now().strftime('%H:%M')
                }
                
                # E. Save to Upstash
                redis.lpush("open_trades", json.dumps(trade_data))
                actions.append(f"Trade Opened: {signal} {sym}")

        except Exception as e:
            actions.append(f"Error on {sym}: {str(e)}")

    return jsonify({"status": "Finished", "actions": actions})

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
