import os
from flask import Flask, jsonify
from upstash_redis import Redis
import yfinance as yf
import pandas as pd
from strategy import StevenStrategy

# 1. Initialize Flask
app = Flask(__name__)

# 2. Connect to Database using Secrets
REDIS_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
redis = Redis(url=REDIS_URL, token=REDIS_TOKEN)

# Popular Pairs to Scan
SYMBOLS = ["EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X"]

# Ensure balance exists
if not redis.exists("balance"):
    redis.set("balance", 10000.0)

# --- ROUTES ---

@app.route('/')
def home():
    try:
        balance = redis.get("balance")
        return jsonify({
            "status": "Bot is alive",
            "message": "The Trading Channel Strategy Bot is scanning...",
            "current_paper_balance": balance
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/tick')
def tick():
    """Triggered by Cron-job.org every hour"""
    results = []
    for sym in SYMBOLS:
        try:
            # Get data
            data = yf.download(tickers=sym, period="5d", interval="1h", progress=False)
            if data.empty: continue
            
            df = data.copy()
            df.columns = [col[0].lower() if isinstance(col, tuple) else col.lower() for col in df.columns]
            
            # Check Strategy
            strat = StevenStrategy(df)
            signal, price, atr = strat.check_signals()
            
            if signal:
                new_trade = {"symbol": sym, "side": signal, "entry": price, "sl": price - (1.5*atr) if signal=="BUY" else price + (1.5*atr)}
                redis.lpush("open_trades", str(new_trade))
                results.append(f"Entered {signal} on {sym}")
        except Exception as e:
            results.append(f"Error on {sym}: {str(e)}")

    return jsonify({"status": "Scan Complete", "actions": results})

# This is for local testing only; Gunicorn ignores this.
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
