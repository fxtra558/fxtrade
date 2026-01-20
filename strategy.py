import numpy as np

class StevenStrategy:
    def __init__(self, df):
        self.df = df

    def calculate_indicators(self):
        # Moving Averages
        self.df['EMA20'] = self.df['close'].ewm(span=20, adjust=False).mean()
        self.df['EMA50'] = self.df['close'].ewm(span=50, adjust=False).mean()
        
        # ATR for Stop Loss (Steven's most important tool)
        high_low = self.df['high'] - self.df['low']
        high_cp = abs(self.df['high'] - self.df['close'].shift())
        low_cp = abs(self.df['low'] - self.df['close'].shift())
        df_tr = pd.concat([high_low, high_cp, low_cp], axis=1)
        self.df['ATR'] = df_tr.max(axis=1).rolling(14).mean()

    def check_signals(self):
        self.calculate_indicators()
        row = self.df.iloc[-1]
        prev_row = self.df.iloc[-2]
        
        # 1. TREND FILTER
        is_uptrend = row['close'] > row['EMA20'] > prev_row['EMA20']
        is_downtrend = row['close'] < row['EMA20'] < prev_row['EMA20']

        # 2. PATTERN: 38.2% CANDLE (Objective Hammer/Star)
        total_range = row['high'] - row['low']
        bullish_382 = (row['high'] - row['close']) / total_range < 0.382 if total_range != 0 else False
        bearish_382 = (row['close'] - row['low']) / total_range < 0.382 if total_range != 0 else False

        # 3. PATTERN: ENGULFING
        bull_engulf = (row['close'] > prev_row['open']) and (prev_row['close'] < prev_row['open'])
        bear_engulf = (row['close'] < prev_row['open']) and (prev_row['close'] > prev_row['open'])

        # 4. AREA OF VALUE (Near EMA20 or S/R)
        near_ema = abs(row['close'] - row['EMA20']) < (row['ATR'] * 0.5)

        if is_uptrend and (bullish_382 or bull_engulf) and near_ema:
            return "BUY", row['ATR']
        
        if is_downtrend and (bearish_382 or bear_engulf) and near_ema:
            return "SELL", row['ATR']
            
        return None, None
