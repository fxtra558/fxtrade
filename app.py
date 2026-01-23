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

SYMBOLS = ["EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD"]
RISK_PER_TRADE = 0.005  # 0.5% Risk as requested

if not redis.exists("balance"):
    redis.set("balance", 10000.0)

# --- ADVANCED LOGIC FUNCTIONS ---

def calculate_position_size(symbol, entry, sl, balance):
    """Calculates units to trade so we only lose exactly 0.5% of balance"""
    try:
        risk_amount = balance * RISK_PER_TRADE
        stop_distance = abs(entry - sl)
        if stop_distance == 0: return 1000
        
        # Simple unit calculation for Forex
        units = int(risk_amount / stop_distance)
        return max(units, 1) # Minimum 1 unit
    except: return 1000

def settle_and_manage_exits():
    """
    STEVEN V3 EXIT LOGIC:
    1. If trade is gone from OANDA -> SL hit -> Deduct 0.5% from balance.
    2. If trade hits 2R -> Bank 50% profit -> Move SL to Break Even (Redis side).
    3. If trend breaks (Price crosses EMA) -> Exit Remainder.
    """
    try:
        broker_positions = dp.get_all_open_positions()
        db_trades = redis.lrange("open_trades", 0, -1)
        current_bal = float(redis.get("balance"))

        for t_raw in db_trades:
            trade = json.loads(t_raw.decode('utf-8') if hasattr(t_raw, 'decode') else t_raw)
            sym = trade['symbol']
            
            # A. Check if broker closed it (Hard SL hit)
            if sym not in broker_positions:
                redis.set("balance", current_bal - (current_bal * RISK_PER_TRADE))
                redis.lrem("open_trades", 1, t_raw)
                continue

            # B. Fetch Live Data for Exit Monitoring
            df = dp.get_ohlc(sym, granularity="H1", count=50)
            if df is None: continue
            curr_price = float(df['close'].iloc[-1])
            ema20 = df['close'].ewm(span=20, adjust=False).mean().iloc[-1]

            # C. Check Partial TP (2R)
            if trade.get('status') == "LIVE":
                reached_2r = (curr_price >= trade['tp_2r']) if trade['side'] == "BUY" else (curr_price <= trade['tp_2r'])
                if reached_2r:
                    # Bank half of the 1% reward (since we risk 0.5%, 2R = 1% gain)
                    redis.set("balance", current_bal + (current_bal * 0.005))
                    trade['status'] = "BE" # Set to Break Even status
                    trade['sl'] = trade['entry'] # Move SL to Entry
                    redis.lrem("open_trades", 1, t_raw)
                    redis.lpush("open_trades", json.dumps(trade))
                    print(f"BANKED 2R: {sym}")

            # D. Check Trend Break Exit (Remaining 50%)
            if trade.get('status') == "BE":
                trend_broken = (curr_price < ema20) if trade['side'] == "BUY" else (curr_price > ema20)
                if trend_broken:
                    # Calculate final profit from remaining half
                    p_l_final = (curr_price - trade['entry']) if trade['side'] == "BUY" else (trade['entry'] - curr_price)
                    # (Simplified for paper money)
                    redis.set("balance", current_bal + 50.0) 
                    redis.lrem("open_trades", 1, t_raw)
                    print(f"TREND BREAK EXIT: {sym}")

    except Exception as e:
        print(f"Exit Management Error: {e}")

# --- WEB ROUTES ---

@app.route('/')
def home():
    try:
        balance = float(redis.get("balance") or 10000.0)
        trades = []
        for t in redis.lrange("open_trades", 0, -1):
            try:
                trade = json.loads(t.decode('utf-8') if hasattr(t, 'decode') else t)
                live_price = dp.get_live_tick(trade['symbol'])
                if live_price:
                    trade['current_price'] = round(live_price, 5)
                    diff = (live_price - trade['entry']) if trade['side'] == "BUY" else (trade['entry'] - live_price)
                    trade['pl_pct'] = round((diff / trade['entry']) * 100, 3)
                trades.append(trade)
            except: continue

        return render_template('index.html', balance=balance, trades=trades, 
                               db_status="Connected", data_status="Online", logic_status="V3 Sniper")
    except Exception as e:
        return f"UI Error: {e}"

@app.route('/tick')
def tick():
    """V3 SNIPER TICK: MTF + Volatility + Risk Sizing"""
    try:
        settle_and_manage_exits()
        balance = float(redis.get("balance") or 10000.0)

        for sym in SYMBOLS:
            if dp.is_position_open(sym): continue

            df_d = dp.get_ohlc(sym, granularity="D", count=250)
            df_h1 = dp.get_ohlc(sym, granularity="H1", count=100)
            if df_d is None or df_h1 is None: continue
            
            strat = StevenStrategy(df_h1, df_d)
            signal, price, sl, tp_2r = strat.check_signals()
            
            if signal:
                units = calculate_position_size(sym, price, sl, balance)
                
                if dp.place_market_order(sym, signal, units, sl, tp_2r):
                    trade_data = {
                        "symbol": sym, "side": signal, "entry": round(price, 5),
                        "sl": round(sl, 5), "tp_2r": round(tp_2r, 5), 
                        "status": "LIVE", "time": str(pd.Timestamp.now())
                    }
                    redis.lpush("open_trades", json.dumps(trade_data))
                    
    except Exception as e:
        print(f"Tick Crash: {e}")
        
    return redirect(url_for('home'))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
