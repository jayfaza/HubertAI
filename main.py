# main.py
# Точка входа — запуск бота.

import asyncio
import logging
from aiogram import F
from aiogram.types import ContentType

from aiogram import Bot, Dispatcher
from config import TOKEN
from handlers.messages import router

# Включаем логирование
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

async def main():
    bot = Bot(token=TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    logger.info("Запускаем бота...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен вручную")
