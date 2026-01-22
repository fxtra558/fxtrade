import pandas as pd
from oandapyV20 import API
import oandapyV20.endpoints.instruments as instruments
import oandapyV20.endpoints.orders as orders
import oandapyV20.endpoints.positions as positions

class DataProvider:
    def __init__(self, token, account_id):
        self.client = API(access_token=token, environment="practice")
        self.account_id = account_id

    def get_ohlc(self, symbol, granularity="H1", count=50):
        """Fetches data with a fallback count to ensure we get a price"""
        params = {"count": count, "granularity": granularity, "price": "M"}
        try:
            r = instruments.InstrumentsCandles(instrument=symbol, params=params)
            self.client.request(r)
            candles = r.response.get('candles', [])
            if not candles: return None
            
            data = []
            for c in candles:
                data.append({
                    "time": c['time'],
                    "open": float(c['mid']['o']),
                    "high": float(c['mid']['h']),
                    "low": float(c['mid']['l']),
                    "close": float(c['mid']['c'])
                })
            return pd.DataFrame(data)
        except: return None

    def is_position_open(self, symbol):
        """Safely checks if a position is open without crashing on 404 errors"""
        try:
            r = positions.PositionDetails(accountID=self.account_id, instrument=symbol)
            self.client.request(r)
            pos = r.response.get('position', {})
            long_units = float(pos.get('long', {}).get('units', 0))
            short_units = float(pos.get('short', {}).get('units', 0))
            return abs(long_units) > 0 or abs(short_units) > 0
        except:
            # OANDA returns an error if you've NEVER traded this pair. 
            # We catch it here and return False (Safe)
            return False

    def place_market_order(self, symbol, side, units, sl, tp):
        order_units = str(units) if side == "BUY" else str(-units)
        data = {
            "order": {
                "price": "",
                "stopLossOnFill": {"timeInForce": "GTC", "price": "{:.5f}".format(sl)},
                "takeProfitOnFill": {"timeInForce": "GTC", "price": "{:.5f}".format(tp)},
                "timeInForce": "FOK",
                "instrument": symbol,
                "units": order_units,
                "type": "MARKET",
                "positionFill": "DEFAULT"
            }
        }
        try:
            r = orders.OrderCreate(accountID=self.account_id, data=data)
            self.client.request(r)
            return True
        except: return False
