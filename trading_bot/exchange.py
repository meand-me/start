"""Binance exchange interface using ccxt."""

import logging
import ccxt
import pandas as pd
from trading_bot.config import (
    BINANCE_API_KEY, BINANCE_API_SECRET, SYMBOL, LEVERAGE, USE_TESTNET,
)

logger = logging.getLogger(__name__)


class Exchange:
    def __init__(self):
        self.exchange = ccxt.binance({
            "apiKey": BINANCE_API_KEY,
            "secret": BINANCE_API_SECRET,
            "options": {"defaultType": "future"},
            "enableRateLimit": True,
        })
        if USE_TESTNET:
            self.exchange.set_sandbox_mode(True)

        self.symbol = SYMBOL
        self._set_leverage()

    def _set_leverage(self):
        try:
            self.exchange.fapiPrivate_post_leverage({
                "symbol": self.symbol.replace("/", ""),
                "leverage": LEVERAGE,
            })
            logger.info("Leverage set to %dx for %s", LEVERAGE, self.symbol)
        except Exception as e:
            logger.warning("Failed to set leverage: %s", e)

    # ── Market Data ──────────────────────────────────────────
    def fetch_ohlcv(self, timeframe: str = "1h", limit: int = 300) -> pd.DataFrame:
        raw = self.exchange.fetch_ohlcv(self.symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        return df

    def get_ticker_price(self) -> float:
        ticker = self.exchange.fetch_ticker(self.symbol)
        return float(ticker["last"])

    # ── Account Info ─────────────────────────────────────────
    def get_balance(self) -> float:
        balance = self.exchange.fetch_balance()
        return float(balance["total"].get("USDT", 0))

    def get_position(self) -> dict | None:
        positions = self.exchange.fetch_positions([self.symbol])
        for pos in positions:
            size = float(pos.get("contracts", 0))
            if size != 0:
                return {
                    "side": pos["side"],
                    "size": size,
                    "notional": float(pos.get("notional", 0)),
                    "entry_price": float(pos.get("entryPrice", 0)),
                    "unrealized_pnl": float(pos.get("unrealizedPnl", 0)),
                    "leverage": int(pos.get("leverage", LEVERAGE)),
                }
        return None

    # ── Orders ───────────────────────────────────────────────
    def market_buy(self, amount_usdt: float) -> dict:
        """Open long position with given USDT amount."""
        price = self.get_ticker_price()
        qty = self._usdt_to_qty(amount_usdt, price)
        logger.info("MARKET BUY %s qty=%.6f price=%.2f", self.symbol, qty, price)
        return self.exchange.create_market_buy_order(self.symbol, qty)

    def market_sell(self, amount_usdt: float) -> dict:
        """Open short position with given USDT amount."""
        price = self.get_ticker_price()
        qty = self._usdt_to_qty(amount_usdt, price)
        logger.info("MARKET SELL %s qty=%.6f price=%.2f", self.symbol, qty, price)
        return self.exchange.create_market_sell_order(self.symbol, qty)

    def close_long(self, qty: float) -> dict:
        """Close (partial) long position."""
        logger.info("CLOSE LONG %s qty=%.6f", self.symbol, qty)
        return self.exchange.create_market_sell_order(self.symbol, qty)

    def close_short(self, qty: float) -> dict:
        """Close (partial) short position."""
        logger.info("CLOSE SHORT %s qty=%.6f", self.symbol, qty)
        return self.exchange.create_market_buy_order(self.symbol, qty)

    def close_all(self) -> dict | None:
        """Close entire position."""
        pos = self.get_position()
        if pos is None:
            logger.info("No position to close")
            return None
        qty = pos["size"]
        if pos["side"] == "long":
            return self.close_long(qty)
        else:
            return self.close_short(qty)

    def set_stop_loss(self, side: str, stop_price: float, qty: float) -> dict:
        """Place a stop-market order."""
        order_side = "sell" if side == "long" else "buy"
        params = {"stopPrice": stop_price, "closePosition": False}
        logger.info("STOP LOSS %s side=%s stop=%.2f qty=%.6f", self.symbol, order_side, stop_price, qty)
        return self.exchange.create_order(
            self.symbol, "STOP_MARKET", order_side, qty, None, params
        )

    def cancel_all_orders(self):
        """Cancel all open orders for the symbol."""
        try:
            self.exchange.cancel_all_orders(self.symbol)
            logger.info("All orders cancelled for %s", self.symbol)
        except Exception as e:
            logger.warning("Cancel orders error: %s", e)

    # ── Helpers ──────────────────────────────────────────────
    def _usdt_to_qty(self, usdt: float, price: float) -> float:
        """Convert USDT amount to contract quantity (with leverage)."""
        raw_qty = (usdt * LEVERAGE) / price
        # Round to exchange precision
        market = self.exchange.market(self.symbol)
        precision = market.get("precision", {}).get("amount", 3)
        return round(raw_qty, precision)
