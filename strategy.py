import pandas as pd
import numpy as np

class StevenStrategy:
    def __init__(self, df_h1, df_daily):
        self.df = df_h1
        self.df_daily = df_daily
        
        # --- FIXED RISK RULES ---
        self.sl_multiplier = 1.5      # 1.5x ATR Stop Loss
        self.reward_risk_ratio = 2.0   # 2.0R Profit Target

    def calculate_indicators(self):
        # 1. BIAS (Daily) - Trend Filter
        self.df_daily['ema200'] = self.df_daily['close'].ewm(span=200, adjust=False).mean()

        # 2. REGIME (H1) - ATR Expansion
        high_low = self.df['high'] - self.df['low']
        high_cp = abs(self.df['high'] - self.df['close'].shift())
        low_cp = abs(self.df['low'] - self.df['close'].shift())
        self.df['atr'] = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1).rolling(14).mean()
        self.df['atr_mean'] = self.df['atr'].rolling(20).mean()

        # 3. VALUE (H1) - EMA 20
        self.df['ema20'] = self.df['close'].ewm(span=20, adjust=False).mean()

    def check_signals(self):
        self.calculate_indicators()
        
        h1 = self.df.iloc[-1]
        prev_h1 = self.df.iloc[-2]
        daily = self.df_daily.iloc[-1]
        
        # 1. DIRECTIONAL BIAS
        is_bullish_bias = daily['close'] > daily['ema200']
        is_bearish_bias = daily['close'] < daily['ema200']

        # 2. REGIME FILTER (Volatility must be expanding)
        is_expanding = h1['atr'] > h1['atr_mean']

        # 3. ENTRY LOCATION (Must be within 1 ATR of the EMA 20)
        price_to_ema_dist = abs(h1['close'] - h1['ema20'])
        is_at_value = price_to_ema_dist <= h1['atr']

        # 4. CONFIRMATION (Structural Failure)
        bullish_confirm = h1['low'] > prev_h1['low']
        bearish_confirm = h1['high'] < prev_h1['high']

        # --- EXECUTION ---
        price = float(h1['close'])
        atr = float(h1['atr'])
        risk = atr * self.sl_multiplier

        # BUY: Bias UP + Expanding Vol + At Value + Structural Confirmation
        if is_bullish_bias and is_expanding and is_at_value and bullish_confirm:
            sl = price - risk
            tp2r = price + (risk * self.reward_risk_ratio)
            return "BUY", price, sl, tp2r

        # SELL: Bias DOWN + Expanding Vol + At Value + Structural Confirmation
        if is_bearish_bias and is_expanding and is_at_value and bearish_confirm:
            sl = price + risk
            tp2r = price - (risk * self.reward_risk_ratio)
            return "SELL", price, sl, tp2r
            
        return None, None, None, None
