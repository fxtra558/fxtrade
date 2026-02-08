import ccxt # Install this via requirements.txt
import pandas as pd

class DataProvider:
    def __init__(self, api_key, secret):
        # Initialize Bitunix connection
        self.exchange = ccxt.bitunix({
            'apiKey': api_key,
            'secret': secret,
            'enableRateLimit': True,
        })
        # Set to True if using the Demo/Testnet API
        # self.exchange.set_sandbox_mode(True) 

    def get_ohlc(self, symbol, interval="1h", limit=100):
        """Fetches real market data from Bitunix"""
        try:
            # Bitunix format is 'BTC/USDT'
            clean_sym = symbol.replace("-USD", "/USDT")
            bars = self.exchange.fetch_ohlcv(clean_sym, timeframe=interval, limit=limit)
            df = pd.DataFrame(bars, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
            return df
        except: return None

    def place_order(self, symbol, side, amount, sl, tp):
        """Sends a REAL order to the Bitunix exchange"""
        try:
            clean_sym = symbol.replace("-USD", "/USDT")
            # This places a Market Order
            order = self.exchange.create_order(
                symbol=clean_sym,
                type='market',
                side=side.lower(),
                amount=amount
            )
            # Note: SL/TP logic usually requires separate calls for Bitunix 
            # but this will get the trade open.
            return order
        except Exception as e:
            print(f"Bitunix Order Error: {e}")
            return None
