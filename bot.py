import os
from flask import Flask
from upstash_redis import Redis
import yfinance as yf
import pandas as pd
from strategy import StevenStrategy

app = Flask(__name__)

# --- SECURE CONNECTION TO DATABASE ---
# This pulls the "Secrets" you just saved on Render
REDIS_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")

# Initialize Redis connection
redis = Redis(url=REDIS_URL, token=REDIS_TOKEN)

# Popular Pairs to Scan (Top Forex Pairs)
SYMBOLS = ["EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X", "USDCAD=X"]

# Ensure balance exists in the database
if not redis.exists("balance"):
    redis.set("balance", 10000.0)
