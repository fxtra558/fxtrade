import os
import json
from flask import Flask, render_template, redirect, url_for, jsonify
from upstash_redis import Redis
from data import DataProvider
from strategy import StevenStrategy
import pandas as pd

app = Flask(__name__)

# --- SECURE CONFIG & SECRETS ---
# Ensure these are set in Render: 
# UPSTASH_REDIS_REST_URL, UPSTASH_REDIS_REST_TOKEN, OANDA_API_KEY, OANDA_ACCOUNT_ID
REDIS_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
OANDA_TOKEN = os.environ.get("OANDA_API_KEY")
OANDA_ACCT = os.environ.get("OANDA_ACCOUNT_ID")

# Initialize external connections
redis = Redis(url=REDIS_URL, token=REDIS_TOKEN)
dp = DataProvider(OANDA_TOKEN, OANDA_ACCT)

# Top Forex Pairs from the video
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
            # Handle potential bytes/string decoding
            t_str = t.decode('utf-8') if hasattr(t, 'decode') else t
            clean_trades.append(json.loads(t_str))
        except: continue
    return clean_trades

def settle_closed_trades():
    """
    Advanced Sync: Checks OANDA to see if any trades hit SL or TP 
    while the bot was sleeping. Updates balance if they did.
    """
    try:
        broker_positions = dp.get_all_open_positions() # Returns e.g. ['EUR_USD']
        db_trades = redis.lrange("open_trades", 0, -1)
        
        for t_raw in db_trades:
            trade = json.loads(t_raw.decode('utf-8') if hasattr(t_raw, 'decode') else t_raw)
            
            # If trade is in our database but NOT open at the broker, it closed
            if trade['symbol'] not in broker_positions:
                # 1. Fetch current price to see outcome
                live_df = dp.get_ohlc(trade['symbol'], count=1)
                if live_df is None: continue
                
                exit_price = float(live_df['close'].iloc[-1])
                entry_price = float(trade['entry'])
                
                # 2. Determine Win/Loss
                is_buy = trade['side'] == "BUY"
                win = (exit_price > entry_price) if is_buy else (exit_price < entry_price)
                
                # 3. Update Balance (Fixed $100 win / $50 loss for paper mode simulation)
                current_bal = float(redis.get("balance") or INITIAL_BALANCE)
                profit_loss = 200.0 if win else -100.0 
                redis.set("balance", current_bal + profit_loss)
                
                # 4. Remove from Open Trades list
                redis.lrem("open_trades", 1, t_raw)
                print(f"Settled {trade['symbol']}: {'WIN' if win else 'LOSS'}")
    except Exception as e:
        print(f"Settlement Error: {e}")

# --- WEB ROUTES ---

@app.route('/')
def home():
    """The Dashboard UI"""
    try:
        # Diagnostic Checks
        db_health = "Connected" if redis.ping() else "Disconnected"
        test_df = dp.get_ohlc("EUR_USD", count=1)
        data_health = "Online (OANDA)" if test_df is not None else "Offline"

        # Financial Data
        balance = float(redis.get("balance") or INITIAL_BALANCE)
        trades = get_clean_trades()

        # Update Live P/L for the UI display
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
    """The Automated Heartbeat: Settles old trades and scans for new ones"""
    try:
        # 1. First, check if any open trades finished
        settle_closed_trades()

        # 2. Scan each symbol for Steven's strategy setups
        for sym in SYMBOLS:
            # Prevent doubling up on the same pair
            if dp.is_position_open(sym): continue

            # Get H1 data for trend/pattern analysis
            df = dp.get_ohlc(sym, granularity="H1", count=100)
            if df is None or df.empty: continue
            
            strat = StevenStrategy(df)
            signal, price_data, atr = strat.check_signals()
            
            if signal:
                # Get scalar price
                price = float(price_data.iloc[-1]) if hasattr(price_data, 'iloc') else float(price_data)
                
                # Steven's Objective Risk Management
                sl = price - (1.5 * atr) if signal == "BUY" else price + (1.5 * atr)
                tp = price + (3.0 * atr) if signal == "BUY" else price - (3.0 * atr)
                
                # Execute trade on OANDA
                # 1000 units = 0.01 standard lot
                if dp.place_market_order(sym, signal, 1000, sl, tp):
                    trade_data = {
                        "symbol": sym, 
                        "side": signal, 
                        "entry": round(price, 5),
                        "sl": round(sl, 5), 
                        "tp": round(tp, 5), 
                        "time": str(pd.Timestamp.now())
                    }
                    redis.lpush("open_trades", json.dumps(trade_data))
                    
    except Exception as e:
        print(f"BOT EXECUTION ERROR: {e}")
        
    return redirect(url_for('home'))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
