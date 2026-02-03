import pandas as pd
import numpy as np

class InstitutionalStrategy:
    def __init__(self, df_h1, df_h4):
        self.df = df_h1
        self.df_h4 = df_h4
        
        # --- PRO RISK SETTINGS ---
        self.sl_multiplier = 1.5      # 1.5x ATR Stop Loss
        self.reward_risk_ratio = 2.0  # 2.0R Target (Win $200 for every $100 risked)

    def calculate_indicators(self):
        # 1. H4 Trend Bias (The Big Picture)
        # We use a 50 EMA on H4. If price is above, we only BUY.
        self.df_h4['ema50'] = self.df_h4['close'].ewm(span=50, adjust=False).mean()

        # 2. H1 Indicators (The Execution)
        self.df['ema20'] = self.df['close'].ewm(span=20, adjust=False).mean()
        
        # ATR for volatility-adjusted Stop Loss
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
        is_h4_bullish = h4['close'] > h4['ema50']
        is_h4_bearish = h4['close'] < h4['ema50']

        # --- 2. VALUE (H1 Pullback Zone) ---
        # We look for price to be near the EMA 20 (The 'Spring' effect)
        h1_buy_zone = h1['close'] <= (h1['ema20'] + (h1['atr'] * 0.5))
        h1_sell_zone = h1['close'] >= (h1['ema20'] - (h1['atr'] * 0.5))

        # --- 3. MOMENTUM TRIGGER (Structural Break) ---
        # Instead of a 'shape', we wait for price to break the previous candle's high/low
        bullish_trigger = h1['close'] > prev_h1['high']
        bearish_trigger = h1['close'] < prev_h1['low']

        # --- 4. RISK MATH ---
        price = float(h1['close'])
        atr = float(h1['atr'])
        risk = atr * self.sl_multiplier

        # --- FINAL AGGREGATED LOGIC ---
        
        # BUY: H4 Trend Up + H1 Price is 'Cheap' + Momentum breaking higher
        if is_h4_bullish and h1_buy_zone and bullish_trigger:
            sl = price - risk
            tp = price + (risk * self.reward_risk_ratio)
            return "BUY", price, sl, tp
        
        # SELL: H4 Trend Down + H1 Price is 'Expensive' + Momentum breaking lower
        if is_h4_bearish and h1_sell_zone and bearish_trigger:
            sl = price + risk
            tp = price - (risk * self.reward_risk_ratio)
            return "SELL", price, sl, tp
            
        return None, None, None, None
