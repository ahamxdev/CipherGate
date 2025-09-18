"""
bot.py
---------
This is the entry point of the Telegram bot.
It initializes the bot, dispatcher, and registers all handlers.
"""

import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

# Import config (to load BOT_TOKEN from .env)
from utils.config import settings

# Import handlers
from handlers import user_handlers, admin_handlers


async def main():
    """
    Main function to start the Telegram bot.
    - Initializes the bot with the token
    - Registers handlers
    - Starts polling
    """
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    # Initialize bot
    bot = Bot(token=settings.BOT_TOKEN, parse_mode=ParseMode.HTML)

    # Initialize dispatcher with in-memory FSM storage
    dp = Dispatcher(storage=MemoryStorage())

    # Register user and admin handlers
    dp.include_router(user_handlers.router)
    dp.include_router(admin_handlers.router)

    logging.info("🤖 Bot is starting...")

    # Start polling
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("❌ Bot stopped.")
