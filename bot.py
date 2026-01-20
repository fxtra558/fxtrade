import time
import json
import os
from data import DataProvider
from strategy import StevenStrategy

# VIRTUAL ACCOUNT SETUP
INITIAL_BALANCE = 10000.0
PORTFOLIO_FILE = "portfolio.json"

if not os.path.exists(PORTFOLIO_FILE):
    with open(PORTFOLIO_FILE, 'w') as f:
        json.dump({"balance": INITIAL_BALANCE, "trades": []}, f)

def record_trade(side, price, atr):
    with open(PORTFOLIO_FILE, 'r') as f:
        data = json.load(f)
    
    # Calculate Risk Management (Steven's 1.5x ATR)
    sl = price - (1.5 * atr) if side == "BUY" else price + (1.5 * atr)
    tp = price + (3.0 * atr) if side == "BUY" else price - (3.0 * atr)
    
    new_trade = {
        "side": side,
        "entry": price,
        "sl": sl,
        "tp": tp,
        "status": "OPEN",
        "time": time.ctime()
    }
    
    data["trades"].append(new_trade)
    with open(PORTFOLIO_FILE, 'w') as f:
        json.dump(data, f, indent=4)
    print(f"VIRTUAL TRADE PLACED: {side} at {price}. SL: {sl}, TP: {tp}")

# MAIN LOOP
dp = DataProvider()

print("AI Bot starting in Virtual Paper Mode (No KYC)...")

while True:
    try:
        df = dp.get_ohlc("EURUSD=X")
        if df is not None:
            strat = StevenStrategy(df)
            signal, price, atr = strat.check_signals()
            
            if signal:
                record_trade(signal, price, atr)
        
        print("Scanning... No signal yet.")
        time.sleep(60) # Scan every minute
    except Exception as e:
        print(f"Error: {e}")
        time.sleep(10)
