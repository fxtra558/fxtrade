import os
import json
from flask import Flask, render_template, redirect, url_for, jsonify, request
from upstash_redis import Redis
from data import DataProvider
from strategy import InstitutionalStrategy  # MATCHES THE NEW NAME
import pandas as pd
from datetime import datetime

app = Flask(__name__)

# --- SECURE CONFIG ---
REDIS_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
OANDA_TOKEN = os.environ.get("OANDA_API_KEY")
OANDA_ACCT = os.environ.get("OANDA_ACCOUNT_ID")

redis = Redis(url=REDIS_URL, token=REDIS_TOKEN)
dp = DataProvider(OANDA_TOKEN, OANDA_ACCT)

SYMBOLS = ["EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD"]
INITIAL_BALANCE = 10000.0
RISK_PER_TRADE = 0.005 

# --- MARKET CLOCK ---

def get_market_status():
    now_utc = datetime.utcnow()
    day = now_utc.weekday() 
    hour = now_utc.hour
    if day == 4 and hour >= 21: return "CLOSING"
    if day == 5 or (day == 6 and hour < 21): return "CLOSED"
    return "OPEN"

# --- TRADE SYNC ---

def sync_with_broker():
    """Checks for closed positions at OANDA and updates local balance"""
    try:
        broker_positions = dp.get_all_open_positions()
        db_trades = redis.lrange("open_trades", 0, -1)
        balance = float(redis.get("balance") or INITIAL_BALANCE)

        for t_raw in db_trades:
            t_str = t_raw.decode('utf-8') if hasattr(t_raw, 'decode') else t_raw
            trade = json.loads(t_str)
            
            if trade['symbol'] not in broker_positions:
                # Trade closed at OANDA (Hit SL or TP)
                curr = dp.get_live_tick(trade['symbol']) or trade['entry']
                win = (curr > trade['entry']) if trade['side']=="BUY" else (curr < trade['entry'])
                # Math: 1.0% gain on win (2R), 0.5% loss on SL
                change = (balance * 0.01) if win else -(balance * 0.005)
                redis.set("balance", balance + change)
                redis.lrem("open_trades", 1, t_raw)
    except Exception as e:
        print(f"Sync Error: {e}")

# --- WEB ROUTES ---

@app.route('/')
def home():
    """The Main Trading Terminal Dashboard"""
    try:
        mkt_status = get_market_status()
        balance = float(redis.get("balance") or INITIAL_BALANCE)
        db_health = "Connected" if redis.ping() else "Disconnected"
        
        raw_trades = redis.lrange("open_trades", 0, -1)
        processed_trades = []
        for t in raw_trades:
            try:
                t_str = t.decode('utf-8') if hasattr(t, 'decode') else t
                trade = json.loads(t_str)
                if mkt_status == "OPEN":
                    curr = dp.get_live_tick(trade['symbol'])
                    if curr:
                        trade['current_price'] = round(curr, 5)
                        diff = (curr - trade['entry']) if trade['side'] == "BUY" else (trade['entry'] - curr)
                        trade['pl_pct'] = round((diff / trade['entry']) * 100, 4)
                processed_trades.append(trade)
            except: continue

        logs = json.loads(redis.get("last_scan_logs") or "{}")
        return render_template('index.html', balance=balance, trades=processed_trades, 
                               db_status=db_health, data_status=mkt_status, 
                               logic_status="V4 Adaptive", last_logs=logs)
    except Exception as e:
        return f"UI Display Error: {str(e)}"

@app.route('/tick')
def tick():
    """THE BOT HEARTBEAT: Optimized for Cron-job and Manual Scan"""
    status = get_market_status()
    logs = {}
    actions = []
    
    try:
        if status == "CLOSING":
            dp.close_all_positions()
            redis.delete("open_trades")
            logs["System"] = "Weekend protection: Positions Closed."
        elif status == "CLOSED":
            logs["System"] = "Market Closed. AI Sleeping."
        else:
            sync_with_broker()
            balance = float(redis.get("balance") or INITIAL_BALANCE)
            
            for sym in SYMBOLS:
                if dp.is_position_open(sym):
                    logs[sym] = "Position live."
                    continue

                # FETCH MULTI-TIMEFRAME DATA (H4 for bias, H1 for entry)
                df_h4 = dp.get_ohlc(sym, granularity="H4", count=100)
                df_h1 = dp.get_ohlc(sym, granularity="H1", count=100)
                
                if df_h4 is None or df_h1 is None: 
                    logs[sym] = "Data Feed Offline."
                    continue
                
                # RUN INSTITUTIONAL STRATEGY
                strat = InstitutionalStrategy(df_h1, df_h4)
                signal, price, sl, tp = strat.check_signals()
                
                if signal:
                    # Risk-based unit sizing (0.5% risk)
                    units = int((balance * RISK_PER_TRADE) / abs(price - sl))
                    if dp.place_market_order(sym, signal, units, sl, tp):
                        trade_data = {
                            "symbol": sym, "side": signal, "entry": round(price, 5),
                            "sl": round(float(sl), 5), "tp_2r": round(float(tp), 5), 
                            "status": "LIVE", "time": str(pd.Timestamp.now().strftime('%m-%d %H:%M'))
                        }
                        redis.lpush("open_trades", json.dumps(trade_data))
                        actions.append(f"Opened {sym}")
                        logs[sym] = f"TRADE: {signal}"
                else:
                    logs[sym] = "Searching..."

        redis.set("last_scan_logs", json.dumps(logs), ex=3600)
        
        # Determine Response Type
        ua = request.headers.get('User-Agent', '')
        if "cron-job" in ua.lower():
            return jsonify({"status": "success", "market": status}), 200
        return redirect(url_for('home'))

    except Exception as e:
        print(f"Tick Crash: {e}")
        return jsonify({"status": "error", "msg": str(e)}), 200

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
