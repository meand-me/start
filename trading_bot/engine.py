"""Main trading engine: orchestrates exchange, strategy, position manager, and Telegram."""

import asyncio
import logging
import time

from trading_bot.config import (
    TOTAL_CAPITAL, POLL_INTERVAL, MODE_LONG, MODE_SHORT, MODE_SCALP, MODE_STOP,
    TIMEFRAME_15M, TIMEFRAME_1H, TIMEFRAME_4H,
)
from trading_bot.exchange import Exchange
from trading_bot.strategy import Strategy
from trading_bot.position_manager import PositionManager, Entry
from trading_bot.telegram_bot import TelegramBot

logger = logging.getLogger(__name__)


class TradingEngine:
    def __init__(self):
        self.exchange = Exchange()
        self.strategy = Strategy(mode=MODE_STOP)  # Start in stopped mode
        self.pm = PositionManager()
        self.bot = TelegramBot()
        self._running = False
        self._mode = MODE_STOP

    async def start(self):
        """Initialize and start the trading engine."""
        # Set up Telegram callbacks
        self.bot.set_command_callback(self._handle_command)
        self.bot.set_tp3_response_callback(self._handle_tp3_response)

        await self.bot.start()
        await self.bot.send_message("자동매매 시스템 시작! 명령어를 입력하세요.\n(롱/숏/단타/중지/청산/상태)")

        self._running = True
        logger.info("Trading engine started")

        # Main loop
        await self._main_loop()

    async def stop(self):
        self._running = False
        await self.bot.stop()
        logger.info("Trading engine stopped")

    # ================================================================
    # Telegram Command Handler
    # ================================================================
    async def _handle_command(self, command: str, update):
        reply = update.message.reply_text

        if command == "롱":
            self._mode = MODE_LONG
            self.strategy.set_mode(MODE_LONG)
            await reply("롱 모드 설정 완료! 롱 방향으로만 매매합니다.")

        elif command == "숏":
            self._mode = MODE_SHORT
            self.strategy.set_mode(MODE_SHORT)
            await reply("숏 모드 설정 완료! 숏 방향으로만 매매합니다.")

        elif command == "단타":
            self._mode = MODE_SCALP
            self.strategy.set_mode(MODE_SCALP)
            await reply("단타 모드 설정 완료! 양방향 자동매매를 시작합니다.")

        elif command == "중지":
            self._mode = MODE_STOP
            self.strategy.set_mode(MODE_STOP)
            await reply("자동매매 일시 정지!")

        elif command == "청산":
            await self._force_liquidate()
            await reply("포지션 전량 청산 완료!")

        elif command == "상태":
            status = self._get_full_status()
            await reply(status)

    async def _handle_tp3_response(self, text: str, update):
        """Handle user's TP3 decision."""
        if not self.pm.state.tp3_pending:
            await update.message.reply_text("현재 TP3 대기 중인 포지션이 없습니다.")
            return

        text_lower = text.strip().lower()
        side = self.pm.state.side

        if "홀드" in text or "유지" in text:
            await update.message.reply_text("잔여 40% 포지션을 유지합니다.")
            self.pm.state.tp3_pending = False

        elif "청산" in text or "익절" in text:
            qty = self.pm.full_close()
            if side == "long":
                self.exchange.close_long(qty)
            else:
                self.exchange.close_short(qty)
            self.exchange.cancel_all_orders()
            await update.message.reply_text("잔여 40% 포지션 청산 완료!")

        else:
            await update.message.reply_text(
                "명확하지 않은 지시입니다. '홀드' 또는 '청산'으로 답변해주세요."
            )

    # ================================================================
    # Main Trading Loop
    # ================================================================
    async def _main_loop(self):
        alma_alerted = False

        while self._running:
            try:
                if self._mode == MODE_STOP:
                    await asyncio.sleep(POLL_INTERVAL)
                    continue

                # Fetch market data
                df_15m = self.exchange.fetch_ohlcv(TIMEFRAME_15M, 300)
                df_1h = self.exchange.fetch_ohlcv(TIMEFRAME_1H, 300)
                df_4h = self.exchange.fetch_ohlcv(TIMEFRAME_4H, 300)

                # ── ALMA Pre-Alert ──────────────────────────────
                if not alma_alerted:
                    alma_msg = self.strategy.check_alma_alert(df_1h)
                    if alma_msg:
                        await self.bot.send_alma_alert(alma_msg)
                        alma_alerted = True

                # ── 15m Alert Only ──────────────────────────────
                alert_15m = self.strategy.check_15m_alert(df_15m)
                if alert_15m:
                    await self.bot.send_15m_alert(alert_15m)

                # ── Position Management (if position open) ──────
                if self.pm.state.is_open():
                    await self._manage_position(df_1h, df_15m)
                else:
                    alma_alerted = False  # Reset ALMA alert for next cycle
                    # ── Entry Evaluation ────────────────────────
                    await self._evaluate_entry(df_1h, df_15m, df_4h)

            except Exception as e:
                logger.error("Main loop error: %s", e, exc_info=True)
                await self.bot.send_message(f"⚠️ 시스템 오류: {e}")

            await asyncio.sleep(POLL_INTERVAL)

    # ================================================================
    # Entry Evaluation
    # ================================================================
    async def _evaluate_entry(self, df_1h, df_15m, df_4h):
        signal = self.strategy.evaluate_entry(df_1h, df_15m, df_4h)
        if signal is None or signal.action == "none":
            return

        # Check position limit
        if not self.pm.state.can_add(signal.size_ratio):
            logger.info("Position limit reached (%.1f%%), skipping entry",
                        self.pm.state.position_ratio() * 100)
            return

        # Execute entry
        size_usdt = TOTAL_CAPITAL * signal.size_ratio
        try:
            if signal.action == "buy":
                order = self.exchange.market_buy(size_usdt)
            else:
                order = self.exchange.market_sell(size_usdt)

            # Record entry
            filled_qty = float(order.get("filled", 0))
            filled_price = float(order.get("average", 0)) or self.exchange.get_ticker_price()

            entry = Entry(
                entry_type=signal.entry_type,
                side="long" if signal.action == "buy" else "short",
                size_usdt=size_usdt,
                entry_price=filled_price,
                stop_loss_price=signal.stop_loss_price,
                qty=filled_qty,
            )
            self.pm.add_entry(entry)

            await self.bot.send_entry_alert(
                entry.side, signal.entry_type.value, filled_price, signal.reason
            )
            logger.info("Entry executed: %s", signal.reason)

        except Exception as e:
            logger.error("Entry order failed: %s", e)
            await self.bot.send_message(f"⚠️ 주문 실패: {e}")

    # ================================================================
    # Position Management (TP / SL)
    # ================================================================
    async def _manage_position(self, df_1h, df_15m):
        side = self.pm.state.side

        # ── Check Stop Loss ─────────────────────────────────
        # Use the most recent entry type for SL rules
        entry_types = self.pm.get_entry_types()
        sl_price = self.pm.get_sl_price()

        sl_signal = self.strategy.evaluate_sl(
            side, entry_types[-1] if entry_types else "", sl_price, df_1h, df_15m
        )

        if sl_signal.should_stop:
            logger.info("Stop loss triggered: %s", sl_signal.reason)
            qty = self.pm.full_close()
            try:
                if side == "long":
                    self.exchange.close_long(qty)
                else:
                    self.exchange.close_short(qty)
                self.exchange.cancel_all_orders()
                await self.bot.send_sl_alert(sl_signal.reason)
            except Exception as e:
                logger.error("SL execution failed: %s", e)
                await self.bot.send_message(f"⚠️ 손절 주문 실패: {e}")
            return

        # ── Check Take Profit ───────────────────────────────
        tp_signal = self.strategy.evaluate_tp(
            side, self.pm.state.avg_entry_price, df_1h,
            self.pm.state.tp1_done, self.pm.state.tp2_done,
        )

        if tp_signal is not None:
            if tp_signal.level == "TP1" and not self.pm.state.tp1_done:
                qty = self.pm.partial_close(tp_signal.close_ratio)
                try:
                    if side == "long":
                        self.exchange.close_long(qty)
                    else:
                        self.exchange.close_short(qty)
                    self.pm.state.tp1_done = True
                    await self.bot.send_tp_alert("TP1", tp_signal.close_ratio, tp_signal.reason)
                except Exception as e:
                    logger.error("TP1 execution failed: %s", e)

            elif tp_signal.level == "TP2" and not self.pm.state.tp2_done:
                qty = self.pm.partial_close(tp_signal.close_ratio)
                try:
                    if side == "long":
                        self.exchange.close_long(qty)
                    else:
                        self.exchange.close_short(qty)
                    self.pm.state.tp2_done = True
                    self.pm.state.tp3_pending = True
                    await self.bot.send_tp_alert("TP2", tp_signal.close_ratio, tp_signal.reason)
                    # Send TP3 question
                    current_price = self.exchange.get_ticker_price()
                    await self.bot.send_tp3_question(current_price, self.pm.state.avg_entry_price)
                    self.pm.state.tp3_notified = True
                except Exception as e:
                    logger.error("TP2 execution failed: %s", e)

        # ── TP3 auto-close at avg price if no response ──────
        if self.pm.state.tp3_pending and self.pm.state.tp3_notified:
            current_price = self.exchange.get_ticker_price()
            avg = self.pm.state.avg_entry_price

            should_auto_close = False
            if side == "long" and current_price <= avg:
                should_auto_close = True
            elif side == "short" and current_price >= avg:
                should_auto_close = True

            if should_auto_close:
                qty = self.pm.full_close()
                try:
                    if side == "long":
                        self.exchange.close_long(qty)
                    else:
                        self.exchange.close_short(qty)
                    self.exchange.cancel_all_orders()
                    await self.bot.send_message(
                        f"TP3 자동 청산 (평단 도달)\n평단: {avg:.2f} / 현재가: {current_price:.2f}"
                    )
                except Exception as e:
                    logger.error("TP3 auto-close failed: %s", e)

    # ================================================================
    # Force Liquidation
    # ================================================================
    async def _force_liquidate(self):
        try:
            self.exchange.close_all()
            self.exchange.cancel_all_orders()
            self.pm.state.reset()
            await self.bot.send_liquidation_alert()
        except Exception as e:
            logger.error("Force liquidation failed: %s", e)
            await self.bot.send_message(f"⚠️ 청산 실패: {e}")

    # ================================================================
    # Status
    # ================================================================
    def _get_full_status(self) -> str:
        mode_names = {
            MODE_LONG: "롱",
            MODE_SHORT: "숏",
            MODE_SCALP: "단타",
            MODE_STOP: "정지",
        }
        try:
            balance = self.exchange.get_balance()
            price = self.exchange.get_ticker_price()
        except Exception:
            balance = 0
            price = 0

        pos_status = self.pm.get_status()

        return (
            f"=== 시스템 상태 ===\n"
            f"모드: {mode_names.get(self._mode, self._mode)}\n"
            f"잔고: {balance:.2f} USDT\n"
            f"현재가: {price:.2f}\n\n"
            f"=== 포지션 ===\n"
            f"{pos_status}"
        )
