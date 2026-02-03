import pandas as pd
import numpy as np

class InstitutionalStrategy:
    def __init__(self, df_h1, df_h4):
        self.df = df_h1
        self.df_h4 = df_h4
        self.sl_multiplier = 1.5      
        self.reward_risk_ratio = 2.0  

    def calculate_indicators(self):
        # 1. H4 Trend Bias
        self.df_h4['ema50'] = self.df_h4['close'].ewm(span=50, adjust=False).mean()

        # 2. H1 Indicators
        self.df['ema20'] = self.df['close'].ewm(span=20, adjust=False).mean()
        high_low = self.df['high'] - self.df['low']
        high_cp = abs(self.df['high'] - self.df['close'].shift())
        low_cp = abs(self.df['low'] - self.df['close'].shift())
        self.df['atr'] = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1).rolling(14).mean()

    def check_signals(self):
        self.calculate_indicators()
        h1 = self.df.iloc[-1]
        prev_h1 = self.df.iloc[-2]
        h4 = self.df_h4.iloc[-1]
        
        is_h4_bullish = h4['close'] > h4['ema50']
        is_h4_bearish = h4['close'] < h4['ema50']
        h1_buy_zone = h1['close'] <= (h1['ema20'] + (h1['atr'] * 0.5))
        h1_sell_zone = h1['close'] >= (h1['ema20'] - (h1['atr'] * 0.5))
        bullish_trigger = h1['close'] > prev_h1['high']
        bearish_trigger = h1['close'] < prev_h1['low']

        price = float(h1['close'])
        atr = float(h1['atr'])
        risk = atr * self.sl_multiplier

        if is_h4_bullish and h1_buy_zone and bullish_trigger:
            return "BUY", price, price - risk, price + (risk * self.reward_risk_ratio)
        
        if is_h4_bearish and h1_sell_zone and bearish_trigger:
            return "SELL", price, price + risk, price - (risk * self.reward_risk_ratio)
            
        return None, None, None, None
