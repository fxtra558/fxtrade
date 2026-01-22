import pandas as pd

class StevenStrategy:
    def __init__(self, df_h1, df_daily):
        self.df = df_h1
        self.df_daily = df_daily

    def calculate_indicators(self):
        # --- H1 INDICATORS ---
        self.df['ema20'] = self.df['close'].ewm(span=20, adjust=False).mean()
        
        # Calculate ATR (14)
        high_low = self.df['high'] - self.df['low']
        high_cp = abs(self.df['high'] - self.df['close'].shift())
        low_cp = abs(self.df['low'] - self.df['close'].shift())
        self.df['atr'] = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1).rolling(14).mean()

        # --- UPGRADE 2: MARKET REGIME (VOLATILITY EXPANSION) ---
        # We calculate the average ATR of the last 10 candles
        # If the current ATR is higher than the average, volatility is 'expanding'
        self.df['atr_sma'] = self.df['atr'].rolling(10).mean()

        # --- DAILY INDICATORS (BIAS) ---
        self.df_daily['ema200'] = self.df_daily['close'].ewm(span=200, adjust=False).mean()

    def check_signals(self):
        self.calculate_indicators()
        
        row = self.df.iloc[-1]
        prev_row = self.df.iloc[-2]
        daily_row = self.df_daily.iloc[-1]
        
        # 1. UPGRADE 1: DIRECTIONAL BIAS (Daily 200 EMA)
        is_daily_bullish = daily_row['close'] > daily_row['ema200']
        is_daily_bearish = daily_row['close'] < daily_row['ema200']

        # 2. UPGRADE 2: MARKET REGIME FILTER (Expansion Check)
        # We ONLY trade if the current volatility is higher than the recent average.
        # This prevents trading in 'dead' or 'choppy' sideways markets.
        is_volatility_expanding = row['atr'] > row['atr_sma']

        # 3. H1 Trend & Location
        is_h1_uptrend = row['close'] > row['ema20']
        is_h1_downtrend = row['close'] < row['ema20']
        near_ema = abs(row['close'] - row['ema20']) < (row['atr'] * 1.2)

        # 4. Candlestick Patterns
        total_range = row['high'] - row['low']
        bullish_382 = (row['high'] - row['close']) / total_range < 0.382 if total_range > 0 else False
        bearish_382 = (row['close'] - row['low']) / total_range < 0.382 if total_range > 0 else False
        
        bull_engulf = (row['close'] > prev_row['open']) and (prev_row['close'] < prev_row['open'])
        bear_engulf = (row['close'] < prev_row['open']) and (prev_row['close'] > prev_row['open'])

        # --- FINAL SIGNAL LOGIC ---
        
        # We added 'is_volatility_expanding' to the requirements
        if is_daily_bullish and is_h1_uptrend and is_volatility_expanding:
            if (bullish_382 or bull_engulf) and near_ema:
                return "BUY", row['close'], row['atr']
        
        if is_daily_bearish and is_downtrend and is_volatility_expanding:
            if (bearish_382 or bear_engulf) and near_ema:
                return "SELL", row['close'], row['atr']
            
        return None, None, None
