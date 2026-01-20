import os
from flask import Flask
from upstash_redis import Redis
import yfinance as yf
import pandas as pd
from strategy import StevenStrategy

app = Flask(__name__)

# --- CONNECT TO DATABASE ---
# Paste your credentials here
REDIS_URL = "YOUR_UPSTASH_REDIS_REST_URL"
REDIS_TOKEN = "YOUR_UPSTASH_REDIS_REST_TOKEN"
redis = Redis(url=REDIS_URL, token=REDIS_TOKEN)

# Popular Pairs to Scan
SYMBOLS = ["EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X"]

if not redis.exists("balance"):
    redis.set("balance", 10000.0)

def manage_open_trades(current_prices):
    """Checks if open trades hit SL or TP"""
    trades = redis.lrange("open_trades", 0, -1)
    for trade_str in trades:
        trade = eval(trade_str) # Convert string back to dict
        symbol = trade['symbol']
        current_price = current_prices[symbol]
        
        # Check Exit Conditions
        hit_tp = (trade['side'] == "BUY" and current_price >= trade['tp']) or \
                 (trade['side'] == "SELL" and current_price <= trade['tp'])
        hit_sl = (trade['side'] == "BUY" and current_price <= trade['sl']) or \
                 (trade['side'] == "SELL" and current_price >= trade['sl'])

        if hit_tp or hit_sl:
            # Update Balance and Remove Trade
            profit = 100 if hit_tp else -50 # Simplified for paper mode
            new_balance = float(redis.get("balance")) + profit
            redis.set("balance", new_balance)
            redis.lrem("open_trades", 1, trade_str)
            print(f"CLOSED {symbol}: {'Profit' if hit_tp else 'Loss'}")

@app.route('/tick')
def tick():
    prices = {}
    for sym in SYMBOLS:
        data = yf.download(tickers=sym, period="5d", interval="1h", progress=False)
        if data.empty: continue
        
        # Format data
        df = data.copy()
        df.columns = [col[0].lower() if isinstance(col, tuple) else col.lower() for col in df.columns]
        prices[sym] = df['close'].iloc[-1]
        
        # Check Strategy
        strat = StevenStrategy(df)
        signal, price, atr = strat.check_signals()
        
        if signal:
            # 1.5x ATR SL and 3.0x ATR TP (Advanced Rule)
            sl = price - (1.5 * atr) if signal == "BUY" else price + (1.5 * atr)
            tp = price + (3.0 * atr) if signal == "BUY" else price - (3.0 * atr)
            
            new_trade = {"symbol": sym, "side": signal, "entry": price, "sl": sl, "tp": tp}
            redis.lpush("open_trades", str(new_trade))
            print(f"ENTRY: {signal} {sym} at {price}")

    manage_open_trades(prices)
    return {"status": "Success", "balance": redis.get("balance")}

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
