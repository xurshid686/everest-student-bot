import aiosqlite

DB_PATH = "bot_data.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS content (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
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
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                message    TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                username    TEXT,
                full_name   TEXT,
                group_name  TEXT,
                section     TEXT,
                accessed_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

async def add_content(group_name, section, title, body=None, file_id=None, file_type=None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO content (group_name, section, title, body, file_id, file_type) VALUES (?,?,?,?,?,?)",
            (group_name, section, title, body, file_id, file_type)
        )
        await db.commit()

async def get_content(group_name, section):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM content WHERE group_name=? AND section=? ORDER BY created_at DESC",
            (group_name, section)
        )
        return [dict(r) for r in await cursor.fetchall()]

async def delete_content(content_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM content WHERE id=?", (content_id,))
        await db.commit()

async def show_content_by_section(section):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM content WHERE section=? ORDER BY group_name, created_at DESC",
            (section,)
        )
        return [dict(r) for r in await cursor.fetchall()]

async def add_announcement(message):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO announcements (message) VALUES (?)", (message,))
        await db.commit()

async def get_announcements():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM announcements ORDER BY created_at DESC LIMIT 1")
        return [dict(r) for r in await cursor.fetchall()]

async def log_access(user_id, username, full_name, group_name, section):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO stats (user_id, username, full_name, group_name, section) VALUES (?,?,?,?,?)",
            (user_id, username, full_name, group_name, section)
        )
        await db.commit()

async def get_stats():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        c1 = await db.execute("SELECT COUNT(DISTINCT user_id) as total FROM stats")
        total_users = (await c1.fetchone())["total"]
        c2 = await db.execute("""SELECT group_name, COUNT(*) as cnt FROM stats GROUP BY group_name ORDER BY cnt DESC LIMIT 5""")
        groups = [dict(r) for r in await c2.fetchall()]
        c3 = await db.execute("""SELECT section, COUNT(*) as cnt FROM stats GROUP BY section ORDER BY cnt DESC""")
        sections = [dict(r) for r in await c3.fetchall()]
        c4 = await db.execute("""SELECT COUNT(*) as cnt FROM stats WHERE DATE(accessed_at) = DATE('now')""")
        today = (await c4.fetchone())["cnt"]
        c5 = await db.execute("""SELECT DISTINCT user_id, username, full_name, MAX(accessed_at) as last FROM stats GROUP BY user_id ORDER BY last DESC LIMIT 10""")
        recent = [dict(r) for r in await c5.fetchall()]
        return {"total_users": total_users, "today": today, "groups": groups, "sections": sections, "recent": recent}
