import pandas as pd
from oandapyV20 import API
import oandapyV20.endpoints.instruments as instruments

class DataProvider:
    def __init__(self, access_token):
        self.client = API(access_token=access_token)

    def get_ohlc(self, symbol, count=200, granularity="H1"):
        params = {"count": count, "granularity": granularity}
        r = instruments.InstrumentsCandles(instrument=symbol, params=params)
        self.client.request(r)
        
        data = []
        for candle in r.response['candles']:
            if candle['complete']:
                data.append({
                    'time': candle['time'],
                    'open': float(candle['mid']['o']),
                    'high': float(candle['mid']['h']),
                    'low': float(candle['mid']['l']),
                    'close': float(candle['mid']['c']),
                })
        
        df = pd.DataFrame(data)
        df['time'] = pd.to_datetime(df['time'])
        return df
