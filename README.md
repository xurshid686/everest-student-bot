# 🎓 Everest Learning Center — Telegram Bot

Built with Python, aiogram 3, SQLite.

## Setup
1. Get bot token from @BotFather
2. Get your Telegram ID from @userinfobot
3. `cp .env.example .env` and fill in values
4. `pip install -r requirements.txt`
5. `python main.py`

## Admin Commands
- /add_task /add_homework /add_material /add_book /add_recorded_lesson /add_lesson_file
- /show_content — list content with IDs
- /delete_content — delete by ID
- /announcement — save announcement
- /cancel — cancel operation

## Deploy Free on Railway
1. Push to GitHub
2. Connect repo on railway.app
3. Add BOT_TOKEN and ADMIN_ID as environment variables
