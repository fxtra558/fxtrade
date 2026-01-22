import pandas as pd
from oandapyV20 import API
import oandapyV20.endpoints.instruments as instruments

class DataProvider:
    def __init__(self, token):
        # We use 'practice' for Demo accounts
        self.client = API(access_token=token, environment="practice")

    def get_ohlc(self, symbol, granularity="H1", count=100):
        """
        Fetches professional OHLC data from OANDA
        Granularity: 'H1' (1hr), 'M15' (15min), etc.
        """
        params = {
            "count": count,
            "granularity": granularity,
            "price": "M" # Midpoint price
        }
        
        try:
            r = instruments.InstrumentsCandles(instrument=symbol, params=params)
            self.client.request(r)
            
            candles = r.response.get('candles', [])
            data = []
            
            for c in candles:
                if c['complete']:
                    data.append({
                        "time": c['time'],
                        "open": float(c['mid']['o']),
                        "high": float(c['mid']['h']),
                        "low": float(c['mid']['l']),
                        "close": float(c['mid']['c']),
                        "volume": int(c['volume'])
                    })
            
            df = pd.DataFrame(data)
            df['time'] = pd.to_datetime(df['time'])
            return df
        except Exception as e:
            print(f"OANDA API Error: {e}")
            return None
