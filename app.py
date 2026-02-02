import os
import json
from flask import Flask, render_template, redirect, url_for, jsonify, request
from upstash_redis import Redis
from data import DataProvider
from strategy import InstitutionalStrategy  # Changed from StevenStrategy
import pandas as pd
from datetime import datetime, time

app = Flask(__name__)

# --- SECURE CONFIG ---
REDIS_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
OANDA_TOKEN = os.environ.get("OANDA_API_KEY")
OANDA_ACCT = os.environ.get("OANDA_ACCOUNT_ID")

redis = Redis(url=REDIS_URL, token=REDIS_TOKEN)
dp = DataProvider(OANDA_TOKEN, OANDA_ACCT)

# Focus on the most liquid "Expert" pairs
SYMBOLS = ["EUR_USD", "GBP_USD", "XAU_USD"] 
RISK_PER_TRADE = 0.01  # Experts usually risk 1%

def get_market_status():
    now_utc = datetime.utcnow()
    day = now_utc.weekday() 
    hour = now_utc.hour
    if day == 4 and hour >= 21: return "CLOSING"
    if day == 5 or (day == 6 and hour < 21): return "CLOSED"
    return "OPEN"

def sync_with_broker():
    try:
        broker_positions = dp.get_all_open_positions()
        db_trades = redis.lrange("open_trades", 0, -1)
        balance = float(redis.get("balance") or 10000.0)

        for t_raw in db_trades:
            t_str = t_raw.decode('utf-8') if hasattr(t_raw, 'decode') else t_raw
            trade = json.loads(t_str)
            
            # If the trade is no longer open in OANDA, it hit SL or TP
            if trade['symbol'] not in broker_positions:
                # Simple logic to simulate balance update
                curr = dp.get_live_tick(trade['symbol']) or trade['entry']
                win = (curr > trade['entry']) if trade['side']=="BUY" else (curr < trade['entry'])
                # 1:2.5 Risk Reward simulation
                change = (balance * RISK_PER_TRADE * 2.5) if win else -(balance * RISK_PER_TRADE)
                redis.set("balance", balance + change)
                redis.lrem("open_trades", 1, t_raw)
    except Exception as e: print(f"Sync Error: {e}")

@app.route('/')
def home():
    try:
        mkt_status = get_market_status()
        balance = float(redis.get("balance") or 10000.0)
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
                               logic_status="Institutional Liquidity", last_logs=logs)
    except Exception as e: return f"UI Error: {e}"

@app.route('/tick')
def tick():
    status = get_market_status()
    logs = {}
    
    try:
        if status != "OPEN":
            logs["System"] = f"Market is {status}."
        else:
            sync_with_broker()
            balance = float(redis.get("balance") or 10000.0)
            
            for sym in SYMBOLS:
                if dp.is_position_open(sym):
                    logs[sym] = "Trade currently running."
                    continue

                # EXPERT DATA: Daily for Liquidity Levels, M15 for Entry Trigger
                df_d = dp.get_ohlc(sym, granularity="D", count=5)
                df_m15 = dp.get_ohlc(sym, granularity="M15", count=50)
                
                if df_d is None or df_m15 is None: 
                    logs[sym] = "Data Fetch Error"
                    continue
                
                # New Strategy Logic
                strat = InstitutionalStrategy(df_m15, df_d)
                signal, price, sl, tp = strat.check_signals()
                
                if signal:
                    # Units based on 1% risk of account balance
                    risk_amt = balance * RISK_PER_TRADE
                    pips_at_risk = abs(price - sl)
                    units = int(risk_amt / pips_at_risk) if pips_at_risk > 0 else 1000
                    
                    if dp.place_market_order(sym, signal, units, sl, tp):
                        trade_data = {
                            "symbol": sym, "side": signal, "entry": round(price, 5),
                            "sl": round(sl, 5), "tp": round(tp, 5), 
                            "status": "LIVE", "time": str(pd.Timestamp.now())
                        }
                        redis.lpush("open_trades", json.dumps(trade_data))
                        logs[sym] = f"EXECUTED {signal}: Liquidity Sweep detected."
                else: 
                    logs[sym] = "Scanning for Sweep..."

        redis.set("last_scan_logs", json.dumps(logs), ex=3600)
        return jsonify({"status": "success", "logs": logs}), 200

    except Exception as e: 
        return jsonify({"status": "error", "msg": str(e)}), 200

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
