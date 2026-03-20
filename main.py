"""Auto trading system entry point."""

import asyncio
import logging
import sys

from trading_bot.engine import TradingEngine

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("trading.log"),
    ],
)
logger = logging.getLogger(__name__)


async def main():
    engine = TradingEngine()
    try:
        logger.info("Starting auto trading system...")
        await engine.start()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await engine.stop()


if __name__ == "__main__":
    asyncio.run(main())
