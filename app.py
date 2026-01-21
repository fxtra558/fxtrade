import os
import json
from flask import Flask, render_template, jsonify, redirect, url_for
from upstash_redis import Redis
import yfinance as yf
import pandas as pd
from strategy import StevenStrategy

app = Flask(__name__)

# --- DATABASE CONNECTION ---
REDIS_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
redis = Redis(url=REDIS_URL, token=REDIS_TOKEN)

SYMBOLS = ["EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X", "USDCAD=X"]
INITIAL_BALANCE = 10000.0

if not redis.exists("balance"):
    redis.set("balance", INITIAL_BALANCE)

def fetch_data(symbol, period="5d", interval="1h"):
    """Fetches and cleans data to prevent 'Series' and 'Offline' errors"""
    try:
        df = yf.download(tickers=symbol, period=period, interval=interval, progress=False)
        if df.empty: return None
        
        # Flatten MultiIndex columns if they exist
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        df.columns = [str(col).lower() for col in df.columns]
        return df
    except:
        return None

def get_clean_trades():
    raw_trades = redis.lrange("open_trades", 0, -1)
    clean_trades = []
    for t in raw_trades:
        try:
            t_str = t.decode('utf-8') if isinstance(t, bytes) else t
            clean_trades.append(json.loads(t_str))
        except: continue
    return clean_trades

# --- ROUTES ---

@app.route('/')
def home():
    """Renders dashboard with Live Profit/Loss tracking"""
    try:
        # 1. Diagnostics
        db_health = "Connected" if redis.ping() else "Disconnected"
        test_df = fetch_data("EURUSD=X", period="1d")
        data_health = "Online" if test_df is not None else "Offline"
        
        # 2. Process Trades with Live P/L
        trades = get_clean_trades()
        processed_trades = []
        
        for trade in trades:
            sym = trade['symbol'] + "=X"
            # Use 1m interval for most accurate live price
            live_df = fetch_data(sym, period="1d", interval="1m")
            
            if live_df is not None and not live_df.empty:
                # FIX: Force scalar conversion to avoid "Series" error
                current_price = float(live_df['close'].iloc[-1])
                entry = float(trade['entry'])
                
                # Calculate % P/L
                if trade['side'] == "BUY":
                    p_l = ((current_price - entry) / entry) * 100
                else:
                    p_l = ((entry - current_price) / entry) * 100
                
                trade['current_price'] = round(current_price, 5)
                trade['pl_pct'] = round(p_l, 2)
            else:
                trade['current_price'] = trade['entry']
                trade['pl_pct'] = 0.0
                
            processed_trades.append(trade)

        bal_raw = redis.get("balance")
        balance = float(bal_raw) if bal_raw else INITIAL_BALANCE

        return render_template('index.html', 
                               balance=balance, 
                               trades=processed_trades,
                               db_status=db_health,
                               data_status=data_health,
                               logic_status="Operational")
    except Exception as e:
        # This will show you exactly what went wrong if it fails again
        return f"Dashboard Logic Error: {str(e)}"

@app.route('/tick')
def tick():
    """Bot Heartbeat - Scans and Redirects"""
    for sym in SYMBOLS:
        df = fetch_data(sym)
        if df is None: continue
        
        try:
            strat = StevenStrategy(df)
            signal, price, atr = strat.check_signals()
            
            if signal:
                # Ensure price is a float
                entry_price = float(price.iloc[-1]) if hasattr(price, 'iloc') else float(price)
                
                trade_data = {
                    "symbol": sym.replace("=X", ""),
                    "side": signal,
                    "entry": round(entry_price, 5),
                    "sl": round(entry_price - (1.5 * atr) if signal == "BUY" else entry_price + (1.5 * atr), 5),
                    "tp": round(entry_price + (3.0 * atr) if signal == "BUY" else entry_price - (3.0 * atr), 5),
                    "time": pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')
                }
                redis.lpush("open_trades", json.dumps(trade_data))
        except Exception as e:
            print(f"Error on {sym}: {e}")

    return redirect(url_for('home'))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
