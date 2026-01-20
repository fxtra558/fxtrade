import pandas as pd

class StevenStrategy:
    def __init__(self, df):
        self.df = df

    def calculate_indicators(self):
        # Trend Filter
        self.df['ema20'] = self.df['close'].ewm(span=20, adjust=False).mean()
        
        # ATR for Stop Loss (Steven's Rule)
        high_low = self.df['high'] - self.df['low']
        high_cp = abs(self.df['high'] - self.df['close'].shift())
        low_cp = abs(self.df['low'] - self.df['close'].shift())
        self.df['tr'] = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1)
        self.df['atr'] = self.df['tr'].rolling(14).mean()

    def check_signals(self):
        self.calculate_indicators()
        row = self.df.iloc[-1]
        prev_row = self.df.iloc[-2]
        
        # Rule 1: Trend Filter (Price relative to EMA)
        is_uptrend = row['close'] > row['ema20']
        is_downtrend = row['close'] < row['ema20']

        # Rule 2: 38.2% Candle (Objective Pattern)
        total_range = row['high'] - row['low']
        bullish_382 = (row['high'] - row['close']) / total_range < 0.382 if total_range > 0 else False
        bearish_382 = (row['close'] - row['low']) / total_range < 0.382 if total_range > 0 else False

        # Rule 3: Engulfing Pattern
        bull_engulf = (row['close'] > prev_row['open']) and (prev_row['close'] < prev_row['open'])
        bear_engulf = (row['close'] < prev_row['open']) and (prev_row['close'] > prev_row['open'])

        # Rule 4: Area of Value (Price is near the EMA)
        near_ema = abs(row['close'] - row['ema20']) < (row['atr'] * 1.0)

        if is_uptrend and (bullish_382 or bull_engulf) and near_ema:
            return "BUY", row['close'], row['atr']
        
        if is_downtrend and (bearish_382 or bear_engulf) and near_ema:
            return "SELL", row['close'], row['atr']
            
        return None, None, None
