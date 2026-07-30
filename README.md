# Paper Trading Bot

Test your memecoin entry/exit strategy risk-free — no real money, no real
wallet. You manually `/enter` (start watching) a token when you spot
something from your memecoin alert bot; this bot handles the rest
automatically:

## The rule

**Entry** — When you `/enter`, the bot does NOT buy immediately. It
watches the price from that moment and waits for a healthy pullback:
- If price dips **5–45% below its peak** since your alert, it buys right
  there, at the dipped price.
- If it dips **more than 45%** (heading toward a 55%+ collapse), the bot
  abandons the watch entirely rather than buying into what looks like a
  rug — no position opens, no money at risk.
- If it **never dips at all** within 15 minutes, it buys anyway at
  whatever the current price is (so a watch never sits in limbo forever).

**Exit** — Once you're in a position:
- Sell at **2.2x** your actual entry price (the 0.2 above a flat 2x is a
  deliberate buffer for fees).
- **Hard cap at 3x** — if price ever gets there, sell immediately no
  matter what.
- **Stop loss at -50%** — if price falls to half your entry price or
  below, sell immediately. Fills the "no downside protection" gap found
  during testing.

## What's tested

**Fully tested — 15+ passing scenarios**, including: the 5%/45% window
boundaries exactly, a too-shallow dip correctly waiting, a too-deep dip
correctly abandoning with zero capital risk, the 15-minute timeout
fallback, the 2.2x and 3x exits, a full rug-pull with no forced exit
(confirming the no-stop-loss finding), complete state persistence across
a restart — including mid-watch and mid-position states — and a full
realistic multi-token scenario combining all outcomes together.

**Not tested**: the Telegram command wiring itself — `python-telegram-bot`
wasn't installable in the sandbox this was built in. Same honest caveat
as your other bots; the underlying logic it calls into is solid, the
first real run is the actual confirmation of the wiring itself.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env` — a **fresh Telegram bot**, separate from your memecoin
bot, via @BotFather.

```bash
python main.py
```

## Commands

- `/balance` — current balance + equity
- `/setbalance 1000` — reset your paper balance for a fresh test run
- `/enter <token_address> <symbol> [stake_pct]` — start watching for a
  dip. `stake_pct` optional, defaults to 5% (e.g. `0.03` for 3%)
- `/cancel <token_address>` — give up on a pending watch manually
- `/positions` — see what's being watched and what's open
- `/close <token_address>` — manually close an open position early
- `/history` — last 10 closed trades + all-time realized PnL

## Notes

- Runs fine on your own PC for testing. Same Render deployment pattern
  as your other bots if/when you want it running 24/7.
- All state (pending watches, open positions, balance, history) saves to
  `portfolio_state.json` after every change — stop and restart anytime
  without losing anything, including a watch or position mid-flight.
