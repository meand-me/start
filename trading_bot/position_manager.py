"""Position manager: tracks entries, sizes, TP/SL state."""

import logging
from dataclasses import dataclass, field

from trading_bot.config import MAX_POSITION_RATIO, TOTAL_CAPITAL, TP3_RATIO
from trading_bot.strategy import EntryType

logger = logging.getLogger(__name__)


@dataclass
class Entry:
    entry_type: EntryType
    side: str  # "long" or "short"
    size_usdt: float
    entry_price: float
    stop_loss_price: float
    qty: float = 0.0


@dataclass
class PositionState:
    """Tracks the current composite position."""
    entries: list[Entry] = field(default_factory=list)
    total_invested_usdt: float = 0.0
    avg_entry_price: float = 0.0
    side: str | None = None
    total_qty: float = 0.0

    # TP tracking
    tp1_done: bool = False
    tp2_done: bool = False
    tp3_pending: bool = False  # waiting for user response on TP3

    # TP3 timeout tracking
    tp3_notified: bool = False

    def is_open(self) -> bool:
        return self.total_qty > 0

    def position_ratio(self) -> float:
        """Current position as ratio of total capital."""
        if TOTAL_CAPITAL <= 0:
            return 0
        return self.total_invested_usdt / TOTAL_CAPITAL

    def can_add(self, ratio: float) -> bool:
        """Check if adding this ratio would exceed max position."""
        return (self.position_ratio() + ratio) <= MAX_POSITION_RATIO

    def reset(self):
        self.entries.clear()
        self.total_invested_usdt = 0.0
        self.avg_entry_price = 0.0
        self.side = None
        self.total_qty = 0.0
        self.tp1_done = False
        self.tp2_done = False
        self.tp3_pending = False
        self.tp3_notified = False


class PositionManager:
    def __init__(self):
        self.state = PositionState()

    def add_entry(self, entry: Entry):
        """Record a new entry into the position."""
        self.state.entries.append(entry)
        self.state.total_invested_usdt += entry.size_usdt
        self.state.total_qty += entry.qty
        self.state.side = entry.side

        # Recalculate average entry price
        total_cost = sum(e.entry_price * e.qty for e in self.state.entries)
        self.state.avg_entry_price = total_cost / self.state.total_qty if self.state.total_qty > 0 else 0

        logger.info(
            "Entry added: %s %s size=%.2f USDT qty=%.6f avg_price=%.2f total_ratio=%.1f%%",
            entry.side, entry.entry_type.value, entry.size_usdt, entry.qty,
            self.state.avg_entry_price, self.state.position_ratio() * 100,
        )

    def get_sl_price(self) -> float:
        """Get the most conservative (tightest) stop loss across all entries."""
        if not self.state.entries:
            return 0
        if self.state.side == "long":
            return max(e.stop_loss_price for e in self.state.entries)
        else:
            return min(e.stop_loss_price for e in self.state.entries)

    def get_entry_types(self) -> list[str]:
        return [e.entry_type.value for e in self.state.entries]

    def partial_close(self, ratio: float) -> float:
        """Calculate qty to close for a given ratio of total position."""
        close_qty = self.state.total_qty * ratio
        self.state.total_qty -= close_qty
        self.state.total_invested_usdt *= (1 - ratio)

        if self.state.total_qty <= 0:
            self.state.reset()

        logger.info("Partial close: ratio=%.1f%% qty=%.6f remaining=%.6f",
                     ratio * 100, close_qty, self.state.total_qty)
        return close_qty

    def full_close(self) -> float:
        """Return qty to close everything."""
        qty = self.state.total_qty
        self.state.reset()
        logger.info("Full close: qty=%.6f", qty)
        return qty

    def get_status(self) -> str:
        if not self.state.is_open():
            return "포지션 없음"

        entries_info = ", ".join(
            f"{e.entry_type.value}({e.size_usdt:.0f}USDT)" for e in self.state.entries
        )
        tp_status = []
        if self.state.tp1_done:
            tp_status.append("TP1✓")
        if self.state.tp2_done:
            tp_status.append("TP2✓")
        if self.state.tp3_pending:
            tp_status.append("TP3 대기중")
        tp_str = " | ".join(tp_status) if tp_status else "TP 미도달"

        return (
            f"방향: {self.state.side}\n"
            f"평단: {self.state.avg_entry_price:.2f}\n"
            f"수량: {self.state.total_qty:.6f}\n"
            f"투자: {self.state.total_invested_usdt:.2f} USDT "
            f"({self.state.position_ratio() * 100:.1f}%)\n"
            f"진입: {entries_info}\n"
            f"TP: {tp_str}\n"
            f"SL: {self.get_sl_price():.2f}"
        )
