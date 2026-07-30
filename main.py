"""
Paper trading bot — entry point.

Every PRICE_CHECK_INTERVAL_SECONDS, checks:
  1. Pending watches — did the price dip into the healthy 5-45% window
     (enter now), blow past 45% (abandon, looks like a collapse), or
     time out with no dip at all (enter anyway)?
  2. Open positions — did price hit 2.2x (take profit) or 3x (hard cap)?

You control entry timing by choosing which alerts to /enter — the bot
handles both the dip-entry and the exit automatically from there.

Run with: python main.py
"""

import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram.ext import ContextTypes

import config
import telegram_bot
from paper_engine import WatchOutcome
from price_source import get_current_price

log = logging.getLogger("main")


# ─── KEEP-ALIVE WEB SERVER (for Render's free tier) ────────────────────────
# Render's free "Web Service" tier requires binding to a port — this tiny
# server just responds 200 OK to anything, so an external pinger (e.g.
# UptimeRobot) can keep the service from spinning down. Same pattern as
# your memecoin bot. Runs in a background thread; the actual bot logic
# below is unaffected by this.

class _KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Paper trading bot is alive")

    def log_message(self, format, *args):
        pass  # silence default request logging, keeps the real logs readable


def _start_keep_alive_server():
    port = int(os.getenv("PORT", 8080))  # Render sets PORT automatically
    server = HTTPServer(("0.0.0.0", port), _KeepAliveHandler)
    log.info("Keep-alive web server listening on port %d", port)
    server.serve_forever()


async def check_positions_job(context: ContextTypes.DEFAULT_TYPE):
    portfolio = telegram_bot.portfolio

    # --- Check pending watches (waiting for a dip to actually enter) ---
    for token_address in list(portfolio.pending_entries.keys()):
        price = get_current_price(token_address)
        if price is None:
            continue

        symbol = portfolio.pending_entries[token_address].symbol
        result = portfolio.check_pending_entry(token_address, price)

        if result is None:
            continue

        telegram_bot._persist()

        if result == WatchOutcome.ABANDONED_TOO_DEEP:
            await _notify(context, f"⚠️ {symbol}: dipped past 45% — looked like a "
                                    f"collapse, not a healthy pullback. Skipped, no position opened.")
        else:
            position = result
            reason_text = "post-alert dip" if position.entry_reason.value == "dip_in_range" else "15-min timeout (never dipped)"
            await _notify(context, f"✅ Entered {symbol} at {position.entry_price:.8f} ({reason_text})\n"
                                    f"Stake: {position.stake:,.2f} | Balance: {portfolio.balance:,.2f}")

    # --- Check open positions (waiting for 2.2x or 3x) ---
    for token_address in list(portfolio.open_positions.keys()):
        price = get_current_price(token_address)
        if price is None:
            continue

        closed_position = portfolio.check_open_position(token_address, price)
        if closed_position is not None:
            telegram_bot._persist()
            message = telegram_bot._format_close_message(closed_position)
            await _notify(context, f"🤖 Auto-exit triggered\n\n{message}")


async def _notify(context: ContextTypes.DEFAULT_TYPE, text: str):
    try:
        await context.bot.send_message(chat_id=config.TELEGRAM_CHAT_ID, text=text)
    except Exception as e:
        log.error("Failed to send notification: %s", e)


def main():
    # Start the keep-alive server in the background (only matters when
    # deployed to Render — harmless when just running locally).
    threading.Thread(target=_start_keep_alive_server, daemon=True).start()

    app = telegram_bot.build_app()
    app.job_queue.run_repeating(
        check_positions_job,
        interval=config.PRICE_CHECK_INTERVAL_SECONDS,
        first=config.PRICE_CHECK_INTERVAL_SECONDS,
    )
    log.info(
        "Paper trading bot starting. Balance=%.2f, checking prices every %ds",
        telegram_bot.portfolio.balance, config.PRICE_CHECK_INTERVAL_SECONDS,
    )
    app.run_polling()


if __name__ == "__main__":
    main()
