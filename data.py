import pandas as pd
from oandapyV20 import API
import oandapyV20.endpoints.instruments as instruments
import oandapyV20.endpoints.orders as orders
import oandapyV20.endpoints.positions as positions
import oandapyV20.endpoints.pricing as pricing # New import for real-time ticks

class DataProvider:
    def __init__(self, token, account_id):
        self.client = API(access_token=token, environment="practice")
        self.account_id = account_id

    def get_ohlc(self, symbol, granularity="H1", count=100):
        """Used for Strategy analysis (Historical candles)"""
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

    def get_live_tick(self, symbol):
        """
        NEW: This gets the actual pulsing price from the market.
        It does not wait for a candle to finish. 
        It returns the 'Mid' price (average of buy and sell).
        """
        params = {"instruments": symbol}
        try:
            r = pricing.PricingInfo(accountID=self.account_id, params=params)
            self.client.request(r)
            # Fetch the first price info in the list
            price_data = r.response.get('prices', [{}])[0]
            bid = float(price_data.get('bids', [{}])[0].get('price'))
            ask = float(price_data.get('asks', [{}])[0].get('price'))
            return (bid + ask) / 2
        except Exception as e:
            print(f"Tick Fetch Error for {symbol}: {e}")
            return None

    def is_position_open(self, symbol):
        try:
            r = positions.PositionDetails(accountID=self.account_id, instrument=symbol)
            self.client.request(r)
            pos = r.response.get('position', {})
            return abs(float(pos.get('long', {}).get('units', 0))) > 0 or \
                   abs(float(pos.get('short', {}).get('units', 0))) > 0
        except: return False

    def get_all_open_positions(self):
        try:
            r = positions.OpenPositions(accountID=self.account_id)
            self.client.request(r)
            return [p['instrument'] for p in r.response.get('positions', [])]
        except: return []

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
