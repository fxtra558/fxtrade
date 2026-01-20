import MetaTrader5 as mt5
from data import DataProvider
from strategy import StevenStrategy
import time

# CONFIG
OANDA_TOKEN = "YOUR_OANDA_API_KEY"
MT5_LOGIN = 12345678  # Your Demo Account Number
MT5_PASS = "your_password"
MT5_SERVER = "MetaQuotes-Demo"

def execute_trade(symbol, side, atr):
    point = mt5.symbol_info(symbol).point
    price = mt5.symbol_info_tick(symbol).ask if side == "BUY" else mt5.symbol_info_tick(symbol).bid
    
    # ATR based Stop Loss (1.5x ATR)
    sl = price - (1.5 * atr) if side == "BUY" else price + (1.5 * atr)
    tp = price + (3.0 * atr) if side == "BUY" else price - (3.0 * atr)

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": 0.1, # 0.1 lot
        "type": mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL,
        "price": price,
        "sl": sl,
        "tp": tp,
        "magic": 1001,
        "comment": "Steven Strategy Bot",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    mt5.order_send(request)

# MAIN LOOP
if not mt5.initialize(login=MT5_LOGIN, password=MT5_PASS, server=MT5_SERVER):
    print("MT5 Init Failed")
    quit()

dp = DataProvider(OANDA_TOKEN)

while True:
    print("Scanning market...")
    df = dp.get_ohlc("EUR_USD")
    strat = StevenStrategy(df)
    signal, atr = strat.check_signals()
    
    if signal:
        print(f"Found {signal} signal! Executing on MT5...")
        execute_trade("EURUSD", signal, atr)
    
    time.sleep(3600) # Check every hour
