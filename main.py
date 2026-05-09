import asyncio
import logging
import sys
import os
from dotenv import load_dotenv
load_dotenv()

import asyncpg
from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)

# ── ENV ──────────────────────────────────────────────────────────
BOT_TOKEN   = os.getenv("BOT_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
ADMIN_ID    = int(os.getenv("ADMIN_ID", "0"))

# ── DATABASE ─────────────────────────────────────────────────────
_pool = None

async def get_pool():
    global _pool
    if _pool is None:
        url = DATABASE_URL
        if "sslmode" not in url:
            url += "?sslmode=require"
        _pool = await asyncpg.create_pool(url)
    return _pool

async def init_db():
    pool = await get_pool()
    async with pool.acquire() as c:
        await c.execute("""
            CREATE TABLE IF NOT EXISTS content (
                id SERIAL PRIMARY KEY,
                group_name TEXT NOT NULL,
                section TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT,
                file_id TEXT,
                file_type TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )""")
        await c.execute("""
            CREATE TABLE IF NOT EXISTS announcements (
                id SERIAL PRIMARY KEY,
                message TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )""")
        await c.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                username TEXT,
                full_name TEXT,
                group_name TEXT,
                section TEXT,
                accessed_at TIMESTAMP DEFAULT NOW()
            )""")

async def db_add(group, section, title, body=None, file_id=None, file_type=None):
    pool = await get_pool()
    async with pool.acquire() as c:
        await c.execute(
            "INSERT INTO content (group_name,section,title,body,file_id,file_type) VALUES($1,$2,$3,$4,$5,$6)",
            group, section, title, body, file_id, file_type)

async def db_get(group, section):
    pool = await get_pool()
    async with pool.acquire() as c:
        rows = await c.fetch(
            "SELECT * FROM content WHERE group_name=$1 AND section=$2 ORDER BY created_at DESC",
            group, section)
        return [dict(r) for r in rows]

async def db_delete(cid):
    pool = await get_pool()
    async with pool.acquire() as c:
        await c.execute("DELETE FROM content WHERE id=$1", cid)

async def db_section(section):
    pool = await get_pool()
    async with pool.acquire() as c:
        rows = await c.fetch(
            "SELECT * FROM content WHERE section=$1 ORDER BY group_name, created_at DESC", section)
        return [dict(r) for r in rows]

async def db_announce(msg):
    pool = await get_pool()
    async with pool.acquire() as c:
        await c.execute("INSERT INTO announcements (message) VALUES ($1)", msg)

async def db_get_announce():
    pool = await get_pool()
    async with pool.acquire() as c:
        rows = await c.fetch("SELECT * FROM announcements ORDER BY created_at DESC LIMIT 1")
        return [dict(r) for r in rows]

async def db_log(uid, uname, fname, group, section):
    pool = await get_pool()
    async with pool.acquire() as c:
        await c.execute(
            "INSERT INTO stats(user_id,username,full_name,group_name,section) VALUES($1,$2,$3,$4,$5)",
            uid, uname, fname, group, section)

async def db_stats():
    pool = await get_pool()
    async with pool.acquire() as c:
        total = await c.fetchval("SELECT COUNT(DISTINCT user_id) FROM stats")
        today = await c.fetchval("SELECT COUNT(*) FROM stats WHERE accessed_at::date=CURRENT_DATE")
        groups = [dict(r) for r in await c.fetch(
            "SELECT group_name, COUNT(*) cnt FROM stats GROUP BY group_name ORDER BY cnt DESC LIMIT 5")]
        sections = [dict(r) for r in await c.fetch(
            "SELECT section, COUNT(*) cnt FROM stats GROUP BY section ORDER BY cnt DESC")]
        recent = [dict(r) for r in await c.fetch(
            "SELECT DISTINCT ON(user_id) user_id,username,full_name,accessed_at FROM stats ORDER BY user_id,accessed_at DESC LIMIT 10")]
        return {"total": total, "today": today, "groups": groups, "sections": sections, "recent": recent}

# ── KEYBOARDS ────────────────────────────────────────────────────
GROUPS = ["Hunters", "Hackers", "Assassins"]

SECTIONS = [
    ("📝 Tasks",            "task"),
    ("📚 Homework",         "homework"),
    ("📄 Materials",        "material"),
    ("📖 Books",            "book"),
    ("🎬 Recorded Lessons", "recorded_lesson"),
    ("📁 Lesson Files",     "lesson_file"),
]
SEC_LABEL = {k: lbl for lbl, k in SECTIONS}

def kb_groups():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"👥 {g}", callback_data=f"grp:{g}")]
        for g in GROUPS
    ])

def kb_sections(group):
    btns = [
        [InlineKeyboardButton(text=lbl, callback_data=f"sec:{group}:{key}")]
        for lbl, key in SECTIONS
    ]
    btns.append([InlineKeyboardButton(text="⬅️ Back", callback_data="back:groups")])
    return InlineKeyboardMarkup(inline_keyboard=btns)

def kb_back(group):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Back to Sections", callback_data=f"back:sec:{group}")]
    ])

def kb_admin_groups():
    btns = [
        [InlineKeyboardButton(text=f"👥 {g}", callback_data=f"ag:{g}")]
        for g in GROUPS
    ]
    btns.append([InlineKeyboardButton(text="❌ Cancel", callback_data="acancel")])
    return InlineKeyboardMarkup(inline_keyboard=btns)

# ── STATES ───────────────────────────────────────────────────────
class Add(StatesGroup):
    group   = State()
    title   = State()
    content = State()

class Del(StatesGroup):
    cid = State()

class Show(StatesGroup):
    sec = State()

class Ann(StatesGroup):
    msg = State()

# ── ROUTER ───────────────────────────────────────────────────────
router = Router()

def is_admin(uid): return uid == ADMIN_ID

# STUDENT: /start
@router.message(CommandStart())
async def start(m: Message):
    ann = await db_get_announce()
    txt = "<b>Welcome to Everest Learning Center!</b>\n\nChoose your group:"
    if ann:
        txt += f"\n\n📢 <b>Announcement:</b>\n{ann[0]['message']}"
    await m.answer(txt, reply_markup=kb_groups())

# STUDENT: pick group
@router.callback_query(F.data.startswith("grp:"))
async def on_group(cb: CallbackQuery):
    g = cb.data[4:]
    await cb.message.edit_text(f"👥 <b>{g}</b>\n\nChoose section:", reply_markup=kb_sections(g))

# STUDENT: pick section
@router.callback_query(F.data.startswith("sec:"))
async def on_section(cb: CallbackQuery):
    parts = cb.data.split(":", 2)
    group, section = parts[1], parts[2]
    u = cb.from_user
    await db_log(u.id, u.username or "", u.full_name or "", group, section)
    label = SEC_LABEL.get(section, section)
    items = await db_get(group, section)
    if not items:
        return await cb.message.edit_text(
            f"<b>{label}</b> — {group}\n\n📭 Nothing here yet!",
            reply_markup=kb_back(group))
    await cb.message.edit_text(
        f"<b>{label}</b> — {group}\n\nSending <b>{len(items)}</b> item(s)...",
        reply_markup=kb_back(group))
    bot = cb.bot
    SEND = {"photo":"send_photo","document":"send_document",
            "audio":"send_audio","video":"send_video","voice":"send_voice"}
    for item in items:
        cap = f"<b>{item['title']}</b>" + (f"\n{item['body']}" if item.get("body") else "")
        ft, fid = item.get("file_type"), item.get("file_id")
        if fid and ft in SEND:
            fn = getattr(bot, SEND[ft])
            kw = {"chat_id": u.id, "caption": cap, "parse_mode": "HTML", ft: fid}
            await fn(**kw)
        else:
            await bot.send_message(chat_id=u.id, text=cap, parse_mode="HTML")

@router.callback_query(F.data == "back:groups")
async def back_groups(cb: CallbackQuery):
    await cb.message.edit_text("Choose your group:", reply_markup=kb_groups())

@router.callback_query(F.data.startswith("back:sec:"))
async def back_sec(cb: CallbackQuery):
    g = cb.data[9:]
    await cb.message.edit_text(f"👥 <b>{g}</b>\n\nChoose section:", reply_markup=kb_sections(g))

# ADMIN: /admin
@router.message(Command("admin"))
async def cmd_admin(m: Message):
    if not is_admin(m.from_user.id): return await m.answer("Not authorized.")
    await m.answer(
        "<b>Admin Panel</b>\n\n"
        "/add_task\n/add_homework\n/add_material\n"
        "/add_book\n/add_recorded_lesson\n/add_lesson_file\n\n"
        "/show_content — list by section\n"
        "/delete_content — delete by ID\n"
        "/announcement — post announcement\n"
        "/stats — statistics\n"
        "/cancel — cancel action")

async def start_add(m, state, section):
    if not is_admin(m.from_user.id): return await m.answer("Not authorized.")
    await state.update_data(section=section)
    await state.set_state(Add.group)
    await m.answer("Choose group:", reply_markup=kb_admin_groups())

@router.message(Command("add_task"))
async def a1(m, s: FSMContext): await start_add(m, s, "task")
@router.message(Command("add_homework"))
async def a2(m, s: FSMContext): await start_add(m, s, "homework")
@router.message(Command("add_material"))
async def a3(m, s: FSMContext): await start_add(m, s, "material")
@router.message(Command("add_book"))
async def a4(m, s: FSMContext): await start_add(m, s, "book")
@router.message(Command("add_recorded_lesson"))
async def a5(m, s: FSMContext): await start_add(m, s, "recorded_lesson")
@router.message(Command("add_lesson_file"))
async def a6(m, s: FSMContext): await start_add(m, s, "lesson_file")

@router.callback_query(Add.group, F.data.startswith("ag:"))
async def pick_group(cb: CallbackQuery, state: FSMContext):
    g = cb.data[3:]
    await state.update_data(group=g)
    await state.set_state(Add.title)
    await cb.message.edit_text(f"Group: <b>{g}</b>\n\nSend the <b>title</b>:")

@router.message(Add.title, F.text)
async def get_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text)
    await state.set_state(Add.content)
    await m.answer("Title saved!\n\nNow send the content (text, photo, video, document, audio, voice)\nOr /skip for title only.")

@router.message(Add.content, F.text)
async def get_text(m: Message, state: FSMContext):
    d = await state.get_data()
    body = None if m.text == "/skip" else m.text
    await db_add(d["group"], d["section"], d["title"], body=body)
    await state.clear(); await m.answer("✅ Saved!")

@router.message(Add.content, F.photo)
async def get_photo(m: Message, state: FSMContext):
    d = await state.get_data()
    await db_add(d["group"], d["section"], d["title"], body=m.caption or "", file_id=m.photo[-1].file_id, file_type="photo")
    await state.clear(); await m.answer("✅ Photo saved!")

@router.message(Add.content, F.document)
async def get_doc(m: Message, state: FSMContext):
    d = await state.get_data()
    await db_add(d["group"], d["section"], d["title"], body=m.caption or "", file_id=m.document.file_id, file_type="document")
    await state.clear(); await m.answer("✅ Document saved!")

@router.message(Add.content, F.audio)
async def get_audio(m: Message, state: FSMContext):
    d = await state.get_data()
    await db_add(d["group"], d["section"], d["title"], body=m.caption or "", file_id=m.audio.file_id, file_type="audio")
    await state.clear(); await m.answer("✅ Audio saved!")

@router.message(Add.content, F.video)
async def get_video(m: Message, state: FSMContext):
    d = await state.get_data()
    await db_add(d["group"], d["section"], d["title"], body=m.caption or "", file_id=m.video.file_id, file_type="video")
    await state.clear(); await m.answer("✅ Video saved!")

@router.message(Add.content, F.voice)
async def get_voice(m: Message, state: FSMContext):
    d = await state.get_data()
    await db_add(d["group"], d["section"], d["title"], file_id=m.voice.file_id, file_type="voice")
    await state.clear(); await m.answer("✅ Voice saved!")

@router.message(Command("delete_content"))
async def cmd_del(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id): return await m.answer("Not authorized.")
    await state.set_state(Del.cid)
    await m.answer("Send the content <b>ID</b> to delete. Use /show_content to find IDs.")

@router.message(Del.cid, F.text)
async def do_del(m: Message, state: FSMContext):
    try:
        await db_delete(int(m.text.strip()))
        await state.clear(); await m.answer("✅ Deleted!")
    except: await m.answer("Send a valid ID number.")

VALID_SECS = ["task","homework","material","book","recorded_lesson","lesson_file"]

@router.message(Command("show_content"))
async def cmd_show(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id): return await m.answer("Not authorized.")
    await state.set_state(Show.sec)
    await m.answer("Which section?\n<code>task | homework | material | book | recorded_lesson | lesson_file</code>")

@router.message(Show.sec, F.text)
async def do_show(m: Message, state: FSMContext):
    s = m.text.strip().lower()
    if s not in VALID_SECS: return await m.answer("Invalid section name.")
    rows = await db_section(s)
    await state.clear()
    if not rows: return await m.answer("No content in this section.")
    text = f"<b>Section: {s}</b>\n\n"
    for r in rows:
        text += f"ID: <code>{r['id']}</code> | {r['group_name']}\nTitle: {r['title']}\n{'File: '+r['file_type'] if r.get('file_id') else 'Text only'}\n\n"
    await m.answer(text[:4000])

@router.message(Command("stats"))
async def cmd_stats(m: Message):
    if not is_admin(m.from_user.id): return await m.answer("Not authorized.")
    s = await db_stats()
    txt = (f"📊 <b>Bot Statistics</b>\n\n"
           f"👥 Total students: <b>{s['total']}</b>\n"
           f"📅 Today: <b>{s['today']}</b>\n\n<b>Groups:</b>\n")
    for g in s["groups"]: txt += f"  👥 {g['group_name']}: {g['cnt']}\n"
    txt += "\n<b>Sections:</b>\n"
    for sec in s["sections"]: txt += f"  📂 {sec['section']}: {sec['cnt']}\n"
    txt += "\n<b>Recent students:</b>\n"
    for u in s["recent"]:
        name = u["full_name"] or u["username"] or str(u["user_id"])
        txt += f"  • {name} ({str(u['accessed_at'])[:10]})\n"
    await m.answer(txt)

@router.message(Command("announcement"))
async def cmd_ann(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id): return await m.answer("Not authorized.")
    await state.set_state(Ann.msg)
    await m.answer("Type your announcement:")

@router.message(Ann.msg, F.text)
async def save_ann(m: Message, state: FSMContext):
    await db_announce(m.text)
    await state.clear()
    await m.answer("✅ Announcement saved!")

@router.message(Command("cancel"))
async def cmd_cancel(m: Message, state: FSMContext):
    await state.clear(); await m.answer("✅ Cancelled.")

@router.callback_query(F.data == "acancel")
async def cb_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear(); await cb.message.edit_text("Cancelled.")

# ── MAIN ─────────────────────────────────────────────────────────
async def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN not set!"); sys.exit(1)
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL not set!"); sys.exit(1)
    print("Connecting to database...")
    await init_db()
    print("Database ready!")
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    print("Bot is running!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
