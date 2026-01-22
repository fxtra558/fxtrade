import pandas as pd
from oandapyV20 import API
import oandapyV20.endpoints.instruments as instruments
import oandapyV20.endpoints.orders as orders

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
                data.append({
                    "time": c['time'],
                    "open": float(c['mid']['o']),
                    "high": float(c['mid']['h']),
                    "low": float(c['mid']['l']),
                    "close": float(c['mid']['c'])
                })
            return pd.DataFrame(data)
        except: return None

    def place_market_order(self, symbol, side, units, sl, tp):
        """Sends a real trade to the OANDA Demo Broker"""
        # Units must be negative for SELL
        order_units = str(units) if side == "BUY" else str(-units)
        
        data = {
            "order": {
                "price": "",
                "stopLossOnFill": {"timeInForce": "GTC", "price": str(round(sl, 5))},
                "takeProfitOnFill": {"timeInForce": "GTC", "price": str(round(tp, 5))},
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
        except Exception as e:
            print(f"OANDA Order Error: {e}")
            return None
