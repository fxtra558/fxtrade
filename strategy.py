import pandas as pd
from datetime import datetime, time

class InstitutionalStrategy:
    def __init__(self, df_m15, df_daily):
        self.df = df_m15
        self.df_daily = df_daily

    def check_signals(self):
        # 1. TIME FILTER: New York Killzone (12:00 - 15:30 UTC)
        # This is the most active time for EUR/USD and GBP/USD
        current_time_utc = self.df.index[-1].time()
        start = time(12, 0)
        end = time(15, 30)
        
        if not (start <= current_time_utc <= end):
            return None, None, None, None

        # 2. LIQUIDITY LEVELS (Previous Day High/Low)
        # We look at the candle from 24 hours ago
        prev_day = self.df_daily.iloc[-2]
        pdh = prev_day['high']
        pdl = prev_day['low']
        
        # 3. CURRENT PRICE ACTION (M15 timeframe)
        now = self.df.iloc[-1]
        prev = self.df.iloc[-2]
        
        # --- LONG SETUP (The "Sweep and Reject") ---
        # Price dipped below yesterday's low and then closed back above it
        if prev['low'] < pdl and now['close'] > pdl:
            price = now['close']
            # Set SL below the recent wick, and TP for a 2.5x return
            sl = now['low'] - 0.0005 
            tp = price + ((price - sl) * 2.5)
            return "BUY", price, sl, tp

        # --- SHORT SETUP (The "Sweep and Reject") ---
        # Price pushed above yesterday's high and then closed back below it
        if prev['high'] > pdh and now['close'] < pdh:
            price = now['close']
            sl = now['high'] + 0.0005
            tp = price - ((sl - price) * 2.5)
            return "SELL", price, sl, tp

        return None, None, None, None
