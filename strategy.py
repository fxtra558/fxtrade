import pandas as pd
import numpy as np

class StevenStrategy:
    def __init__(self, df_h1, df_daily):
        self.df = df_h1
        self.df_daily = df_daily

    def calculate_indicators(self):
        # --- BASIC INDICATORS ---
        self.df['ema20'] = self.df['close'].ewm(span=20, adjust=False).mean()
        
        high_low = self.df['high'] - self.df['low']
        high_cp = abs(self.df['high'] - self.df['close'].shift())
        low_cp = abs(self.df['low'] - self.df['close'].shift())
        self.df['atr'] = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1).rolling(14).mean()
        
        # Volatility Filter (Upgrade 2)
        self.df['atr_sma'] = self.df['atr'].rolling(10).mean()

        # Daily Bias (Upgrade 1)
        self.df_daily['ema200'] = self.df_daily['close'].ewm(span=200, adjust=False).mean()

        # --- UPGRADE 3: MARKET STRUCTURE (Higher Lows / Lower Highs) ---
        # We look back at the previous 'swing' points to confirm structure
        # A simple way to do this programmatically is comparing recent minima/maxima
        self.df['recent_low'] = self.df['low'].rolling(window=10).min()
        self.df['recent_high'] = self.df['high'].rolling(window=10).max()
        
        # We find the low/high from 10 to 20 candles ago for comparison
        self.df['prev_swing_low'] = self.df['low'].shift(10).rolling(window=10).min()
        self.df['prev_swing_high'] = self.df['high'].shift(10).rolling(window=10).max()

    def check_signals(self):
        self.calculate_indicators()
        
        row = self.df.iloc[-1]
        prev_row = self.df.iloc[-2]
        daily_row = self.df_daily.iloc[-1]
        
        # 1. BIAS & VOLATILITY FILTERS
        is_daily_bullish = daily_row['close'] > daily_row['ema200']
        is_daily_bearish = daily_row['close'] < daily_row['ema200']
        is_volatility_expanding = row['atr'] > row['atr_sma']

        # 2. UPGRADE 3: STRUCTURE CHECK
        # BUY: Current local low must be HIGHER than the previous swing low (Higher Low)
        has_bullish_structure = row['recent_low'] > row['prev_swing_low']
        
        # SELL: Current local high must be LOWER than the previous swing high (Lower High)
        has_bearish_structure = row['recent_high'] < row['prev_swing_high']

        # 3. H1 CONTEXT
        is_h1_uptrend = row['close'] > row['ema20']
        is_h1_downtrend = row['close'] < row['ema20']
        near_ema = abs(row['close'] - row['ema20']) < (row['atr'] * 1.5)

        # 4. CANDLESTICK PATTERN TRIGGERS
        total_range = row['high'] - row['low']
        bullish_382 = (row['high'] - row['close']) / total_range < 0.382 if total_range > 0 else False
        bearish_382 = (row['close'] - row['low']) / total_range < 0.382 if total_range > 0 else False
        
        bull_engulf = (row['close'] > prev_row['open']) and (prev_row['close'] < prev_row['open'])
        bear_engulf = (row['close'] < prev_row['open']) and (prev_row['close'] > prev_row['open'])

        # --- FINAL AGGREGATED LOGIC ---
        
        # BUY Logic: Daily UP + Volatility UP + Higher Low + H1 UP + Pattern
        if is_daily_bullish and is_volatility_expanding and has_bullish_structure:
            if is_h1_uptrend and (bullish_382 or bull_engulf) and near_ema:
                return "BUY", row['close'], row['atr']
        
        # SELL Logic: Daily DOWN + Volatility UP + Lower High + H1 DOWN + Pattern
        if is_daily_bearish and is_volatility_expanding and has_bearish_structure:
            if is_h1_downtrend and (bearish_382 or bear_engulf) and near_ema:
                return "SELL", row['close'], row['atr']
            
        return None, None, None
