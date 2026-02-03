import pandas as pd
import numpy as np

class StevenStrategy:
    def __init__(self, df_h1, df_h4):
        self.df = df_h1
        self.df_h4 = df_h4
        
        # --- PRO RISK SETTINGS ---
        self.sl_multiplier = 1.5      # 1.5x ATR Stop Loss
        self.reward_risk_ratio = 2.0  # 2R Target

    def calculate_indicators(self):
        # 1. H4 Trend Bias (The Filter)
        # 50 EMA on H4 is a professional mid-term trend indicator
        self.df_h4['ema50'] = self.df_h4['close'].ewm(span=50, adjust=False).mean()

        # 2. H1 Indicators (The Trigger)
        self.df['ema20'] = self.df['close'].ewm(span=20, adjust=False).mean()
        
        # ATR for volatility-based SL
        high_low = self.df['high'] - self.df['low']
        high_cp = abs(self.df['high'] - self.df['close'].shift())
        low_cp = abs(self.df['low'] - self.df['close'].shift())
        self.df['atr'] = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1).rolling(14).mean()

    def check_signals(self):
        self.calculate_indicators()
        
        h1 = self.df.iloc[-1]
        prev_h1 = self.df.iloc[-2]
        h4 = self.df_h4.iloc[-1]
        
        # --- 1. DIRECTION (H4 Filter) ---
        # Is the 4-hour trend moving?
        is_h4_bullish = h4['close'] > h4['ema50']
        is_h4_bearish = h4['close'] < h4['ema50']

        # --- 2. VALUE (H1 Pullback) ---
        # Is price currently "cheap" in an uptrend (near/below EMA)?
        # Or "expensive" in a downtrend (near/above EMA)?
        h1_buy_pullback = h1['close'] <= (h1['ema20'] + (h1['atr'] * 0.5))
        h1_sell_pullback = h1['close'] >= (h1['ema20'] - (h1['atr'] * 0.5))

        # --- 3. TRIGGER (The "Breakout" of the Pullback) ---
        # We enter when the current price breaks the HIGH of the previous hourly candle (for BUY)
        # This proves momentum is returning.
        bullish_trigger = h1['close'] > prev_h1['high']
        bearish_trigger = h1['close'] < prev_h1['low']

        # --- FINAL AGGREGATED LOGIC ---
        price = float(h1['close'])
        atr = float(h1['atr'])
        risk = atr * self.sl_multiplier

        # BUY Logic: H4 Trend Up + H1 Pullback + Momentum Break
        if is_h4_bullish and h1_buy_pullback and bullish_trigger:
            sl = price - risk
            tp = price + (risk * self.reward_risk_ratio)
            return "BUY", price, sl, tp
        
        # SELL Logic: H4 Trend Down + H1 Pullback + Momentum Break
        if is_h4_bearish and h1_sell_pullback and bearish_trigger:
            sl = price + risk
            tp = price - (risk * self.reward_risk_ratio)
            return "SELL", price, sl, tp
            
        return None, None, None, None
