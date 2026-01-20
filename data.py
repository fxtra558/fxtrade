import yfinance as yf
import pandas as pd

class DataProvider:
    def get_ohlc(self, symbol="EURUSD=X", interval="1h"):
        # symbol for EURUSD in Yahoo Finance is 'EURUSD=X'
        data = yf.download(tickers=symbol, period="5d", interval=interval, progress=False)
        if data.empty:
            return None
        
        df = data.copy()
        # Clean column names
        df.columns = [col[0].lower() if isinstance(col, tuple) else col.lower() for col in df.columns]
        return df
