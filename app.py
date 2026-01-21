import os
import json
from flask import Flask, render_template, jsonify, redirect, url_for
from upstash_redis import Redis
import yfinance as yf
import pandas as pd
from strategy import StevenStrategy

app = Flask(__name__)

REDIS_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
redis = Redis(url=REDIS_URL, token=REDIS_TOKEN)

SYMBOLS = ["EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X", "USDCAD=X"]
INITIAL_BALANCE = 10000.0

if not redis.exists("balance"):
    redis.set("balance", INITIAL_BALANCE)

def fetch_data(symbol, period="5d", interval="1h"):
    try:
        df = yf.download(tickers=symbol, period=period, interval=interval, progress=False)
        if df.empty: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df.columns = [str(col).lower() for col in df.columns]
        return df
    except: return None

@app.route('/')
def home():
    try:
        # 1. Diagnostics
        db_health = "Connected" if redis.ping() else "Disconnected"
        test_df = fetch_data("EURUSD=X", period="1d")
        data_health = "Online" if test_df is not None else "Offline"
        
        # 2. Get Trades and Calculate LIVE P/L
        raw_trades = redis.lrange("open_trades", 0, -1)
        trades_with_live_data = []
        
        for t in raw_trades:
            trade = json.loads(t) if isinstance(t, str) else json.loads(t.decode('utf-8'))
            sym = trade['symbol'] + "=X"
            
            # Fetch current price for this specific trade
            live_data = yf.download(tickers=sym, period="1d", interval="1m", progress=False)
            if not live_data.empty:
                current_price = float(live_data['Close'].iloc[-1])
                entry = float(trade['entry'])
                
                # Calculate % Profit/Loss
                if trade['side'] == "BUY":
                    p_l_pct = ((current_price - entry) / entry) * 100
                else:
                    p_l_pct = ((entry - current_price) / entry) * 100
                
                trade['current_price'] = round(current_price, 5)
                trade['pl_pct'] = round(p_l_pct, 2)
            else:
                trade['current_price'] = "Wait..."
                trade['pl_pct'] = 0.0
                
            trades_with_live_data.append(trade)

        balance = float(redis.get("balance"))
        return render_template('index.html', balance=balance, trades=trades_with_live_data, 
                               db_status=db_health, data_status=data_health, logic_status="Operational")
    except Exception as e:
        return f"Dashboard Error: {str(e)}"

@app.route('/tick')
def tick():
    for sym in SYMBOLS:
        df = fetch_data(sym)
        if df is None: continue
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
    return redirect(url_for('home'))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
