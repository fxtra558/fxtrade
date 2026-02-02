import pandas as pd
import numpy as np

class InstitutionalFlowStrategy:
    def __init__(self, df_m15, df_daily):
        self.df = df_m15       # 15-minute for execution
        self.df_daily = df_daily # Daily for levels
        
    def calculate_levels(self):
        # 1. Get Previous Day High/Low (The Liquidity)
        prev_day = self.df_daily.iloc[-2] # The completed yesterday candle
        self.pdh = prev_day['high']
        self.pdl = prev_day['low']
        
        # 2. Daily Bias (Is the market overall bullish or bearish?)
        # Simple Expert Rule: If yesterday closed higher than it opened, bias is Bullish
        self.bullish_bias = prev_day['close'] > prev_day['open']

    def check_signals(self):
        self.calculate_levels()
        
        # Get current state
        now = self.df.iloc[-1]
        prev = self.df.iloc[-2]
        current_time = self.df.index[-1].time()
        
        # 3. TIME FILTER (Expert's Secret: Only trade the "Killzone")
        # New York Open: 8:00 AM - 11:00 AM EST
        is_ny_session = time(8, 0) <= current_time <= time(11, 0)
        if not is_ny_session:
            return None, "Wait for NY Session"

        # 4. THE TRAP & REVERSAL LOGIC (TJR Style)
        
        # --- LONG SETUP ---
        # A) Price must have dropped BELOW yesterday's low (The Liquidity Sweep)
        # B) Current 15m candle must close back ABOVE yesterday's low (The Rejection)
        # C) Trend Bias should be Bullish
        if self.bullish_bias:
            if prev['low'] < self.pdl and now['close'] > self.pdl:
                price = now['close']
                # Risk management: SL below the recent low, Target 2x Risk
                sl = now['low'] - (price * 0.001) 
                tp = price + ((price - sl) * 2.5) 
                return "BUY", price, sl, tp

        # --- SHORT SETUP ---
        # A) Price must have pushed ABOVE yesterday's high (The Sweep)
        # B) Current 15m candle must close back BELOW yesterday's high (The Rejection)
        # C) Trend Bias should be Bearish
        if not self.bullish_bias:
            if prev['high'] > self.pdh and now['close'] < self.pdh:
                price = now['close']
                sl = now['high'] + (price * 0.001)
                tp = price - ((sl - price) * 2.5)
                return "SELL", price, sl, tp

        return None, "Scanning for Liquidity Sweep..."
