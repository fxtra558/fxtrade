import os
import json
from flask import Flask, render_template, jsonify
from upstash_redis import Redis
import yfinance as yf
import pandas as pd
from strategy import StevenStrategy

# 1. Initialize Flask App
app = Flask(__name__)

# 2. Connect to Upstash Redis (Pulls from Render Environment Secrets)
REDIS_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")

if not REDIS_URL or not REDIS_TOKEN:
    print("CRITICAL ERROR: Upstash secrets missing in Render Environment Settings!")

redis = Redis(url=REDIS_URL, token=REDIS_TOKEN)

# 3. Configuration & Strategy Settings
SYMBOLS = ["EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X", "USDCAD=X"]
INITIAL_BALANCE = 10000.0

# Ensure our Virtual Bank Account exists
if not redis.exists("balance"):
    redis.set("balance", INITIAL_BALANCE)

# --- HELPER FUNCTIONS ---

def get_current_trades():
    """Fetches open trades from the database and converts them from JSON strings to Python dicts"""
    raw_list = redis.lrange("open_trades", 0, -1)
    trades = []
    for item in raw_list:
        try:
            # Handle decoding if necessary
            t_str = item.decode('utf-8') if isinstance(item, bytes) else item
            trades.append(json.loads(t_str))
        except Exception as e:
            print(f"Error parsing trade: {e}")
    return trades

# --- ROUTES ---

@app.route('/')
def home():
    """Renders the professional dark-mode dashboard"""
    try:
        balance = float(redis.get("balance"))
        trades = get_current_trades()
        return render_template('index.html', balance=balance, trades=trades)
    except Exception as e:
        return f"Dashboard Error: {str(e)}"

@app.route('/tick')
def tick():
    """
    The main bot loop. 
    Triggered every hour by Cron-job.org to scan the market.
    """
    actions_taken = []
    
    for sym in SYMBOLS:
        try:
            # A. Fetch Real-time Data (No KYC via Yahoo Finance)
            data = yf.download(tickers=sym, period="5d", interval="1h", progress=False)
            if data.empty:
                continue
            
            # B. Clean Data Columns
            df = data.copy()
            df.columns = [col[0].lower() if isinstance(col, tuple) else col.lower() for col in df.columns]
            
            # C. Check Strategy (Steven's rules from the video)
            strat = StevenStrategy(df)
            signal, price, atr = strat.check_signals()
            
            if signal:
                # D. Objective Risk Management
                # Stop Loss = 1.5x ATR, Take Profit = 3.0x ATR
                sl = price - (1.5 * atr) if signal == "BUY" else price + (1.5 * atr)
                tp = price + (3.0 * atr) if signal == "BUY" else price - (3.0 * atr)
                
                new_trade = {
                    "symbol": sym.replace("=X", ""),
                    "side": signal,
                    "entry": round(float(price), 5),
                    "sl": round(float(sl), 5),
                    "tp": round(float(tp), 5),
                    "time": pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')
                }
                
                # E. Save trade to database
                redis.lpush("open_trades", json.dumps(new_trade))
                actions_taken.append(f"Opened {signal} on {sym}")
                
        except Exception as e:
            print(f"Error scanning {sym}: {e}")

    return jsonify({
        "status": "Scan Complete", 
        "timestamp": pd.Timestamp.now().strftime('%Y-%m-%d %H:%M'),
        "actions": actions_taken,
        "new_balance": redis.get("balance")
    })

# Render uses Gunicorn, but this allows local testing
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
