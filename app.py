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

# Top Forex Pairs
SYMBOLS = ["EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD"]
INITIAL_BALANCE = 10000.0

if not redis.exists("balance"):
    redis.set("balance", INITIAL_BALANCE)

# --- CORE LOGIC FUNCTIONS ---

def get_clean_trades():
    """Retrieves trades from Redis and converts them to valid Python dictionaries"""
    raw_trades = redis.lrange("open_trades", 0, -1)
    clean_trades = []
    for t in raw_trades:
        try:
            t_str = t.decode('utf-8') if hasattr(t, 'decode') else t
            clean_trades.append(json.loads(t_str))
        except: continue
    return clean_trades

def settle_closed_trades():
    """Syncs Dashboard with Broker positions and updates balance"""
    try:
        broker_positions = dp.get_all_open_positions()
        db_trades = redis.lrange("open_trades", 0, -1)
        
        for t_raw in db_trades:
            trade = json.loads(t_raw.decode('utf-8') if hasattr(t_raw, 'decode') else t_raw)
            
            if trade['symbol'] not in broker_positions:
                # Trade hit SL or TP. Fetch price to see outcome.
                live_df = dp.get_ohlc(trade['symbol'], count=1)
                if live_df is None: continue
                
                exit_price = float(live_df['close'].iloc[-1])
                entry_price = float(trade['entry'])
                is_buy = trade['side'] == "BUY"
                win = (exit_price > entry_price) if is_buy else (exit_price < entry_price)
                
                current_bal = float(redis.get("balance") or INITIAL_BALANCE)
                profit_loss = 200.0 if win else -100.0 
                redis.set("balance", current_bal + profit_loss)
                redis.lrem("open_trades", 1, t_raw)
                print(f"Settled {trade['symbol']}: {'WIN' if win else 'LOSS'}")
    except Exception as e:
        print(f"Settlement Error: {e}")

# --- WEB ROUTES ---

@app.route('/')
def home():
    """The Dashboard UI with Multi-Timeframe Health Check"""
    try:
        # Diagnostic Checks
        db_health = "Connected" if redis.ping() else "Disconnected"
        test_df = dp.get_ohlc("EUR_USD", granularity="D", count=1) # Checking Daily Feed
        data_health = "Online (OANDA D+H1)" if test_df is not None else "Offline"

        balance = float(redis.get("balance") or INITIAL_BALANCE)
        trades = get_clean_trades()

        # Update Live P/L for display
        for trade in trades:
            live_df = dp.get_ohlc(trade['symbol'], granularity="M5", count=1)
            if live_df is not None and not live_df.empty:
                curr = float(live_df['close'].iloc[-1])
                entry = float(trade['entry'])
                trade['current_price'] = curr
                diff = (curr - entry) if trade['side'] == "BUY" else (entry - curr)
                trade['pl_pct'] = round((diff / entry) * 100, 3)
            else:
                trade['current_price'] = trade['entry']
                trade['pl_pct'] = 0.0

        return render_template('index.html', balance=balance, trades=trades, 
                               db_status=db_health, data_status=data_health, logic_status="Operational")
    except Exception as e:
        return f"Dashboard Display Error: {str(e)}"

@app.route('/tick')
def tick():
    """ADVANCED LOOP: Checks Daily Trend before scanning H1 Patterns"""
    try:
        settle_closed_trades()

        for sym in SYMBOLS:
            if dp.is_position_open(sym): continue

            # UPGRADE 1: Fetch Daily data (Bias) and H1 data (Entry)
            df_daily = dp.get_ohlc(sym, granularity="D", count=250) # Need 200 for EMA200
            df_h1 = dp.get_ohlc(sym, granularity="H1", count=100)
            
            if df_daily is None or df_h1 is None: continue
            
            # Pass both timeframes into the strategy
            strat = StevenStrategy(df_h1, df_daily)
            signal, price_data, atr = strat.check_signals()
            
            if signal:
                price = float(price_data.iloc[-1]) if hasattr(price_data, 'iloc') else float(price_data)
                sl = price - (1.5 * atr) if signal == "BUY" else price + (1.5 * atr)
                tp = price + (3.0 * atr) if signal == "BUY" else price - (3.0 * atr)
                
                # Execute on OANDA
                if dp.place_market_order(sym, signal, 1000, sl, tp):
                    trade_data = {
                        "symbol": sym, "side": signal, "entry": round(price, 5),
                        "sl": round(sl, 5), "tp": round(tp, 5), 
                        "time": str(pd.Timestamp.now())
                    }
                    redis.lpush("open_trades", json.dumps(trade_data))
                    
    except Exception as e:
        print(f"BOT EXECUTION ERROR: {e}")
        
    return redirect(url_for('home'))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
