import aiosqlite

DB_PATH = "bot_data.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS content (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                level       TEXT NOT NULL,
                group_name  TEXT NOT NULL,
                section     TEXT NOT NULL,
                title       TEXT NOT NULL,
                body        TEXT,
                file_id     TEXT,
                file_type   TEXT,
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS announcements (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                message     TEXT NOT NULL,
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

async def add_content(level, group_name, section, title, body=None, file_id=None, file_type=None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO content (level, group_name, section, title, body, file_id, file_type) VALUES (?,?,?,?,?,?,?)",
            (level, group_name, section, title, body, file_id, file_type)
        )
        await db.commit()

async def get_content(level, group_name, section):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM content WHERE level=? AND group_name=? AND section=? ORDER BY created_at DESC",
            (level, group_name, section)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

async def delete_content(content_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM content WHERE id=?", (content_id,))
        await db.commit()

async def show_content_by_section(section):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM content WHERE section=? ORDER BY level, group_name, created_at DESC",
            (section,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

async def add_announcement(message):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO announcements (message) VALUES (?)", (message,))
        await db.commit()

async def get_announcements():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM announcements ORDER BY created_at DESC LIMIT 10")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
