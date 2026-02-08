import os
import json
import pandas as pd
from datetime import datetime
from upstash_redis import Redis
from data import DataProvider
from strategy import StevenStrategy

# --- 1. INITIALIZE CONNECTIONS ---
redis = Redis(
    url=os.environ.get("UPSTASH_REDIS_REST_URL"), 
    token=os.environ.get("UPSTASH_REDIS_REST_TOKEN")
)

dp = DataProvider(
    api_key=os.environ.get("BITUNIX_API_KEY"),
    secret=os.environ.get("BITUNIX_SECRET")
)

# --- 2. CRYPTO CONFIGURATION ---
SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "ADA/USDT", "AVAX/USDT"]
RISK_PER_TRADE = 0.005  # 0.5% Risk
INITIAL_BALANCE = 10000.0

# --- 3. TRADING LOGIC ---

def run_trading_cycle():
    # WE REMOVED THE MARKET STATUS CHECK - NOW IT RUNS 24/7
    print(f"Bitunix 24/7 Pulse: {datetime.utcnow()} UTC")
    
    # A. SYNC OPEN TRADES & SETTLE BALANCES
    db_trades = redis.lrange("open_trades", 0, -1)
    balance = float(redis.get("balance") or INITIAL_BALANCE)
    
    for t_raw in db_trades:
        try:
            t_str = t_raw.decode('utf-8') if hasattr(t_raw, 'decode') else t_raw
            trade = json.loads(t_str)
            
            curr_price = dp.get_live_tick(trade['symbol'])
            if curr_price is None: continue
            
            is_buy = trade['side'] == "BUY"
            hit_tp = (curr_price >= trade['tp_2r']) if is_buy else (curr_price <= trade['tp_2r'])
            hit_sl = (curr_price <= trade['sl']) if is_buy else (curr_price >= trade['sl'])

            if hit_tp or hit_sl:
                change = (balance * 0.01) if hit_tp else -(balance * 0.005)
                balance += change
                redis.set("balance", balance)
                redis.lrem("open_trades", 1, t_raw)
                print(f"SETTLED {trade['symbol']}: {'PROFIT' if hit_tp else 'LOSS'}")
        except: continue

    # B. SCAN FOR NEW OPPORTUNITIES
    logs = {}
    current_open_list = [json.loads(t.decode('utf-8') if hasattr(t, 'decode') else t)['symbol'] for t in redis.lrange("open_trades", 0, -1)]

    for sym in SYMBOLS:
        try:
            if sym in current_open_list:
                logs[sym] = "Position live."
                continue

            df_d = dp.get_ohlc(sym, timeframe="1d", limit=250)
            df_h1 = dp.get_ohlc(sym, timeframe="1h", limit=100)
            
            if df_d is None or df_h1 is None:
                logs[sym] = "Exchange Offline."
                continue
            
            strat = StevenStrategy(df_h1, df_d)
            signal, price, sl, tp = strat.check_signals()
            
            if signal:
                risk_cash = balance * RISK_PER_TRADE
                stop_dist = abs(price - sl)
                units = risk_cash / stop_dist if stop_dist > 0 else 0
                
                if units > 0:
                    order = dp.place_market_order(sym, signal, units)
                    if order:
                        new_trade = {
                            "symbol": sym, "side": signal, "entry": round(price, 6),
                            "sl": round(sl, 6), "tp_2r": round(tp, 6),
                            "time": datetime.utcnow().strftime('%Y-%m-%d %H:%M')
                        }
                        redis.lpush("open_trades", json.dumps(new_trade))
                        logs[sym] = f"SUCCESS: {signal}"
                    else: logs[sym] = "Order Rejected."
            else:
                logs[sym] = "No setup."

        except Exception as e:
            logs[sym] = "Error."

    redis.set("last_scan_logs", json.dumps(logs))
    print(f"Cycle complete. New Balance: ${balance:,.2f}")

if __name__ == "__main__":
    run_trading_cycle()
