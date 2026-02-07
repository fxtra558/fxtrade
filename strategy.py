import pandas as pd
import numpy as np
from ta.trend import ADXIndicator

class StevenStrategy:
    def __init__(self, df_h1, df_daily):
        self.df = df_h1
        self.df_daily = df_daily
        self.sl_multiplier = 1.5
        self.reward_risk_ratio = 2.0

    def calculate_indicators(self):
        # 1. H1 Indicators
        adx_io = ADXIndicator(self.df['high'], self.df['low'], self.df['close'], window=14)
        self.df['adx'] = adx_io.adx()
        self.df['ema20'] = self.df['close'].ewm(span=20, adjust=False).mean()
        self.df['ema50'] = self.df['close'].ewm(span=50, adjust=False).mean()
        
        # ATR Calculation
        high_low = self.df['high'] - self.df['low']
        high_cp = abs(self.df['high'] - self.df['close'].shift())
        low_cp = abs(self.df['low'] - self.df['close'].shift())
        self.df['atr'] = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1).rolling(14).mean()
        self.df['atr_median'] = self.df['atr'].rolling(50).median()

        # 2. Daily Indicators
        self.df_daily['ema200'] = self.df_daily['close'].ewm(span=200, adjust=False).mean()

    def check_signals(self):
        self.calculate_indicators()
        
        if self.df.iloc[-2:].isnull().values.any() or self.df_daily.iloc[-2:].isnull().values.any():
            return None, None, None, None

        h1 = self.df.iloc[-1]
        prev_h1 = self.df.iloc[-2]
        daily = self.df_daily.iloc[-1]
        daily_prev = self.df_daily.iloc[-2]

        # --- 1. DIRECTIONAL BIAS (UPGRADE: STRONG TREND EXCEPTION) ---
        ema_rising = daily['ema200'] > daily_prev['ema200']
        # If trend is ultra-strong (ADX > 25), we don't care about the EMA slope
        is_strong_trend = h1['adx'] > 25
        
        bullish_bias = daily['close'] > daily['ema200'] and (ema_rising or is_strong_trend)
        bearish_bias = daily['close'] < daily['ema200'] and (not ema_rising or is_strong_trend)

        # --- 2. TREND REGIME (RELAXED TO 15) ---
        is_trending = h1['adx'] > 15
        
        # --- 3. VOLATILITY FLOOR (RELAXED TO 90% OF MEDIAN) ---
        atr_ok = h1['atr'] > (h1['atr_median'] * 0.9)

        # --- 4. ENTRY LOGIC: MOMENTUM PULLBACK (RELAXED) ---
        # BUY Logic
        above_anchor_buy = h1['close'] > h1['ema50']
        # Pullback Zone: Allow 0.2% leeway
        pullback_buy = h1['low'] <= (h1['ema20'] * 1.002)
        # Momentum: Close above previous Close (Faster trigger)
        momentum_buy = h1['close'] > prev_h1['close']

        # SELL Logic
        below_anchor_sell = h1['close'] < h1['ema50']
        pullback_sell = h1['high'] >= (h1['ema20'] * 0.998)
        momentum_sell = h1['close'] < prev_h1['close']

        price = float(h1['close'])
        atr = float(h1['atr'])
        risk = atr * self.sl_multiplier

        # LONG EXECUTION
        if bullish_bias and is_trending and atr_ok:
            if above_anchor_buy and pullback_buy and momentum_buy:
                return "BUY", price, price - risk, price + (risk * self.reward_risk_ratio)

        # SHORT EXECUTION
        if bearish_bias and is_trending and atr_ok:
            if below_anchor_sell and pullback_sell and momentum_sell:
                return "SELL", price, price + risk, price - (risk * self.reward_risk_ratio)
            
        return None, None, None, None
