import pandas as pd
from oandapyV20 import API
import oandapyV20.endpoints.instruments as instruments
import oandapyV20.endpoints.orders as orders
import oandapyV20.endpoints.positions as positions

class DataProvider:
    def __init__(self, token, account_id):
        # We use 'practice' for Demo accounts. 
        # For a live account, this would change to 'live'.
        self.client = API(access_token=token, environment="practice")
        self.account_id = account_id

    def get_ohlc(self, symbol, granularity="H1", count=50):
        """Fetches historical candle data (Open, High, Low, Close)"""
        params = {
            "count": count, 
            "granularity": granularity, 
            "price": "M"  # Midpoint price
        }
        try:
            r = instruments.InstrumentsCandles(instrument=symbol, params=params)
            self.client.request(r)
            candles = r.response.get('candles', [])
            
            if not candles:
                return None
            
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
        except Exception as e:
            print(f"OANDA Data Error for {symbol}: {e}")
            return None

    def is_position_open(self, symbol):
        """Checks if a specific symbol currently has a live trade"""
        try:
            r = positions.PositionDetails(accountID=self.account_id, instrument=symbol)
            self.client.request(r)
            pos = r.response.get('position', {})
            # A position is open if either long or short units are non-zero
            long_units = float(pos.get('long', {}).get('units', 0))
            short_units = float(pos.get('short', {}).get('units', 0))
            return abs(long_units) > 0 or abs(short_units) > 0
        except:
            # OANDA returns a 404 if the pair has never been traded.
            # We catch that here and return False safely.
            return False

    def get_all_open_positions(self):
        """Returns a list of all symbols currently being traded on OANDA"""
        try:
            r = positions.OpenPositions(accountID=self.account_id)
            self.client.request(r)
            pos_data = r.response.get('positions', [])
            # Extract just the instrument names (e.g. ['EUR_USD', 'GBP_USD'])
            return [p['instrument'] for p in pos_data]
        except Exception as e:
            print(f"Position Sync Error: {e}")
            return []

    def place_market_order(self, symbol, side, units, sl, tp):
        """Executes a real trade on the OANDA Demo account"""
        # Units must be positive for BUY and negative for SELL
        order_units = str(units) if side == "BUY" else str(-units)
        
        # OANDA requires SL and TP to be strings with exactly 5 decimal places
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
            # If the broker accepts the order, return True
            return True
        except Exception as e:
            print(f"OANDA Order Refused: {e}")
            return False
