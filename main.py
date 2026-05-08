import asyncio, logging, sys
from os import getenv
from dotenv import load_dotenv
load_dotenv()

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from database import init_db
from handlers import student, admin

TOKEN = getenv("BOT_TOKEN")

async def main():
    if not TOKEN: sys.exit("ERROR: BOT_TOKEN not set!")
    await init_db()
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp  = Dispatcher(storage=MemoryStorage())
    dp.include_router(admin.router)
    dp.include_router(student.router)
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    print("Bot is running...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
