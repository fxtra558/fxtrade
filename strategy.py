import pandas as pd

class StevenStrategy:
    def __init__(self, df):
        self.df = df

    def check_signals(self):
        # Indicators
        self.df['ema20'] = self.df['close'].ewm(span=20, adjust=False).mean()
        high_low = self.df['high'] - self.df['low']
        high_cp = abs(self.df['high'] - self.df['close'].shift())
        low_cp = abs(self.df['low'] - self.df['close'].shift())
        self.df['atr'] = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1).rolling(14).mean()

        row = self.df.iloc[-1]
        prev_row = self.df.iloc[-2]
        
        # 1. Trend Filter
        is_uptrend = row['close'] > row['ema20']
        is_downtrend = row['close'] < row['ema20']

        # 2. 38.2% Candle (Objective Pattern)
        total_range = row['high'] - row['low']
        bull_382 = (row['high'] - row['close']) / total_range < 0.382 if total_range > 0 else False
        bear_382 = (row['close'] - row['low']) / total_range < 0.382 if total_range > 0 else False

        # 3. Engulfing
        bull_engulf = (row['close'] > prev_row['open']) and (prev_row['close'] < prev_row['open'])
        bear_engulf = (row['close'] < prev_row['open']) and (prev_row['close'] > prev_row['open'])

        # 4. Area of Value
        near_ema = abs(row['close'] - row['ema20']) < (row['atr'] * 1.2)

        if is_uptrend and (bull_382 or bull_engulf) and near_ema:
            return "BUY", row['close'], row['atr']
        if is_downtrend and (bear_382 or bear_engulf) and near_ema:
            return "SELL", row['close'], row['atr']
        return None, None, None
