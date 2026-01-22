import pandas as pd

class StevenStrategy:
    def __init__(self, df_h1, df_daily):
        """
        df_h1: 1-Hour data for entry patterns
        df_daily: Daily data for long-term trend bias
        """
        self.df = df_h1
        self.df_daily = df_daily

    def calculate_indicators(self):
        # 1. MAIN TIMEFRAME (H1) INDICATORS
        self.df['ema20'] = self.df['close'].ewm(span=20, adjust=False).mean()
        
        # ATR for volatility-adjusted Stop Loss
        high_low = self.df['high'] - self.df['low']
        high_cp = abs(self.df['high'] - self.df['close'].shift())
        low_cp = abs(self.df['low'] - self.df['close'].shift())
        self.df['atr'] = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1).rolling(14).mean()

        # 2. BIAS TIMEFRAME (DAILY) INDICATORS
        # The 200 EMA on the Daily chart is the 'Golden Rule' of professional trading
        self.df_daily['ema200'] = self.df_daily['close'].ewm(span=200, adjust=False).mean()

    def check_signals(self):
        self.calculate_indicators()
        
        # Current data for H1
        row = self.df.iloc[-1]
        prev_row = self.df.iloc[-2]
        
        # Current data for Daily (Bias)
        daily_row = self.df_daily.iloc[-1]
        
        # --- UPGRADE 1: DIRECTIONAL BIAS (THE FILTER) ---
        # We only look for BUYS if the daily price is above the Daily 200 EMA
        is_daily_bullish = daily_row['close'] > daily_row['ema200']
        # We only look for SELLS if the daily price is below the Daily 200 EMA
        is_daily_bearish = daily_row['close'] < daily_row['ema200']

        # --- EXISTING CORE LOGIC ---
        # 1. H1 Trend (Price relative to 20 EMA)
        is_h1_uptrend = row['close'] > row['ema20']
        is_h1_downtrend = row['close'] < row['ema20']

        # 2. 38.2% Candle Pattern
        total_range = row['high'] - row['low']
        bullish_382 = (row['high'] - row['close']) / total_range < 0.382 if total_range > 0 else False
        bearish_382 = (row['close'] - row['low']) / total_range < 0.382 if total_range > 0 else False

        # 3. Engulfing Pattern
        bull_engulf = (row['close'] > prev_row['open']) and (prev_row['close'] < prev_row['open'])
        bear_engulf = (row['close'] < prev_row['open']) and (prev_row['close'] > prev_row['open'])

        # 4. Area of Value (Near EMA20)
        near_ema = abs(row['close'] - row['ema20']) < (row['atr'] * 1.2)

        # --- COMBINED SIGNAL LOGIC (THE MASTER CHECK) ---
        
        # BUY: Daily Trend is UP + H1 Trend is UP + Pattern + Location
        if is_daily_bullish and is_h1_uptrend and (bullish_382 or bull_engulf) and near_ema:
            return "BUY", row['close'], row['atr']
        
        # SELL: Daily Trend is DOWN + H1 Trend is DOWN + Pattern + Location
        if is_daily_bearish and is_h1_downtrend and (bearish_382 or bear_engulf) and near_ema:
            return "SELL", row['close'], row['atr']
            
        return None, None, None
