import asyncpg
import os
import ssl

_pool = None

async def get_pool():
    global _pool
    if _pool is None:
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            raise RuntimeError("DATABASE_URL environment variable is not set! Please add it in Railway.")
        # Supabase requires SSL — handle both URL formats
        if "sslmode" not in db_url:
            db_url = db_url + "?sslmode=require"
        _pool = await asyncpg.create_pool(db_url)
    return _pool

async def init_db():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS content (
                id          SERIAL PRIMARY KEY,
                group_name  TEXT NOT NULL,
                section     TEXT NOT NULL,
                title       TEXT NOT NULL,
                body        TEXT,
                file_id     TEXT,
                file_type   TEXT,
                created_at  TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS announcements (
                id         SERIAL PRIMARY KEY,
                message    TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                id          SERIAL PRIMARY KEY,
                user_id     BIGINT NOT NULL,
                username    TEXT,
                full_name   TEXT,
                group_name  TEXT,
                section     TEXT,
                accessed_at TIMESTAMP DEFAULT NOW()
            )
        """)

async def add_content(group_name, section, title, body=None, file_id=None, file_type=None):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO content (group_name, section, title, body, file_id, file_type) VALUES ($1,$2,$3,$4,$5,$6)",
            group_name, section, title, body, file_id, file_type
        )

async def get_content(group_name, section):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM content WHERE group_name=$1 AND section=$2 ORDER BY created_at DESC",
            group_name, section
        )
        return [dict(r) for r in rows]

async def delete_content(content_id):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM content WHERE id=$1", content_id)

async def show_content_by_section(section):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM content WHERE section=$1 ORDER BY group_name, created_at DESC",
            section
        )
        return [dict(r) for r in rows]

async def add_announcement(message):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO announcements (message) VALUES ($1)", message)

async def get_announcements():
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM announcements ORDER BY created_at DESC LIMIT 1")
        return [dict(r) for r in rows]

async def log_access(user_id, username, full_name, group_name, section):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO stats (user_id, username, full_name, group_name, section) VALUES ($1,$2,$3,$4,$5)",
            user_id, username, full_name, group_name, section
        )

async def get_stats():
    pool = await get_pool()
    async with pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(DISTINCT user_id) FROM stats")
        today = await conn.fetchval("SELECT COUNT(*) FROM stats WHERE accessed_at::date = CURRENT_DATE")
        groups = [dict(r) for r in await conn.fetch(
            "SELECT group_name, COUNT(*) as cnt FROM stats GROUP BY group_name ORDER BY cnt DESC LIMIT 5"
        )]
        sections = [dict(r) for r in await conn.fetch(
            "SELECT section, COUNT(*) as cnt FROM stats GROUP BY section ORDER BY cnt DESC"
        )]
        recent = [dict(r) for r in await conn.fetch(
            "SELECT DISTINCT ON (user_id) user_id, username, full_name, accessed_at FROM stats ORDER BY user_id, accessed_at DESC LIMIT 10"
        )]
        return {"total_users": total_users, "today": today, "groups": groups, "sections": sections, "recent": recent}
