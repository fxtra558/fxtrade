import pandas as pd
import numpy as np

class StevenStrategy:
    def __init__(self, df_h1, df_daily):
        self.df = df_h1
        self.df_daily = df_daily
        
        # --- RISK PARAMETERS (The Money Maker) ---
        self.sl_multiplier = 1.5  # Risking 1.5x the current volatility
        self.reward_risk_ratio = 2.0  # Making 2x what we risk (Positive Expectancy)

    def calculate_indicators(self):
        # 1. Trend & Volatility (H1)
        self.df['ema20'] = self.df['close'].ewm(span=20, adjust=False).mean()
        
        high_low = self.df['high'] - self.df['low']
        high_cp = abs(self.df['high'] - self.df['close'].shift())
        low_cp = abs(self.df['low'] - self.df['close'].shift())
        self.df['atr'] = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1).rolling(14).mean()
        
        # Volatility Regime Filter
        self.df['atr_sma'] = self.df['atr'].rolling(10).mean()

        # 2. Daily Bias (The Filter)
        self.df_daily['ema200'] = self.df_daily['close'].ewm(span=200, adjust=False).mean()

        # 3. Market Structure (Higher Lows/Lower Highs)
        self.df['recent_low'] = self.df['low'].rolling(window=10).min()
        self.df['recent_high'] = self.df['high'].rolling(window=10).max()
        self.df['prev_swing_low'] = self.df['low'].shift(10).rolling(window=10).min()
        self.df['prev_swing_high'] = self.df['high'].shift(10).rolling(window=10).max()

    def check_signals(self):
        self.calculate_indicators()
        
        row = self.df.iloc[-1]
        prev_row = self.df.iloc[-2]
        daily_row = self.df_daily.iloc[-1]
        
        # --- THE MULTI-LAYER FILTER SYSTEM ---
        is_daily_bullish = daily_row['close'] > daily_row['ema200']
        is_daily_bearish = daily_row['close'] < daily_row['ema200']
        is_vol_expanding = row['atr'] > row['atr_sma']
        has_bull_structure = row['recent_low'] > row['prev_swing_low']
        has_bear_structure = row['recent_high'] < row['prev_swing_high']
        is_h1_uptrend = row['close'] > row['ema20']
        is_h1_downtrend = row['close'] < row['ema20']

        # Patterns
        total_range = row['high'] - row['low']
        bull_382 = (row['high'] - row['close']) / total_range < 0.382 if total_range > 0 else False
        bear_382 = (row['close'] - row['low']) / total_range < 0.382 if total_range > 0 else False
        bull_engulf = (row['close'] > prev_row['open']) and (prev_row['close'] < prev_row['open'])
        bear_engulf = (row['close'] < prev_row['open']) and (prev_row['close'] > prev_row['open'])

        # --- SIGNAL EXECUTION WITH EXPECTANCY MATH ---
        price = float(row['close'])
        atr = float(row['atr'])
        risk_distance = atr * self.sl_multiplier
        reward_distance = risk_distance * self.reward_risk_ratio

        # BUY Logic
        if is_daily_bullish and is_vol_expanding and has_bull_structure:
            if is_h1_uptrend and (bull_382 or bull_engulf):
                sl = price - risk_distance
                tp = price + reward_distance
                return "BUY", price, sl, tp
        
        # SELL Logic
        if is_daily_bearish and is_vol_expanding and has_bear_structure:
            if is_h1_downtrend and (bear_382 or bear_engulf):
                sl = price + risk_distance
                tp = price - reward_distance
                return "SELL", price, sl, tp
            
        return None, None, None, None
