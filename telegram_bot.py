"""
Telegram commands for the paper trading bot.

/start              - check access, show help
/balance             - show current balance + equity
/setbalance <amt>    - reset your paper balance (e.g. to start a fresh test run)
/enter <address> <symbol> [stake_pct]
                     - paper-buy a token at its current live price.
                       stake_pct is optional, defaults to DEFAULT_STAKE_PCT
                       (e.g. 0.05 = 5% of current balance).
/positions           - list open positions with live multiple
/close <address>     - manually force-close a position right now
/history             - show your last several closed trades (PnL summary)

NOTE ON TESTING: python-telegram-bot could not be installed/run in the
sandbox this was built in (no network access there) — same honest
limitation as your other bots. The core logic this calls into
(paper_engine.py, portfolio_store.py, price_source.py) IS fully tested;
this file's job is just wiring those into Telegram commands using the
same well-documented, stable API pattern as your other bots.
"""

import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

import config
from paper_engine import PaperPortfolio, ExitReason
from portfolio_store import save_portfolio, load_portfolio
from price_source import get_current_price, get_token_info

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("telegram_bot")

portfolio: PaperPortfolio = load_portfolio(config.PORTFOLIO_STATE_PATH, config.STARTING_BALANCE)


def _persist():
    save_portfolio(portfolio, config.PORTFOLIO_STATE_PATH)


def _is_allowed(update: Update) -> bool:
    return str(update.effective_chat.id) == str(config.TELEGRAM_CHAT_ID)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        await update.message.reply_text("Not authorized.")
        return
    await update.message.reply_text(
        "Paper trading bot ready. No real money moves here — this is for "
        "testing your strategy risk-free.\n\n"
        "/balance — current balance\n"
        "/addbalance <amount> — top up funds, keeps positions/history\n"
        "/setbalance <amount> — full reset, WIPES positions/history too\n"
        "/enter <token_address> [symbol] [stake_pct] — paper-buy, symbol "
        "auto-detected if you skip it (e.g. /enter <address> or "
        "/enter <address> 0.03 for 3% stake, or /enter <address> DOGE2 0.03)\n"
        "/positions — see open positions\n"
        "/close <token_address> — manually close early\n"
        "/history — recent closed trades"
    )


async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    await update.message.reply_text(
        f"Balance: ${portfolio.balance:,.2f}\n"
        f"Open positions: {len(portfolio.open_positions)}\n"
        f"Total equity (balance + stake locked in open trades): ${portfolio.total_equity:,.2f}"
    )


async def addbalance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /addbalance 500")
        return
    try:
        amount = float(context.args[0])
    except ValueError:
        await update.message.reply_text("That doesn't look like a number.")
        return
    portfolio.balance += amount
    _persist()
    await update.message.reply_text(
        f"Added ${amount:,.2f}. New balance: ${portfolio.balance:,.2f}\n"
        f"(Open positions and trade history untouched.)"
    )


async def setbalance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /setbalance 1000")
        return
    try:
        amount = float(context.args[0])
    except ValueError:
        await update.message.reply_text("That doesn't look like a number.")
        return
    global portfolio
    portfolio = PaperPortfolio(starting_balance=amount)
    _persist()
    await update.message.reply_text(f"Paper balance reset to ${amount:,.2f}. All open/closed history cleared.")


async def enter_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /enter <token_address> [symbol] [stake_pct]")
        return

    token_address = context.args[0]

    # symbol is now optional — auto-detected from DEXScreener if you don't
    # type one. If your second argument looks like a number, treat it as
    # stake_pct instead of a symbol (handles "/enter <address> 0.05").
    remaining = context.args[1:]
    manual_symbol = None
    stake_pct = config.DEFAULT_STAKE_PCT

    if remaining:
        first = remaining[0]
        try:
            stake_pct = float(first)
            remaining = remaining[1:]
        except ValueError:
            manual_symbol = first
            remaining = remaining[1:]
            if remaining:
                try:
                    stake_pct = float(remaining[0])
                except ValueError:
                    pass

    if token_address in portfolio.open_positions or token_address in portfolio.pending_entries:
        await update.message.reply_text("Already watching or holding a position in that token.")
        return

    info = get_token_info(token_address)
    if info is None:
        await update.message.reply_text("Couldn't fetch live data for that token right now — try again shortly.")
        return

    symbol = manual_symbol or info["symbol"]
    price = info["price"]

    try:
        portfolio.start_watching(token_address, symbol, price, stake_pct)
    except ValueError as e:
        await update.message.reply_text(f"Couldn't start watching: {e}")
        return

    _persist()
    await update.message.reply_text(
        f"Watching {symbol} — alert price {price:.8f}\n"
        f"Waiting for a 5-45% pullback from peak to actually enter "
        f"(will enter anyway after 15 min if it never dips).\n"
        f"Planned stake: {stake_pct*100:.1f}% of balance when triggered."
    )


async def positions_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    if not portfolio.pending_entries and not portfolio.open_positions:
        await update.message.reply_text("Nothing being watched and no open positions.")
        return

    lines = []
    if portfolio.pending_entries:
        lines.append("Watching for a dip:")
        for addr, pending in portfolio.pending_entries.items():
            price = get_current_price(addr)
            if price is None:
                lines.append(f"  {pending.symbol}: price unavailable right now")
                continue
            pct_from_peak = (1 - price / pending.peak_price) * 100
            lines.append(f"  {pending.symbol}: {pct_from_peak:.1f}% below peak (need 5-45% to enter)")
        lines.append("")

    if portfolio.open_positions:
        lines.append("Open positions:")
        for addr, pos in portfolio.open_positions.items():
            price = get_current_price(addr)
            if price is None:
                lines.append(f"  {pos.symbol}: price unavailable right now")
                continue
            multiple = price / pos.entry_price
            lines.append(f"  {pos.symbol}: {multiple:.2f}x now (target 2.2x, cap 3x)")

    await update.message.reply_text("\n".join(lines))


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /cancel <token_address>")
        return
    cancelled = portfolio.cancel_pending(context.args[0])
    _persist()
    await update.message.reply_text("Cancelled." if cancelled else "Nothing pending for that address.")


async def close_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /close <token_address>")
        return
    token_address = context.args[0]
    price = get_current_price(token_address)
    if price is None:
        await update.message.reply_text("Couldn't fetch a live price to close at right now.")
        return

    position = portfolio.force_close(token_address, price)
    if position is None:
        await update.message.reply_text("No open position found for that address.")
        return

    _persist()
    await update.message.reply_text(_format_close_message(position))


def _format_close_message(position) -> str:
    emoji = "🟢" if position.pnl >= 0 else "🔴"
    return (
        f"{emoji} Closed {position.symbol}\n"
        f"Entry: {position.entry_price:.8f}  →  Exit: {position.exit_price:.8f}\n"
        f"Result: {position.realized_multiple:.2f}x  ({position.exit_reason.value})\n"
        f"PnL: ${position.pnl:+,.2f}  |  Balance: ${portfolio.balance:,.2f}"
    )


async def history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    if not portfolio.closed_positions:
        await update.message.reply_text("No closed trades yet.")
        return
    recent = portfolio.closed_positions[-10:]
    lines = ["Recent closed trades:"]
    for p in recent:
        emoji = "🟢" if p.pnl >= 0 else "🔴"
        lines.append(f"  {emoji} {p.symbol}: {p.realized_multiple:.2f}x, PnL ${p.pnl:+,.2f} ({p.exit_reason.value})")
    total_pnl = sum(p.pnl for p in portfolio.closed_positions)
    lines.append(f"\nAll-time realized PnL: ${total_pnl:+,.2f}")
    await update.message.reply_text("\n".join(lines))


def build_app() -> Application:
    if not config.TELEGRAM_BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set in .env")
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", balance_cmd))
    app.add_handler(CommandHandler("addbalance", addbalance_cmd))
    app.add_handler(CommandHandler("setbalance", setbalance_cmd))
    app.add_handler(CommandHandler("enter", enter_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CommandHandler("positions", positions_cmd))
    app.add_handler(CommandHandler("close", close_cmd))
    app.add_handler(CommandHandler("history", history_cmd))
    return app
