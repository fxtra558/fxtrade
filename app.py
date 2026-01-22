import os
import json
from flask import Flask, render_template, redirect, url_for, jsonify
from upstash_redis import Redis
from data import DataProvider
from strategy import StevenStrategy
import pandas as pd

app = Flask(__name__)

# --- CONFIG & SECRETS ---
REDIS_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
OANDA_TOKEN = os.environ.get("OANDA_API_KEY")
OANDA_ACCT = os.environ.get("OANDA_ACCOUNT_ID")

redis = Redis(url=REDIS_URL, token=REDIS_TOKEN)
dp = DataProvider(OANDA_TOKEN, OANDA_ACCT)

SYMBOLS = ["EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD"]

@app.route('/')
def home():
    try:
        # Check Database
        db_health = "Connected" if redis.ping() else "Disconnected"
        
        # Financial Data
        raw_bal = redis.get("balance")
        balance = float(raw_bal) if raw_bal else 10000.0
        
        raw_trades = redis.lrange("open_trades", 0, -1)
        trades = []
        for t in raw_trades:
            try:
                # Ensure we handle bytes vs strings correctly
                t_str = t.decode('utf-8') if hasattr(t, 'decode') else t
                trades.append(json.loads(t_str))
            except: continue

        return render_template('index.html', balance=balance, trades=trades, 
                               db_status=db_health, data_status="Online (OANDA)", logic_status="Operational")
    except Exception as e:
        return f"Dashboard Error: {str(e)}"

@app.route('/tick')
def tick():
    """Safety-First scanning loop"""
    try:
        for sym in SYMBOLS:
            df = dp.get_ohlc(sym, granularity="H1")
            if df is None or df.empty: continue
            
            strat = StevenStrategy(df)
            # Strategy returns (signal, price_series, atr)
            signal, price_series, atr = strat.check_signals()
            
            if signal:
                # Force price to be a single float number
                raw_price = price_series.iloc[-1] if hasattr(price_series, 'iloc') else price_series
                price = float(raw_price)
                
                # Calculation of SL/TP
                sl = price - (1.5 * atr) if signal == "BUY" else price + (1.5 * atr)
                tp = price + (3.0 * atr) if signal == "BUY" else price - (3.0 * atr)
                
                # 1. ATTEMPT REAL ORDER
                response = dp.place_market_order(sym, signal, 1000, sl, tp)
                
                # 2. ONLY RECORD IF BROKER SUCCESSFUL
                if response:
                    trade_data = {
                        "symbol": sym, "side": signal, "entry": round(price, 5),
                        "sl": round(sl, 5), "tp": round(tp, 5), "pl_pct": 0.0
                    }
                    redis.lpush("open_trades", json.dumps(trade_data))
                    
        return redirect(url_for('home'))
    
    except Exception as e:
        # This prevents the 500 Internal Server Error
        print(f"CRITICAL TICK ERROR: {e}")
        return redirect(url_for('home'))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
