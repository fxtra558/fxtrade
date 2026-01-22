import pandas as pd

class StevenStrategy:
    def __init__(self, df_h1, df_daily):
        self.df = df_h1
        self.df_daily = df_daily
        # --- RISK SETTINGS ---
        self.sl_atr_multiplier = 1.5  # Steven's "Breathing Room" rule
        self.reward_risk_ratio = 3.0  # One win = Three losses

    def calculate_indicators(self):
        # 1. Trend & Volatility
        self.df['ema20'] = self.df['close'].ewm(span=20, adjust=False).mean()
        high_low = self.df['high'] - self.df['low']
        high_cp = abs(self.df['high'] - self.df['close'].shift())
        low_cp = abs(self.df['low'] - self.df['close'].shift())
        self.df['atr'] = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1).rolling(14).mean()
        self.df['atr_sma'] = self.df['atr'].rolling(10).mean()

        # 2. Daily Bias
        self.df_daily['ema200'] = self.df_daily['close'].ewm(span=200, adjust=False).mean()

        # 3. Market Structure (Upgrade 3)
        self.df['recent_low'] = self.df['low'].rolling(10).min()
        self.df['recent_high'] = self.df['high'].rolling(10).max()
        self.df['prev_swing_low'] = self.df['low'].shift(10).rolling(10).min()
        self.df['prev_swing_high'] = self.df['high'].shift(10).rolling(10).max()

    def check_signals(self):
        self.calculate_indicators()
        row = self.df.iloc[-1]
        daily_row = self.df_daily.iloc[-1]
        prev_row = self.df.iloc[-2]

        # --- FILTERS ---
        is_daily_bullish = daily_row['close'] > daily_row['ema200']
        is_daily_bearish = daily_row['close'] < daily_row['ema200']
        is_vol_expanding = row['atr'] > row['atr_sma']
        
        # --- STRUCTURE ---
        has_bull_structure = row['recent_low'] > row['prev_swing_low']
        has_bear_structure = row['recent_high'] < row['prev_swing_high']

        # --- PATTERNS ---
        total_range = row['high'] - row['low']
        bullish_382 = (row['high'] - row['close']) / total_range < 0.382 if total_range > 0 else False
        bearish_382 = (row['close'] - row['low']) / total_range < 0.382 if total_range > 0 else False
        bull_engulf = (row['close'] > prev_row['open']) and (prev_row['close'] < prev_row['open'])
        bear_engulf = (row['close'] < prev_row['open']) and (prev_row['close'] > prev_row['open'])

        # --- FINAL LOGIC & RISK MATH (UPGRADE 4) ---
        price = float(row['close'])
        atr = float(row['atr'])

        # BUY SIGNAL
        if is_daily_bullish and is_vol_expanding and has_bull_structure:
            if (bullish_382 or bull_engulf) and abs(price - row['ema20']) < (atr * 1.5):
                sl = price - (atr * self.sl_atr_multiplier)
                tp = price + ((price - sl) * self.reward_risk_ratio)
                return "BUY", price, sl, tp

        # SELL SIGNAL
        if is_daily_bearish and is_vol_expanding and has_bear_structure:
            if (bearish_382 or bear_engulf) and abs(price - row['ema20']) < (atr * 1.5):
                sl = price + (atr * self.sl_atr_multiplier)
                tp = price - ((sl - price) * self.reward_risk_ratio)
                return "SELL", price, sl, tp

        return None, None, None, None
