import os
import json
from flask import Flask, render_template, redirect, url_for, jsonify
from upstash_redis import Redis
from data import DataProvider
from strategy import StevenStrategy
import pandas as pd

app = Flask(__name__)

# --- SECURE CONFIG ---
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
        db_health = "Connected" if redis.ping() else "Disconnected"
        balance = float(redis.get("balance") or 10000.0)
        
        raw_trades = redis.lrange("open_trades", 0, -1)
        trades = []
        
        for t in raw_trades:
            try:
                trade = json.loads(t.decode('utf-8') if hasattr(t, 'decode') else t)
                # Fetch Current Price with a 5-candle buffer for safety
                live_df = dp.get_ohlc(trade['symbol'], granularity="M5", count=5)
                
                if live_df is not None and not live_df.empty:
                    curr = float(live_df['close'].iloc[-1])
                    entry = float(trade['entry'])
                    trade['current_price'] = curr
                    # P/L Math
                    diff = (curr - entry) if trade['side'] == "BUY" else (entry - curr)
                    trade['pl_pct'] = round((diff / entry) * 100, 3)
                else:
                    trade['current_price'] = trade['entry']
                    trade['pl_pct'] = 0.0
                
                trades.append(trade)
            except: continue

        return render_template('index.html', balance=balance, trades=trades, 
                               db_status=db_health, data_status="Online (OANDA)", logic_status="Operational")
    except Exception as e:
        return f"Critical UI Error: {str(e)}"

@app.route('/tick')
def tick():
    """Safety-focused loop that redirects home no matter what"""
    try:
        for sym in SYMBOLS:
            # 1. Prevent crashes by checking open status safely
            if dp.is_position_open(sym): continue

            df = dp.get_ohlc(sym, granularity="H1", count=100)
            if df is None or df.empty: continue
            
            strat = StevenStrategy(df)
            signal, price_data, atr = strat.check_signals()
            
            if signal:
                # Handle price whether it's a Series or a Float
                price = float(price_data.iloc[-1]) if hasattr(price_data, 'iloc') else float(price_data)
                
                sl = price - (1.5 * atr) if signal == "BUY" else price + (1.5 * atr)
                tp = price + (3.0 * atr) if signal == "BUY" else price - (3.0 * atr)
                
                if dp.place_market_order(sym, signal, 1000, sl, tp):
                    trade_data = {"symbol": sym, "side": signal, "entry": round(price, 5),
                                  "sl": round(sl, 5), "tp": round(tp, 5), "time": str(pd.Timestamp.now())}
                    redis.lpush("open_trades", json.dumps(trade_data))
    except Exception as e:
        print(f"BOT ERROR: {e}")
        
    return redirect(url_for('home'))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
