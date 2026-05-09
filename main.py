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
    if not TOKEN:
        print("ERROR: BOT_TOKEN is not set in Railway Variables!")
        sys.exit(1)
    if not getenv("DATABASE_URL"):
        print("ERROR: DATABASE_URL is not set in Railway Variables!")
        print("Please add: DATABASE_URL = postgresql://postgres:PASSWORD@db.xxx.supabase.co:5432/postgres")
        sys.exit(1)
    print("Connecting to Supabase database...")
    try:
        await init_db()
        print("Database connected successfully!")
    except Exception as e:
        print(f"Database connection FAILED: {e}")
        print("Check your DATABASE_URL in Railway Variables")
        sys.exit(1)

    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp  = Dispatcher(storage=MemoryStorage())
    dp.include_router(admin.router)
    dp.include_router(student.router)
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    print("Bot is running! Data is permanently stored in Supabase.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
