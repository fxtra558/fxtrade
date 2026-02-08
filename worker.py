import os
import json
import pandas as pd
from datetime import datetime
from upstash_redis import Redis
from data import DataProvider
from strategy import StevenStrategy

# --- 1. INITIALIZE CONNECTIONS ---
# Pulls from GitHub Secrets
redis = Redis(
    url=os.environ.get("UPSTASH_REDIS_REST_URL"), 
    token=os.environ.get("UPSTASH_REDIS_REST_TOKEN")
)
dp = DataProvider()

# --- 2. CRYPTO CONFIGURATION ---
# Popular trending coins (Yahoo Finance format)
COINS = ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "ADA-USD", "AVAX-USD"]
RISK_PER_TRADE = 0.005  # 0.5% Risk
INITIAL_BALANCE = 10000.0

def run_trading_cycle():
    print(f"Crypto Pulse Started: {datetime.utcnow()} UTC")
    
    # --- STEP 1: SYNC & SETTLE ---
    # Since we have no broker, the bot checks if price hit SL or TP itself
    db_trades = redis.lrange("open_trades", 0, -1)
    balance = float(redis.get("balance") or INITIAL_BALANCE)
    
    for t_raw in db_trades:
        t_str = t_raw.decode('utf-8') if hasattr(t_raw, 'decode') else t_raw
        trade = json.loads(t_str)
        
        # Get live price for the coin
        curr_price = dp.get_live_tick(trade['symbol'])
        if curr_price is None: continue
        
        # Check Win/Loss conditions
        is_buy = trade['side'] == "BUY"
        hit_tp = (curr_price >= trade['tp_2r']) if is_buy else (curr_price <= trade['tp_2r'])
        hit_sl = (curr_price <= trade['sl']) if is_buy else (curr_price >= trade['sl'])

        if hit_tp or hit_sl:
            # 2R Payoff: Profit = 1% gain (2x risk), Loss = 0.5% loss
            change = (balance * 0.01) if hit_tp else -(balance * 0.005)
            balance += change
            redis.set("balance", balance)
            redis.lrem("open_trades", 1, t_raw)
            print(f"CLOSED {trade['symbol']}: {'WIN' if hit_tp else 'LOSS'}")

    # --- STEP 2: SCAN FOR NEW TRADES ---
    logs = {}
    current_open_symbols = [json.loads(t.decode('utf-8') if hasattr(t, 'decode') else t)['symbol'] for t in redis.lrange("open_trades", 0, -1)]

    for coin in COINS:
        try:
            # Prevent double trades on the same coin
            if coin in current_open_symbols:
                logs[coin] = "Position active."
                continue

            # Fetch Multi-Timeframe Data (D for Bias, H1 for Entry)
            df_d = dp.get_ohlc(coin, interval="1d", period="250d")
            df_h1 = dp.get_ohlc(coin, interval="1h", period="5d")
            
            if df_d is None or df_h1 is None:
                logs[coin] = "Data Offline."
                continue
            
            # Run Steven's V4.1 Strategy
            strat = StevenStrategy(df_h1, df_d)
            signal, price, sl, tp = strat.check_signals()
            
            if signal:
                # Place virtual trade in database
                new_trade = {
                    "symbol": coin,
                    "side": signal,
                    "entry": round(price, 5),
                    "sl": round(sl, 5),
                    "tp_2r": round(tp, 5),
                    "time": datetime.utcnow().strftime('%Y-%m-%d %H:%M')
                }
                redis.lpush("open_trades", json.dumps(new_trade))
                logs[coin] = f"TRADE: {signal}"
                print(f"ENTRY: {signal} {coin} at {price}")
            else:
                logs[coin] = "Searching..."

        except Exception as e:
            print(f"Error on {coin}: {e}")
            logs[coin] = "Error."

    # --- STEP 3: LOGS & FINAL PERSISTENCE ---
    redis.set("last_scan_logs", json.dumps(logs))
    print(f"Cycle complete. Balance: ${balance:,.2f}")

if __name__ == "__main__":
    run_trading_cycle()
