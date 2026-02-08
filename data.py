import yfinance as yf
import pandas as pd

class DataProvider:
    def get_ohlc(self, symbol, interval="1h", period="5d"):
        """
        Fetches live Crypto data from Yahoo Finance.
        Symbols: BTC-USD, ETH-USD, SOL-USD, etc.
        """
        try:
            # interval='1h' for H1 strategy, '1d' for Daily Bias
            df = yf.download(tickers=symbol, period=period, interval=interval, progress=False)
            if df.empty: return None
            
            # Fix Yahoo Finance's new data format
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            df.columns = [str(col).lower() for col in df.columns]
            return df
        except Exception as e:
            print(f"Data Fetch Error for {symbol}: {e}")
            return None

    def get_live_tick(self, symbol):
        """Gets the most recent price point instantly"""
        try:
            # Fetch 1-minute data to get the absolute latest price
            df = yf.download(tickers=symbol, period="1d", interval="1m", progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return float(df['Close'].iloc[-1])
        except:
            return None
