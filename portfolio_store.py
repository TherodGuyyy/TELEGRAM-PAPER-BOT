"""
Saves/loads the paper portfolio to a JSON file, so restarting the bot
doesn't lose your pending entries, open positions, or history.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from paper_engine import PaperPortfolio, Position, PendingEntry, ExitReason, EntryReason

log = logging.getLogger("portfolio_store")


def _position_to_dict(p: Position) -> dict:
    return {
        "token_address": p.token_address, "symbol": p.symbol,
        "entry_price": p.entry_price,
        "entry_reason": p.entry_reason.value,
        "stake": p.stake,
        "entry_time": p.entry_time.isoformat(),
        "closed": p.closed,
        "exit_price": p.exit_price,
        "exit_reason": p.exit_reason.value if p.exit_reason else None,
        "exit_time": p.exit_time.isoformat() if p.exit_time else None,
    }


def _position_from_dict(d: dict) -> Position:
    p = Position(
        token_address=d["token_address"], symbol=d["symbol"],
        entry_price=d["entry_price"],
        entry_reason=EntryReason(d["entry_reason"]),
        stake=d["stake"],
        entry_time=datetime.fromisoformat(d["entry_time"]),
    )
    p.closed = d["closed"]
    p.exit_price = d["exit_price"]
    p.exit_reason = ExitReason(d["exit_reason"]) if d["exit_reason"] else None
    p.exit_time = datetime.fromisoformat(d["exit_time"]) if d["exit_time"] else None
    return p


def _pending_to_dict(p: PendingEntry) -> dict:
    return {
        "token_address": p.token_address, "symbol": p.symbol,
        "stake_pct": p.stake_pct,
        "alert_time": p.alert_time.isoformat(),
        "alert_price": p.alert_price,
        "peak_price": p.peak_price,
    }


def _pending_from_dict(d: dict) -> PendingEntry:
    p = PendingEntry(
        token_address=d["token_address"], symbol=d["symbol"],
        stake_pct=d["stake_pct"],
        alert_time=datetime.fromisoformat(d["alert_time"]),
        alert_price=d["alert_price"],
    )
    p.peak_price = d["peak_price"]
    return p


def save_portfolio(portfolio: PaperPortfolio, path: str) -> None:
    data = {
        "balance": portfolio.balance,
        "starting_balance": portfolio.starting_balance,
        "pending_entries": {k: _pending_to_dict(v) for k, v in portfolio.pending_entries.items()},
        "open_positions": {k: _position_to_dict(v) for k, v in portfolio.open_positions.items()},
        "closed_positions": [_position_to_dict(p) for p in portfolio.closed_positions],
    }
    Path(path).write_text(json.dumps(data, indent=2))


def load_portfolio(path: str, default_starting_balance: float) -> PaperPortfolio:
    p = Path(path)
    if not p.exists():
        return PaperPortfolio(starting_balance=default_starting_balance)

    try:
        data = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Couldn't read portfolio state (%s) — starting fresh.", e)
        return PaperPortfolio(starting_balance=default_starting_balance)

    portfolio = PaperPortfolio(starting_balance=data["starting_balance"])
    portfolio.balance = data["balance"]
    portfolio.pending_entries = {
        k: _pending_from_dict(v) for k, v in data.get("pending_entries", {}).items()
    }
    portfolio.open_positions = {k: _position_from_dict(v) for k, v in data["open_positions"].items()}
    portfolio.closed_positions = [_position_from_dict(v) for v in data["closed_positions"]]
    return portfolio
