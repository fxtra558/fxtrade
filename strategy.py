import pandas as pd
from datetime import datetime, time

class InstitutionalStrategy:
    def __init__(self, df_m15, df_daily):
        self.df = df_m15
        self.df_daily = df_daily

    def check_signals(self):
        # 1. TIME FILTER: New York Killzone (12:00 - 15:30 UTC)
        current_time_utc = self.df.index[-1].time()
        start = time(12, 0)
        end = time(15, 30)
        
        if not (start <= current_time_utc <= end):
            return None, None, None, None

        # 2. LIQUIDITY LEVELS (Previous Day High/Low)
        prev_day = self.df_daily.iloc[-2]
        pdh = prev_day['high']
        pdl = prev_day['low']
        
        # 3. CURRENT PRICE ACTION (M15)
        now = self.df.iloc[-1]
        prev = self.df.iloc[-2]
        
        # BUY: Price swept PDL (dropped below) and closed back above it
        if prev['low'] < pdl and now['close'] > pdl:
            price = now['close']
            sl = now['low'] - 0.0005 # Tight SL below the sweep
            tp = price + ((price - sl) * 2.5) # 1:2.5 RR
            return "BUY", price, sl, tp

        # SELL: Price swept PDH (pushed above) and closed back below it
        if prev['high'] > pdh and now['close'] < pdh:
            price = now['close']
            sl = now['high'] + 0.0005
            tp = price - ((sl - price) * 2.5)
            return "SELL", price, sl, tp

        return None, None, None, None
