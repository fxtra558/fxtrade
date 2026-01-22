import os
import json
from flask import Flask, render_template, jsonify, redirect, url_for
from upstash_redis import Redis
from data import DataProvider
import pandas as pd
from strategy import StevenStrategy

app = Flask(__name__)

# --- SECURE DATABASE CONNECTION ---
REDIS_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
OANDA_TOKEN = os.environ.get("OANDA_API_KEY")

redis = Redis(url=REDIS_URL, token=REDIS_TOKEN)
dp = DataProvider(OANDA_TOKEN)

# Popular OANDA Symbols
SYMBOLS = ["EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD"]
INITIAL_BALANCE = 10000.0

if not redis.exists("balance"):
    redis.set("balance", INITIAL_BALANCE)

def format_symbol_for_oanda(symbol):
    """Ensures symbol has an underscore (e.g., EURUSD -> EUR_USD)"""
    symbol = str(symbol).replace("=X", "").replace("/", "").upper()
    if "_" not in symbol and len(symbol) == 6:
        return f"{symbol[:3]}_{symbol[3:]}"
    return symbol

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
    """Main Dashboard with FIX for Symbol Formatting and Live P/L"""
    try:
        # 1. System Checks
        test_df = dp.get_ohlc("EUR_USD", count=1)
        db_health = "Connected" if redis.ping() else "Disconnected"
        data_health = "Online (OANDA)" if test_df is not None else "Offline"

        # 2. Financial Stats
        balance = float(redis.get("balance"))
        trades = get_clean_trades()
        processed_trades = []

        # 3. Calculate LIVE P/L for the UI
        for trade in trades:
            try:
                # FIX: Ensure symbol is formatted correctly for OANDA fetch
                oanda_sym = format_symbol_for_oanda(trade['symbol'])
                live_data = dp.get_ohlc(oanda_sym, granularity="M5", count=1)
                
                if live_data is not None and not live_data.empty:
                    current_price = float(live_data['close'].iloc[-1])
                    entry = float(trade['entry'])
                    
                    trade['current_price'] = round(current_price, 5)
                    # Calculate P/L % based on BUY or SELL side
                    if trade['side'] == "BUY":
                        p_l = ((current_price - entry) / entry) * 100
                    else:
                        p_l = ((entry - current_price) / entry) * 100
                    
                    trade['pl_pct'] = round(p_l, 2)
                else:
                    trade['pl_pct'] = 0.0 # API couldn't reach data
                    trade['current_price'] = trade['entry']
            except Exception as e:
                print(f"Error calculating P/L for {trade['symbol']}: {e}")
                trade['pl_pct'] = 0.0
            
            processed_trades.append(trade)

        return render_template('index.html', balance=balance, trades=processed_trades,
                               db_status=db_health, data_status=data_health, logic_status="Operational")
    except Exception as e:
        return f"Dashboard Error: {str(e)}"

@app.route('/tick')
def tick():
    """Scans markets via OANDA and saves to Redis"""
    for sym in SYMBOLS:
        df = dp.get_ohlc(sym, granularity="H1")
        if df is None: continue
        
        try:
            strat = StevenStrategy(df)
            signal, price, atr = strat.check_signals()
            
            if signal:
                entry_p = float(price.iloc[-1])
                trade_data = {
                    "symbol": sym, # Already has underscore
                    "side": signal,
                    "entry": round(entry_p, 5),
                    "sl": round(entry_p - (1.5 * atr) if signal == "BUY" else entry_p + (1.5 * atr), 5),
                    "tp": round(entry_p + (3.0 * atr) if signal == "BUY" else entry_p - (3.0 * atr), 5),
                    "time": pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')
                }
                redis.lpush("open_trades", json.dumps(trade_data))
        except Exception as e:
            print(f"Tick error on {sym}: {e}")

    return redirect(url_for('home'))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
