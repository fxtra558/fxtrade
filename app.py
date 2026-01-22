import os
import json
from flask import Flask, render_template, jsonify, redirect, url_for
from upstash_redis import Redis
from data import DataProvider
import pandas as pd
from strategy import StevenStrategy

app = Flask(__name__)

# --- SECRETS (From Render Environment) ---
REDIS_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
OANDA_TOKEN = os.environ.get("OANDA_API_KEY") # Add this secret to Render!

redis = Redis(url=REDIS_URL, token=REDIS_TOKEN)
dp = DataProvider(OANDA_TOKEN)

# --- CONFIGURATION ---
# OANDA format is 'CURRENCY_CURRENCY'
SYMBOLS = ["EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD"]

if not redis.exists("balance"):
    redis.set("balance", 10000.0)

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
    try:
        # Diagnostic Check via OANDA
        test_df = dp.get_ohlc("EUR_USD", count=1)
        db_health = "Connected" if redis.ping() else "Disconnected"
        data_health = "Online (OANDA)" if test_df is not None else "Offline"

        balance = float(redis.get("balance"))
        trades = get_clean_trades()

        # Update Live Prices for Dashboard
        for trade in trades:
            live_data = dp.get_ohlc(trade['symbol'], granularity="M1", count=1)
            if live_data is not None:
                current_price = live_data['close'].iloc[-1]
                entry = float(trade['entry'])
                trade['current_price'] = round(current_price, 5)
                # Calculate % P/L
                p_l = ((current_price - entry) / entry) * 100 if trade['side'] == "BUY" else ((entry - current_price) / entry) * 100
                trade['pl_pct'] = round(p_l, 2)

        return render_template('index.html', balance=balance, trades=trades,
                               db_status=db_health, data_status=data_health, logic_status="Operational")
    except Exception as e:
        return f"OANDA Dashboard Error: {str(e)}"

@app.route('/tick')
def tick():
    """Bot Heartbeat - Using OANDA Data"""
    for sym in SYMBOLS:
        df = dp.get_ohlc(sym, granularity="H1") # Standard Hourly strategy
        if df is None: continue
        
        strat = StevenStrategy(df)
        signal, price, atr = strat.check_signals()
        
        if signal:
            trade_data = {
                "symbol": sym, # Keep OANDA format
                "side": signal,
                "entry": round(float(price.iloc[-1]), 5),
                "sl": round(float(price.iloc[-1] - (1.5 * atr) if signal == "BUY" else price.iloc[-1] + (1.5 * atr)), 5),
                "tp": round(float(price.iloc[-1] + (3.0 * atr) if signal == "BUY" else price.iloc[-1] - (3.0 * atr)), 5),
                "time": pd.Timestamp.now().strftime('%m-%d %H:%M')
            }
            redis.lpush("open_trades", json.dumps(trade_data))
            
    return redirect(url_for('home'))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
