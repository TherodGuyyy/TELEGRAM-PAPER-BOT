"""
Core paper-trading engine — CORRECTED MODEL (v2):

ENTRY (this is where the "dip" logic actually belongs — corrected after
an earlier misunderstanding where I'd put dip-watching on the exit side
instead):
  1. You /enter a token the moment you see an alert you like — this
     creates a PENDING entry, NOT an immediate buy.
  2. The engine tracks the peak price since that alert moment.
  3. Once price falls to 55%+ below that peak (i.e. price <= peak * 0.45),
     the pending entry converts into an ACTUAL position, bought at that
     dipped price.
  4. If no such dip happens within ENTRY_TIMEOUT_MINUTES, enter anyway at
     whatever the current price is (default fallback — configurable).

EXIT (simplified — no dip-watching here anymore, that was the mistake):
  - Straightforward: sell at TAKE_PROFIT_MULTIPLE (2.2x) of your actual
    entry price. The 0.2 above 2.0x is a deliberate buffer for fees.
  - Hard cap at HARD_CAP_MULTIPLE (3x) — if price ever gets there before
    2.2x for some reason (shouldn't normally happen since 2.2 < 3, but
    kept as a safety ceiling), exit immediately.

IMPORTANT — same finding as before, still true: this rule has NO
stop-loss. If a position never reaches 2.2x and just bleeds down, it
stays open indefinitely. Still worth deciding on deliberately rather
than leaving unaddressed.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional


ENTRY_DIP_MIN_PCT = 0.05      # anything shallower than this isn't a real "dip" yet — keep waiting
ENTRY_DIP_MAX_PCT = 0.45      # anything deeper than this looks like a collapse, not a healthy
                               # pullback — abandon the watch rather than buy into a falling knife
ENTRY_TIMEOUT_MINUTES = 15    # enter anyway at current price if no dip by then
TAKE_PROFIT_MULTIPLE = 2.2    # sell at 2.2x entry (buffer for fees over a flat 2x)
HARD_CAP_MULTIPLE = 3.0       # absolute ceiling, sell immediately if ever reached
STOP_LOSS_MULTIPLE = 0.5      # sell if price falls to 50% of entry or below —
                               # fills the "no downside protection" gap found
                               # during testing


class ExitReason(Enum):
    TAKE_PROFIT_2_2X = "take_profit_2.2x"
    HARD_CAP_3X = "hard_cap_3x"
    STOP_LOSS_50PCT = "stop_loss_50pct"
    MANUAL = "manual"


class EntryReason(Enum):
    DIP_IN_RANGE = "dip_in_range"          # the healthy 5-45% pullback window
    TIMEOUT_FALLBACK = "timeout_fallback"
    MANUAL_IMMEDIATE = "manual_immediate"  # reserved for a future "just buy now" command


class WatchOutcome(Enum):
    ENTERED = "entered"
    ABANDONED_TOO_DEEP = "abandoned_too_deep"  # dipped past 45% — looked like a collapse, skipped


@dataclass
class PendingEntry:
    """Waiting for a dip in the healthy 5-45% window before actually buying."""
    token_address: str
    symbol: str
    stake_pct: float
    alert_time: datetime
    alert_price: float
    peak_price: float = field(init=False)

    def __post_init__(self):
        self.peak_price = self.alert_price

    def check_price(self, current_price: float, now: datetime = None):
        """
        Feed in the latest price. Returns one of:
          - (entry_price, EntryReason) if this should convert to a real position now
          - WatchOutcome.ABANDONED_TOO_DEEP if the dip blew past the safe window
            (caller should cancel this watch, not enter)
          - None if still waiting
        """
        now = now or datetime.now(timezone.utc)

        if current_price > self.peak_price:
            self.peak_price = current_price

        deep_floor = self.peak_price * (1 - ENTRY_DIP_MAX_PCT)   # 45% down — go below this = abandon
        shallow_ceiling = self.peak_price * (1 - ENTRY_DIP_MIN_PCT)  # 5% down — the "is this even a dip yet" line

        # Too deep FIRST — a collapse past 45% disqualifies this token
        # entirely, takes priority over anything else.
        if current_price < deep_floor * 0.9999999:
            return WatchOutcome.ABANDONED_TOO_DEEP

        # In the healthy 5-45% window?
        if current_price <= shallow_ceiling * 1.0000001:
            return current_price, EntryReason.DIP_IN_RANGE

        if now - self.alert_time >= timedelta(minutes=ENTRY_TIMEOUT_MINUTES):
            return current_price, EntryReason.TIMEOUT_FALLBACK

        return None


@dataclass
class Position:
    token_address: str
    symbol: str
    entry_price: float
    entry_reason: EntryReason
    stake: float
    entry_time: datetime
    closed: bool = field(default=False, init=False)
    exit_price: Optional[float] = field(default=None, init=False)
    exit_reason: Optional[ExitReason] = field(default=None, init=False)
    exit_time: Optional[datetime] = field(default=None, init=False)

    def update_price(self, current_price: float, now: datetime = None) -> Optional[ExitReason]:
        """Returns the ExitReason if this price update should trigger a
        close, else None. Does not close the position itself."""
        if self.closed:
            return None

        multiple_now = current_price / self.entry_price

        if multiple_now >= HARD_CAP_MULTIPLE * 0.9999999:
            return ExitReason.HARD_CAP_3X
        if multiple_now >= TAKE_PROFIT_MULTIPLE * 0.9999999:
            return ExitReason.TAKE_PROFIT_2_2X
        if multiple_now <= STOP_LOSS_MULTIPLE * 1.0000001:
            return ExitReason.STOP_LOSS_50PCT
        return None

    def close(self, exit_price: float, reason: ExitReason, now: datetime = None):
        self.closed = True
        self.exit_price = exit_price
        self.exit_reason = reason
        self.exit_time = now or datetime.now(timezone.utc)

    @property
    def pnl(self) -> float:
        if self.exit_price is None:
            return 0.0
        return self.stake * (self.exit_price / self.entry_price - 1.0)

    @property
    def realized_multiple(self) -> Optional[float]:
        if self.exit_price is None:
            return None
        return self.exit_price / self.entry_price


class PaperPortfolio:
    def __init__(self, starting_balance: float):
        self.balance = starting_balance
        self.starting_balance = starting_balance
        self.pending_entries: dict[str, PendingEntry] = {}
        self.open_positions: dict[str, Position] = {}
        self.closed_positions: list[Position] = []

    def start_watching(self, token_address: str, symbol: str, alert_price: float,
                        stake_pct: float, now: datetime = None) -> PendingEntry:
        """Called when you /enter — starts waiting for a dip, does NOT buy yet."""
        if token_address in self.pending_entries or token_address in self.open_positions:
            raise ValueError(f"Already watching or holding a position in {symbol}.")
        pending = PendingEntry(
            token_address=token_address, symbol=symbol, stake_pct=stake_pct,
            alert_time=now or datetime.now(timezone.utc), alert_price=alert_price,
        )
        self.pending_entries[token_address] = pending
        return pending

    def check_pending_entry(self, token_address: str, current_price: float,
                             now: datetime = None):
        """
        Feeds a price into a pending (not-yet-bought) entry.
        Returns:
          - a Position, if this triggered a real entry
          - WatchOutcome.ABANDONED_TOO_DEEP, if the dip blew past the safe
            window and the watch was cancelled (no position opened)
          - None, if still waiting
        """
        pending = self.pending_entries.get(token_address)
        if pending is None:
            return None

        result = pending.check_price(current_price, now)
        if result is None:
            return None

        if result == WatchOutcome.ABANDONED_TOO_DEEP:
            del self.pending_entries[token_address]
            return WatchOutcome.ABANDONED_TOO_DEEP

        entry_price, entry_reason = result
        stake = self.balance * pending.stake_pct
        if stake <= 0 or stake > self.balance:
            del self.pending_entries[token_address]
            return None

        position = Position(
            token_address=token_address, symbol=pending.symbol,
            entry_price=entry_price, entry_reason=entry_reason,
            stake=stake, entry_time=now or datetime.now(timezone.utc),
        )
        self.balance -= stake
        del self.pending_entries[token_address]
        self.open_positions[token_address] = position
        return position

    def check_open_position(self, token_address: str, current_price: float,
                             now: datetime = None) -> Optional[Position]:
        position = self.open_positions.get(token_address)
        if position is None:
            return None

        reason = position.update_price(current_price, now)
        if reason is not None:
            position.close(current_price, reason, now)
            self.balance += position.stake + position.pnl
            del self.open_positions[token_address]
            self.closed_positions.append(position)
            return position
        return None

    def force_close(self, token_address: str, current_price: float,
                     now: datetime = None) -> Optional[Position]:
        position = self.open_positions.get(token_address)
        if position is None:
            return None
        position.close(current_price, ExitReason.MANUAL, now)
        self.balance += position.stake + position.pnl
        del self.open_positions[token_address]
        self.closed_positions.append(position)
        return position

    def cancel_pending(self, token_address: str) -> bool:
        if token_address in self.pending_entries:
            del self.pending_entries[token_address]
            return True
        return False

    @property
    def total_equity(self) -> float:
        return self.balance + sum(p.stake for p in self.open_positions.values())
