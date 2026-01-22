import pandas as pd
from oandapyV20 import API
import oandapyV20.endpoints.instruments as instruments
import oandapyV20.endpoints.orders as orders
import oandapyV20.endpoints.positions as positions

class DataProvider:
    def __init__(self, token, account_id):
        self.client = API(access_token=token, environment="practice")
        self.account_id = account_id

    def get_ohlc(self, symbol, granularity="H1", count=100):
        params = {"count": count, "granularity": granularity, "price": "M"}
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
                        "close": float(c['mid']['c'])
                    })
            return pd.DataFrame(data)
        except: return None

    def is_position_open(self, symbol):
        """Checks OANDA to see if we already have a trade open for this symbol"""
        try:
            r = positions.PositionDetails(accountID=self.account_id, instrument=symbol)
            self.client.request(r)
            # If long or short units are not 0, position is open
            pos = r.response.get('position', {})
            return abs(float(pos.get('long', {}).get('units', 0))) > 0 or \
                   abs(float(pos.get('short', {}).get('units', 0))) > 0
        except:
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
            return r.response
        except: return None
