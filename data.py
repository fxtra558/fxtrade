import ccxt
import pandas as pd

class DataProvider:
    def __init__(self, api_key, secret):
        """Initializes the Bitunix exchange connection via CCXT"""
        self.exchange = ccxt.bitunix({
            'apiKey': api_key,
            'secret': secret,
            'enableRateLimit': True,
        })
        
        # NOTE: If your API key is for a 'Demo/Practice' account, 
        # CCXT usually routes it correctly, but ensure your keys 
        # were generated in the Bitunix 'Demo Trading' section.

    def get_ohlc(self, symbol, timeframe="1h", limit=150):
        """Fetches high-quality candle data directly from Bitunix"""
        try:
            # Bitunix symbols are formatted like 'BTC/USDT'
            bars = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            df = pd.DataFrame(bars, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
            df['time'] = pd.to_datetime(df['time'], unit='ms')
            
            # Ensure all columns are lowercase for strategy compatibility
            df.columns = [str(col).lower() for col in df.columns]
            return df
        except Exception as e:
            print(f"Bitunix Data Error for {symbol}: {e}")
            return None

    def get_live_tick(self, symbol):
        """Gets the exact current price sitting on the order book"""
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            # We use the 'last' price (most recent trade)
            return float(ticker['last'])
        except Exception as e:
            print(f"Bitunix Ticker Error for {symbol}: {e}")
            return None

    def place_market_order(self, symbol, side, amount):
        """Executes a REAL market order on Bitunix"""
        try:
            # side must be 'buy' or 'sell'
            order = self.exchange.create_order(
                symbol=symbol,
                type='market',
                side=side.lower(),
                amount=amount
            )
            return order
        except Exception as e:
            print(f"Bitunix Order Rejection: {e}")
            return None

    def close_position(self, symbol, side, amount):
        """Closes an open position by placing an opposite order"""
        try:
            opposite_side = 'sell' if side.upper() == 'BUY' else 'buy'
            return self.place_market_order(symbol, opposite_side, amount)
        except:
            return None
