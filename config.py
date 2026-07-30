import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

STARTING_BALANCE = float(os.getenv("STARTING_BALANCE", "1000"))
DEFAULT_STAKE_PCT = float(os.getenv("DEFAULT_STAKE_PCT", "0.05"))  # 5% per trade default

PRICE_CHECK_INTERVAL_SECONDS = int(os.getenv("PRICE_CHECK_INTERVAL_SECONDS", "30"))

PORTFOLIO_STATE_PATH = os.getenv("PORTFOLIO_STATE_PATH", "./portfolio_state.json")
