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
        # Check Feed via a simple call
        test_df = dp.get_ohlc("EUR_USD", count=5)
        data_health = "Online (OANDA)" if test_df is not None else "Offline"
        db_health = "Connected" if redis.ping() else "Disconnected"
        
        balance = float(redis.get("balance"))
        # Get trades from our DB for the UI
        raw_trades = redis.lrange("open_trades", 0, -1)
        trades = [json.loads(t) for t in raw_trades]

        # Calculate live P/L for the UI
        for trade in trades:
            live = dp.get_ohlc(trade['symbol'], granularity="M1", count=1)
            if live is not None:
                curr = float(live['close'].iloc[-1])
                entry = float(trade['entry'])
                trade['current_price'] = curr
                trade['pl_pct'] = round(((curr - entry)/entry)*100 if trade['side'] == "BUY" else ((entry - curr)/entry)*100, 2)

        return render_template('index.html', balance=balance, trades=trades, 
                               db_status=db_health, data_status=data_health, logic_status="Operational")
    except Exception as e:
        return f"System Error: {str(e)}"

@app.route('/tick')
def tick():
    """Triggered by Cron-job: Scans and executes on OANDA account"""
    for sym in SYMBOLS:
        df = dp.get_ohlc(sym, granularity="H1")
        if df is None: continue
        
        strat = StevenStrategy(df)
        signal, price_series, atr = strat.check_signals()
        
        if signal:
            price = float(price_series.iloc[-1])
            sl = price - (1.5 * atr) if signal == "BUY" else price + (1.5 * atr)
            tp = price + (3.0 * atr) if signal == "BUY" else price - (3.0 * atr)
            
            # 1. PLACE REAL ORDER IN OANDA
            # 1000 units is roughly 0.01 lot
            response = dp.place_market_order(sym, signal, 1000, sl, tp)
            
            if response:
                # 2. IF BROKER ACCEPTS, RECORD IN DASHBOARD
                trade_data = {
                    "symbol": sym, "side": signal, "entry": round(price, 5),
                    "sl": round(sl, 5), "tp": round(tp, 5), "pl_pct": 0.0
                }
                redis.lpush("open_trades", json.dumps(trade_data))
                
    return redirect(url_for('home'))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
