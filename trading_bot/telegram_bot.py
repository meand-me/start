"""Telegram bot: command handling and alert notifications."""

import asyncio
import logging
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters,
)
from trading_bot.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)


class TelegramBot:
    def __init__(self):
        self.app: Application | None = None
        self._command_callback = None
        self._tp3_response_callback = None

    def set_command_callback(self, callback):
        """Set callback for trading commands: callback(command: str)"""
        self._command_callback = callback

    def set_tp3_response_callback(self, callback):
        """Set callback for TP3 user response: callback(text: str)"""
        self._tp3_response_callback = callback

    async def start(self):
        self.app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

        # Register command handlers
        self.app.add_handler(CommandHandler("start", self._cmd_start))
        self.app.add_handler(CommandHandler("상태", self._cmd_status))

        # Text message handler for trading commands
        self.app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, self._handle_message
        ))

        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()
        logger.info("Telegram bot started")

    async def stop(self):
        if self.app:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
            logger.info("Telegram bot stopped")

    # ── Command Handlers ─────────────────────────────────────
    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "자동매매 봇 활성화!\n\n"
            "명령어:\n"
            "롱 - 롱 방향 매매\n"
            "숏 - 숏 방향 매매\n"
            "단타 - 양방향 자동매매\n"
            "중지 - 프로그램 일시 정지\n"
            "청산 - 현재 포지션 즉시 청산\n"
            "상태 - 현재 포지션/모드 확인"
        )

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self._command_callback:
            await self._command_callback("상태", update)

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.message.text:
            return

        # Only accept messages from authorized chat
        chat_id = str(update.message.chat_id)
        if TELEGRAM_CHAT_ID and chat_id != TELEGRAM_CHAT_ID:
            return

        text = update.message.text.strip()

        # Check if this is a TP3 response
        if self._tp3_response_callback and text not in ("롱", "숏", "단타", "중지", "청산", "상태"):
            await self._tp3_response_callback(text, update)
            return

        # Trading commands
        valid_commands = {"롱", "숏", "단타", "중지", "청산", "상태"}
        if text in valid_commands:
            if self._command_callback:
                await self._command_callback(text, update)
        else:
            await update.message.reply_text(f"알 수 없는 명령어: {text}")

    # ── Notification Methods ─────────────────────────────────
    async def send_message(self, text: str):
        """Send a message to the configured chat."""
        if self.app and TELEGRAM_CHAT_ID:
            await self.app.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text)

    async def send_entry_alert(self, side: str, entry_type: str, price: float, reason: str):
        msg = (
            f"{'🟢' if side == 'long' else '🔴'} 진입 완료!\n"
            f"방향: {side.upper()}\n"
            f"조건: {entry_type}\n"
            f"가격: {price:.2f}\n"
            f"사유: {reason}"
        )
        await self.send_message(msg)

    async def send_tp_alert(self, level: str, close_ratio: float, reason: str):
        msg = f"💰 {level} 익절!\n비율: {close_ratio * 100:.0f}%\n{reason}"
        await self.send_message(msg)

    async def send_tp3_question(self, current_price: float, avg_price: float):
        msg = (
            f"💰 TP2 도달! 나머지 40% 어떻게 할까요?\n"
            f"현재가 {current_price:.2f} / 평단 {avg_price:.2f}\n\n"
            f"답장으로 지시해주세요.\n"
            f"(답장 없으면 평단 도달 시 자동 청산)"
        )
        await self.send_message(msg)

    async def send_sl_alert(self, reason: str):
        msg = f"🛑 손절 실행!\n{reason}"
        await self.send_message(msg)

    async def send_alma_alert(self, message: str):
        msg = f"📊 {message}"
        await self.send_message(msg)

    async def send_15m_alert(self, message: str):
        msg = f"📊 {message}"
        await self.send_message(msg)

    async def send_liquidation_alert(self):
        msg = "⚡ 포지션 전량 청산 완료!"
        await self.send_message(msg)
