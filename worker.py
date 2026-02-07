import os
import json
import pandas as pd
from datetime import datetime
from upstash_redis import Redis
from data import DataProvider
from strategy import StevenStrategy

# --- 1. INITIALIZE CONNECTIONS ---
# These pull from the "Secrets" you added to GitHub Settings
redis = Redis(
    url=os.environ.get("UPSTASH_REDIS_REST_URL"), 
    token=os.environ.get("UPSTASH_REDIS_REST_TOKEN")
)

dp = DataProvider(
    token=os.environ.get("OANDA_API_KEY"), 
    account_id=os.environ.get("OANDA_ACCOUNT_ID")
)

# --- 2. CONFIGURATION ---
SYMBOLS = ["EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD", "NZD_USD", "EUR_JPY", "GBP_JPY"]
RISK_PER_TRADE = 0.005  # 0.5% Risk per trade
INITIAL_BALANCE = 10000.0

# --- 3. MARKET CLOCK ---

def get_market_status():
    """UTC: Friday 9PM to Sunday 9PM is closed/closing"""
    now_utc = datetime.utcnow()
    day = now_utc.weekday() # 0=Mon, 4=Fri, 5=Sat, 6=Sun
    hour = now_utc.hour

    if day == 4 and hour >= 21: return "CLOSING"
    if day == 5 or (day == 6 and hour < 21): return "CLOSED"
    return "OPEN"

# --- 4. TRADING CORE ---

def run_trading_cycle():
    status = get_market_status()
    logs = {}
    
    # CASE A: FRIDAY NIGHT - Safety First
    if status == "CLOSING":
        print("Market is closing for the weekend. Flattening account...")
        dp.close_all_positions()
        redis.delete("open_trades")
        logs["System"] = "Weekend Protection: All trades closed."
        redis.set("last_scan_logs", json.dumps(logs))
        return

    # CASE B: WEEKEND - Sleep
    if status == "CLOSED":
        print("Market is closed. Robot going back to sleep.")
        logs["System"] = "Market Closed."
        redis.set("last_scan_logs", json.dumps(logs))
        return

    # CASE C: MARKET OPEN - The Hunt
    print(f"Cycle started at {datetime.utcnow()} UTC")
    
    # 1. Sync Balance and Settled Trades
    broker_pos = dp.get_all_open_positions() # e.g. ['EUR_USD']
    db_trades = redis.lrange("open_trades", 0, -1)
    balance = float(redis.get("balance") or INITIAL_BALANCE)

    for t_raw in db_trades:
        # Handle decoding bytes from Redis
        t_str = t_raw.decode('utf-8') if hasattr(t_raw, 'decode') else t_raw
        trade = json.loads(t_str)
        
        if trade['symbol'] not in broker_pos:
            # Trade closed at broker (hit SL or TP)
            curr = dp.get_live_tick(trade['symbol']) or trade['entry']
            is_buy = trade['side'] == "BUY"
            win = (curr > trade['entry']) if is_buy else (curr < trade['entry'])
            
            # Update balance: 1.0% gain for win (2R), 0.5% loss for SL
            change = (balance * 0.01) if win else -(balance * 0.005)
            balance += change
            redis.set("balance", balance)
            redis.lrem("open_trades", 1, t_raw)
            print(f"Settled {trade['symbol']}: {'WIN' if win else 'LOSS'}")

    # 2. Scan for New Opportunities
    for sym in SYMBOLS:
        try:
            # Don't double up on the same pair
            if dp.is_position_open(sym):
                logs[sym] = "Position live."
                continue

            # Fetch Multi-Timeframe Data
            df_d = dp.get_ohlc(sym, granularity="D", count=250)
            df_h1 = dp.get_ohlc(sym, granularity="H1", count=100)
            
            if df_d is None or df_h1 is None:
                logs[sym] = "Data error."
                continue
            
            # Apply Steven's Advanced Strategy
            strat = StevenStrategy(df_h1, df_d)
            signal, price, sl, tp = strat.check_signals()
            
            if signal:
                # Calculate Units for 0.5% Risk
                risk_amt = balance * RISK_PER_TRADE
                stop_dist = abs(price - sl)
                units = int(risk_amt / stop_dist) if stop_dist > 0 else 1000
                
                # Place Order on OANDA
                if dp.place_market_order(sym, signal, units, sl, tp):
                    new_trade = {
                        "symbol": sym, 
                        "side": signal, 
                        "entry": round(price, 5), 
                        "sl": round(sl, 5), 
                        "tp_2r": round(tp, 5), 
                        "time": datetime.utcnow().strftime('%Y-%m-%d %H:%M')
                    }
                    redis.lpush("open_trades", json.dumps(new_trade))
                    logs[sym] = f"SUCCESS: {signal}"
                    print(f"Trade Entered: {signal} {sym}")
                else:
                    logs[sym] = "Broker rejected."
            else:
                logs[sym] = "No setup."

        except Exception as e:
            print(f"Error on {sym}: {e}")
            logs[sym] = "Error."

    # 3. Save logs for the Netlify Dashboard
    redis.set("last_scan_logs", json.dumps(logs))
    print("Cycle complete. Logs saved to database.")

if __name__ == "__main__":
    run_trading_cycle()
