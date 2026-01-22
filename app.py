import os
import json
from flask import Flask, render_template, redirect, url_for, jsonify
from upstash_redis import Redis
from data import DataProvider
from strategy import StevenStrategy
import pandas as pd

app = Flask(__name__)

# --- CONFIG ---
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
        
        # 1. Fetch current trades from Database
        raw_trades = redis.lrange("open_trades", 0, -1)
        trades = []
        for t in raw_trades:
            trade = json.loads(t) if isinstance(t, str) else json.loads(t.decode('utf-8'))
            
            # 2. FETCH REAL-TIME PRICE FOR EACH TRADE
            live_df = dp.get_ohlc(trade['symbol'], granularity="M1", count=1)
            if live_df is not None and not live_df.empty:
                current_price = float(live_df['close'].iloc[-1])
                entry = float(trade['entry'])
                
                # 3. CALCULATE LIVE P/L %
                if trade['side'] == "BUY":
                    p_l = ((current_price - entry) / entry) * 100
                else:
                    p_l = ((entry - current_price) / entry) * 100
                
                trade['current_price'] = round(current_price, 5)
                trade['pl_pct'] = round(p_l, 3) # 3 decimals for precision
            else:
                trade['current_price'] = "Syncing..."
                trade['pl_pct'] = 0.0
                
            trades.append(trade)

        balance = float(redis.get("balance"))
        return render_template('index.html', balance=balance, trades=trades, 
                               db_status=db_health, data_status="Online (OANDA)", logic_status="Operational")
    except Exception as e:
        return f"Dashboard Error: {str(e)}"

@app.route('/tick')
def tick():
    """Scans and prevents duplicate trades"""
    for sym in SYMBOLS:
        # STEP 1: CHECK IF POSITION ALREADY EXISTS AT BROKER
        if dp.is_position_open(sym):
            print(f"Skipping {sym}: Position already open.")
            continue

        df = dp.get_ohlc(sym, granularity="H1")
        if df is None: continue
        
        strat = StevenStrategy(df)
        signal, price_series, atr = strat.check_signals()
        
        if signal:
            price = float(price_series.iloc[-1])
            sl = price - (1.5 * atr) if signal == "BUY" else price + (1.5 * atr)
            tp = price + (3.0 * atr) if signal == "BUY" else price - (3.0 * atr)
            
            # PLACE ORDER
            response = dp.place_market_order(sym, signal, 1000, sl, tp)
            
            if response:
                trade_data = {
                    "symbol": sym, "side": signal, "entry": round(price, 5),
                    "sl": round(sl, 5), "tp": round(tp, 5), "pl_pct": 0.0
                }
                redis.lpush("open_trades", json.dumps(trade_data))
                
    return redirect(url_for('home'))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
