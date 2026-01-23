import os
import json
from flask import Flask, render_template, redirect, url_for, jsonify, request
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

# Global Settings
SYMBOLS = ["EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD"]
INITIAL_BALANCE = 10000.0
RISK_PER_TRADE = 0.005  # 0.5% risk

if not redis.exists("balance"):
    redis.set("balance", INITIAL_BALANCE)

# --- HELPER LOGIC ---

def calculate_position_size(symbol, entry, sl, balance):
    """Calculates units to trade based on 0.5% risk"""
    try:
        risk_dollars = balance * RISK_PER_TRADE
        stop_dist = abs(entry - sl)
        if stop_dist == 0: return 1000
        units = int(risk_dollars / stop_dist)
        return max(units, 1)
    except: return 1000

def get_clean_trades():
    """Retrieves trades and handles data decoding"""
    raw_trades = redis.lrange("open_trades", 0, -1)
    trades = []
    for t in raw_trades:
        try:
            t_str = t.decode('utf-8') if hasattr(t, 'decode') else t
            trades.append(json.loads(t_str))
        except: continue
    return trades

def manage_exits():
    """Syncs with OANDA to settle profits/losses and handle 2R partials"""
    try:
        broker_positions = dp.get_all_open_positions()
        db_trades = redis.lrange("open_trades", 0, -1)
        balance = float(redis.get("balance") or INITIAL_BALANCE)

        for t_raw in db_trades:
            trade = json.loads(t_raw.decode('utf-8') if hasattr(t_raw, 'decode') else t_raw)
            sym = trade['symbol']
            
            # 1. If trade hit SL/TP at broker
            if sym not in broker_positions:
                live_price = dp.get_live_tick(sym) or trade['entry']
                win = (live_price > trade['entry']) if trade['side']=="BUY" else (live_price < trade['entry'])
                # Settle balance
                change = (balance * 0.01) if win else -(balance * 0.005)
                redis.set("balance", balance + change)
                redis.lrem("open_trades", 1, t_raw)
                continue
            
            # 2. Monitor for 2R Partial TP (Manual tracker in Redis)
            if trade.get('status') == "LIVE":
                curr = dp.get_live_tick(sym)
                if curr:
                    hit_2r = (curr >= trade['tp_2r']) if trade['side']=="BUY" else (curr <= trade['tp_2r'])
                    if hit_2r:
                        redis.set("balance", balance + (balance * 0.005)) # Bank 0.5%
                        trade['status'] = "BE" # Move to Break Even
                        redis.lrem("open_trades", 1, t_raw)
                        redis.lpush("open_trades", json.dumps(trade))

    except Exception as e: print(f"Exit Error: {e}")

# --- WEB ROUTES ---

@app.route('/')
def home():
    """The Professional Dashboard"""
    try:
        # Health Checks
        db_health = "Connected" if redis.ping() else "Disconnected"
        test_df = dp.get_ohlc("EUR_USD", count=1)
        data_health = "Online" if test_df is not None else "Offline"
        
        balance = float(redis.get("balance") or INITIAL_BALANCE)
        raw_logs = redis.get("last_scan_logs")
        last_logs = json.loads(raw_logs) if raw_logs else {}
        
        # Calculate Live P/L for display
        trades = get_clean_trades()
        for t in trades:
            curr = dp.get_live_tick(t['symbol'])
            if curr:
                t['current_price'] = round(curr, 5)
                diff = (curr - t['entry']) if t['side'] == "BUY" else (t['entry'] - curr)
                t['pl_pct'] = round((diff / t['entry']) * 100, 4)
            else:
                t['current_price'] = "Syncing..."
                t['pl_pct'] = 0.0

        return render_template('index.html', balance=balance, trades=trades, 
                               db_status=db_health, data_status=data_health, 
                               logic_status="V3 Sniper", last_logs=last_logs)
    except Exception as e:
        return f"Dashboard UI Error: {str(e)}"

@app.route('/tick')
def tick():
    """The Automated Strategy Engine"""
    try:
        manage_exits()
        balance = float(redis.get("balance") or INITIAL_BALANCE)
        logs = {}
        actions = []

        for sym in SYMBOLS:
            if dp.is_position_open(sym):
                logs[sym] = "Position live."
                continue

            df_d = dp.get_ohlc(sym, granularity="D", count=250)
            df_h1 = dp.get_ohlc(sym, granularity="H1", count=100)
            if df_d is None or df_h1 is None: 
                logs[sym] = "Data Offline."
                continue
            
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
                    actions.append(f"Opened {sym}")
                    logs[sym] = f"TRADE: {signal}"
                else:
                    logs[sym] = "Broker rejected."
            else:
                logs[sym] = "Searching..."

        redis.set("last_scan_logs", json.dumps(logs), ex=3600)

        # --- FIX: SUCCESS RESPONSE FOR CRON-JOB.ORG ---
        ua = request.headers.get('User-Agent', '')
        if "cron-job.org" in ua.lower():
            return jsonify({"status": "success", "actions": actions}), 200
        
        return redirect(url_for('home'))
                    
    except Exception as e:
        print(f"Tick Crash: {e}")
        return jsonify({"status": "error", "msg": str(e)}), 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
