import os
import json
from flask import Flask, render_template, redirect, url_for, jsonify
from upstash_redis import Redis
from data import DataProvider
from strategy import StevenStrategy
import pandas as pd

app = Flask(__name__)

# --- SECURE CONFIG & SECRETS ---
REDIS_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
OANDA_TOKEN = os.environ.get("OANDA_API_KEY")
OANDA_ACCT = os.environ.get("OANDA_ACCOUNT_ID")

redis = Redis(url=REDIS_URL, token=REDIS_TOKEN)
dp = DataProvider(OANDA_TOKEN, OANDA_ACCT)

SYMBOLS = ["EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD"]
INITIAL_BALANCE = 10000.0

if not redis.exists("balance"):
    redis.set("balance", INITIAL_BALANCE)

# --- HELPER FUNCTIONS ---

def get_clean_trades():
    """Retrieves trades and handles data types for JSON safety"""
    raw_trades = redis.lrange("open_trades", 0, -1)
    clean_trades = []
    for t in raw_trades:
        try:
            t_str = t.decode('utf-8') if hasattr(t, 'decode') else t
            clean_trades.append(json.loads(t_str))
        except: continue
    return clean_trades

def settle_closed_trades():
    """Checks OANDA to see if any trades closed while we were away"""
    try:
        broker_positions = dp.get_all_open_positions()
        db_trades = redis.lrange("open_trades", 0, -1)
        
        for t_raw in db_trades:
            trade = json.loads(t_raw.decode('utf-8') if hasattr(t_raw, 'decode') else t_raw)
            if trade['symbol'] not in broker_positions:
                # Trade hit SL or TP. Check win/loss.
                final_price = dp.get_live_tick(trade['symbol'])
                if final_price is None: continue
                
                win = (final_price > float(trade['entry'])) if trade['side'] == "BUY" else (final_price < float(trade['entry']))
                
                # Update Balance
                current_bal = float(redis.get("balance") or INITIAL_BALANCE)
                profit_loss = 200.0 if win else -100.0 
                redis.set("balance", current_bal + profit_loss)
                redis.lrem("open_trades", 1, t_raw)
    except Exception as e:
        print(f"Settlement Error: {e}")

# --- WEB ROUTES ---

@app.route('/')
def home():
    """Dashboard UI with Live Tick-by-Tick Pricing"""
    try:
        # 1. Connectivity Status
        db_health = "Connected" if redis.ping() else "Disconnected"
        
        # 2. Get Open Trades
        balance = float(redis.get("balance") or INITIAL_BALANCE)
        trades = get_clean_trades()
        processed_trades = []

        # 3. FIX: Fetch ACTUAL LIVE TICKS for each trade
        for trade in trades:
            live_price = dp.get_live_tick(trade['symbol'])
            
            if live_price is not None:
                entry = float(trade['entry'])
                trade['current_price'] = round(live_price, 5)
                
                # Calculate P/L based on Side
                if trade['side'] == "BUY":
                    p_l = ((live_price - entry) / entry) * 100
                else:
                    p_l = ((entry - live_price) / entry) * 100
                
                trade['pl_pct'] = round(p_l, 4) # High precision for small moves
            else:
                trade['current_price'] = "Offline"
                trade['pl_pct'] = 0.0

            processed_trades.append(trade)

        return render_template('index.html', balance=balance, trades=processed_trades, 
                               db_status=db_health, data_status="Online (Tick Feed)", logic_status="Operational")
    except Exception as e:
        return f"Dashboard UI Error: {str(e)}"

@app.route('/tick')
def tick():
    """Scans markets using H1 strategy and Daily Bias"""
    try:
        settle_closed_trades()

        for sym in SYMBOLS:
            if dp.is_position_open(sym): continue

            # Multi-Timeframe logic
            df_daily = dp.get_ohlc(sym, granularity="D", count=250)
            df_h1 = dp.get_ohlc(sym, granularity="H1", count=100)
            
            if df_daily is None or df_h1 is None: continue
            
            strat = StevenStrategy(df_h1, df_daily)
            signal, price_data, sl, tp = strat.check_signals()
            
            if signal:
                # Ensure price is a number
                price = float(price_data.iloc[-1]) if hasattr(price_data, 'iloc') else float(price_data)
                
                if dp.place_market_order(sym, signal, 1000, sl, tp):
                    trade_data = {
                        "symbol": sym, "side": signal, "entry": round(price, 5),
                        "sl": round(float(sl), 5), "tp": round(float(tp), 5), 
                        "time": str(pd.Timestamp.now())
                    }
                    redis.lpush("open_trades", json.dumps(trade_data))
                    
    except Exception as e:
        print(f"BOT SCAN ERROR: {e}")
        
    return redirect(url_for('home'))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
