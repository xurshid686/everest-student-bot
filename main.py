import asyncio
import logging
import sys
import os

# Load .env if present (local dev), ignored on Railway
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

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

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────
BOT_TOKEN    = os.getenv("BOT_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
ADMIN_ID     = int(os.getenv("ADMIN_ID", "0"))

LESSON_TIMES = ["9:30", "14:30", "16:30", "18:30"]

GROUP_SECTIONS = [
    ("📝 Homework",         "homework"),
    ("📖 Books",            "book"),
    ("🎬 Recorded Lessons", "recorded_lesson"),
    ("📁 Files",            "files"),
    ("📋 Board Notes",      "board"),
]
SEC_LABELS = {k: lbl for lbl, k in GROUP_SECTIONS}

# Mock subsections — listening has parts, reading has passages, others have none
MOCK_SUBSECTIONS = {
    "🎧 Listening": ["🎵 Part 1", "🎵 Part 2", "🎵 Part 3", "🎵 Part 4"],
    "📖 Reading":   ["📄 Passage 1", "📄 Passage 2", "📄 Passage 3"],
}

# ─────────────────────────────────────────────
#  DATABASE
# ─────────────────────────────────────────────
_pool = None

async def get_pool():
    global _pool
    if _pool is None:
        url = DATABASE_URL
        if "sslmode" not in url:
            url = url + "?sslmode=require"
        _pool = await asyncpg.create_pool(url, min_size=1, max_size=5)
    return _pool

async def init_db():
    p = await get_pool()
    async with p.acquire() as c:
        await c.execute("""
            CREATE TABLE IF NOT EXISTS students (
                user_id      BIGINT PRIMARY KEY,
                username     TEXT DEFAULT '',
                full_name    TEXT DEFAULT '',
                day_type     TEXT NOT NULL,
                lesson_time  TEXT NOT NULL,
                joined_at    TIMESTAMP DEFAULT NOW()
            )
        """)
        await c.execute("""
            CREATE TABLE IF NOT EXISTS group_codes (
                day_type     TEXT NOT NULL,
                lesson_time  TEXT NOT NULL,
                code         TEXT NOT NULL,
                PRIMARY KEY (day_type, lesson_time)
            )
        """)
        await c.execute("""
            CREATE TABLE IF NOT EXISTS group_content (
                id          SERIAL PRIMARY KEY,
                day_type    TEXT NOT NULL,
                section     TEXT NOT NULL,
                title       TEXT NOT NULL,
                body        TEXT DEFAULT '',
                file_id     TEXT DEFAULT '',
                file_type   TEXT DEFAULT '',
                created_at  TIMESTAMP DEFAULT NOW()
            )
        """)
        await c.execute("""
            CREATE TABLE IF NOT EXISTS universal_categories (
                id       SERIAL PRIMARY KEY,
                name     TEXT NOT NULL UNIQUE,
                position INT DEFAULT 0
            )
        """)
        await c.execute("""
            CREATE TABLE IF NOT EXISTS universal_content (
                id          SERIAL PRIMARY KEY,
                category_id INT REFERENCES universal_categories(id) ON DELETE CASCADE,
                title       TEXT NOT NULL,
                body        TEXT DEFAULT '',
                file_id     TEXT DEFAULT '',
                file_type   TEXT DEFAULT '',
                created_at  TIMESTAMP DEFAULT NOW()
            )
        """)
        await c.execute("""
            CREATE TABLE IF NOT EXISTS mock_sections (
                id       SERIAL PRIMARY KEY,
                name     TEXT NOT NULL UNIQUE,
                position INT DEFAULT 0
            )
        """)
        await c.execute("""
            CREATE TABLE IF NOT EXISTS mock_content (
                id         SERIAL PRIMARY KEY,
                section_id INT REFERENCES mock_sections(id) ON DELETE CASCADE,
                subsection TEXT DEFAULT '',
                test_num   INT  DEFAULT 0,
                title      TEXT NOT NULL,
                body       TEXT DEFAULT '',
                file_id    TEXT DEFAULT '',
                file_type  TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        await c.execute("ALTER TABLE mock_content ADD COLUMN IF NOT EXISTS subsection TEXT DEFAULT ''")
        await c.execute("ALTER TABLE mock_content ADD COLUMN IF NOT EXISTS test_num INT DEFAULT 0")
        # Seed default mock sections
        for name, pos in [
            ("🎧 Listening", 1), ("📖 Reading", 2),
            ("✍️ Writing", 3),  ("🎤 Speaking", 4)
        ]:
            await c.execute(
                "INSERT INTO mock_sections(name,position) VALUES($1,$2) ON CONFLICT(name) DO NOTHING",
                name, pos)
        # Seed default universal categories
        for name, pos in [
            ("📚 Grammar", 1), ("📝 Vocabulary", 2),
            ("🗣️ Speaking Tips", 3), ("📄 Other", 4)
        ]:
            await c.execute(
                "INSERT INTO universal_categories(name,position) VALUES($1,$2) ON CONFLICT(name) DO NOTHING",
                name, pos)

# ── DB helpers ───────────────────────────────
async def db_get_student(uid):
    p = await get_pool()
    async with p.acquire() as c:
        r = await c.fetchrow("SELECT * FROM students WHERE user_id=$1", uid)
        return dict(r) if r else None

async def db_save_student(uid, uname, fname, day_type, lesson_time):
    p = await get_pool()
    async with p.acquire() as c:
        await c.execute("""
            INSERT INTO students(user_id,username,full_name,day_type,lesson_time)
            VALUES($1,$2,$3,$4,$5)
            ON CONFLICT(user_id) DO UPDATE
            SET username=$2, full_name=$3, day_type=$4, lesson_time=$5
        """, uid, uname or "", fname or "", day_type, lesson_time)

async def db_get_students(day_type=None, lesson_time=None):
    p = await get_pool()
    async with p.acquire() as c:
        if day_type and lesson_time:
            rows = await c.fetch(
                "SELECT * FROM students WHERE day_type=$1 AND lesson_time=$2",
                day_type, lesson_time)
        elif day_type:
            rows = await c.fetch("SELECT * FROM students WHERE day_type=$1", day_type)
        else:
            rows = await c.fetch("SELECT * FROM students")
        return [dict(r) for r in rows]

async def db_get_code(day_type, lesson_time):
    p = await get_pool()
    async with p.acquire() as c:
        r = await c.fetchrow(
            "SELECT code FROM group_codes WHERE day_type=$1 AND lesson_time=$2",
            day_type, lesson_time)
        return r["code"] if r else None

async def db_set_code(day_type, lesson_time, code):
    p = await get_pool()
    async with p.acquire() as c:
        await c.execute("""
            INSERT INTO group_codes(day_type,lesson_time,code) VALUES($1,$2,$3)
            ON CONFLICT(day_type,lesson_time) DO UPDATE SET code=$3
        """, day_type, lesson_time, code)

async def db_add_group(day_type, section, title, body="", file_id="", file_type=""):
    p = await get_pool()
    async with p.acquire() as c:
        await c.execute("""
            INSERT INTO group_content(day_type,section,title,body,file_id,file_type)
            VALUES($1,$2,$3,$4,$5,$6)
        """, day_type, section, title, body, file_id, file_type)

async def db_get_group(day_type, section):
    p = await get_pool()
    async with p.acquire() as c:
        rows = await c.fetch("""
            SELECT * FROM group_content
            WHERE day_type=$1 AND section=$2 ORDER BY created_at DESC
        """, day_type, section)
        return [dict(r) for r in rows]

async def db_del_group(cid):
    p = await get_pool()
    async with p.acquire() as c:
        await c.execute("DELETE FROM group_content WHERE id=$1", int(cid))

async def db_list_group():
    p = await get_pool()
    async with p.acquire() as c:
        rows = await c.fetch(
            "SELECT id,day_type,section,title FROM group_content ORDER BY day_type,section,created_at DESC")
        return [dict(r) for r in rows]

async def db_get_ucats():
    p = await get_pool()
    async with p.acquire() as c:
        rows = await c.fetch(
            "SELECT * FROM universal_categories ORDER BY position, id")
        return [dict(r) for r in rows]

async def db_add_ucat(name):
    p = await get_pool()
    async with p.acquire() as c:
        await c.execute(
            "INSERT INTO universal_categories(name) VALUES($1) ON CONFLICT(name) DO NOTHING", name)

async def db_del_ucat(cid):
    p = await get_pool()
    async with p.acquire() as c:
        await c.execute("DELETE FROM universal_categories WHERE id=$1", int(cid))

async def db_rename_ucat(cid, name):
    p = await get_pool()
    async with p.acquire() as c:
        await c.execute("UPDATE universal_categories SET name=$2 WHERE id=$1", int(cid), name)

async def db_add_ucontent(cat_id, title, body="", file_id="", file_type=""):
    p = await get_pool()
    async with p.acquire() as c:
        await c.execute("""
            INSERT INTO universal_content(category_id,title,body,file_id,file_type)
            VALUES($1,$2,$3,$4,$5)
        """, int(cat_id), title, body, file_id, file_type)

async def db_get_ucontent(cat_id):
    p = await get_pool()
    async with p.acquire() as c:
        rows = await c.fetch(
            "SELECT * FROM universal_content WHERE category_id=$1 ORDER BY created_at DESC",
            int(cat_id))
        return [dict(r) for r in rows]

async def db_del_ucontent(cid):
    p = await get_pool()
    async with p.acquire() as c:
        await c.execute("DELETE FROM universal_content WHERE id=$1", int(cid))

async def db_get_msecs():
    p = await get_pool()
    async with p.acquire() as c:
        rows = await c.fetch("SELECT * FROM mock_sections ORDER BY position, id")
        return [dict(r) for r in rows]

async def db_add_msec(name):
    p = await get_pool()
    async with p.acquire() as c:
        await c.execute(
            "INSERT INTO mock_sections(name) VALUES($1) ON CONFLICT(name) DO NOTHING", name)

async def db_del_msec(sid):
    p = await get_pool()
    async with p.acquire() as c:
        await c.execute("DELETE FROM mock_sections WHERE id=$1", int(sid))

async def db_rename_msec(sid, name):
    p = await get_pool()
    async with p.acquire() as c:
        await c.execute("UPDATE mock_sections SET name=$2 WHERE id=$1", int(sid), name)

async def db_add_mcontent(sec_id, title, subsection="", test_num=0, body="", file_id="", file_type=""):
    p = await get_pool()
    async with p.acquire() as c:
        await c.execute("""
            INSERT INTO mock_content(section_id,subsection,test_num,title,body,file_id,file_type)
            VALUES($1,$2,$3,$4,$5,$6,$7)
        """, int(sec_id), subsection, int(test_num), title, body, file_id, file_type)

async def db_get_mcontent(sec_id, subsection=None):
    p = await get_pool()
    async with p.acquire() as c:
        if subsection is not None:
            rows = await c.fetch(
                "SELECT * FROM mock_content WHERE section_id=$1 AND subsection=$2 ORDER BY test_num, created_at",
                int(sec_id), subsection)
        else:
            rows = await c.fetch(
                "SELECT * FROM mock_content WHERE section_id=$1 ORDER BY subsection, test_num, created_at",
                int(sec_id))
        return [dict(r) for r in rows]

async def db_get_mock_tests(sec_id, subsection):
    p = await get_pool()
    async with p.acquire() as c:
        rows = await c.fetch(
            "SELECT DISTINCT test_num FROM mock_content WHERE section_id=$1 AND subsection=$2 ORDER BY test_num",
            int(sec_id), subsection)
        return [r["test_num"] for r in rows]

async def db_del_mcontent(cid):
    p = await get_pool()
    async with p.acquire() as c:
        await c.execute("DELETE FROM mock_content WHERE id=$1", int(cid))

# ─────────────────────────────────────────────
#  KEYBOARDS
# ─────────────────────────────────────────────
def ikb(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)

def btn(text, data):
    return InlineKeyboardButton(text=text, callback_data=data)

def back_btn(data):
    return [btn("⬅️ Back", data)]

def main_menu_kb():
    return ikb([
        [btn("👥 Groups",     "m:groups")],
        [btn("🌐 Universal",  "m:universal")],
        [btn("📝 Mock Tests", "m:mock")],
    ])

def day_type_kb():
    return ikb([
        [btn("🔵 Odd Days",  "day:odd")],
        [btn("🟢 Even Days", "day:even")],
        back_btn("back:main"),
    ])

def times_kb(day_type):
    return ikb([
        [btn(f"🕐 {t}", f"time:{day_type}:{t}")]
        for t in LESSON_TIMES
    ] + [back_btn(f"day:{day_type}")])

def confirm_kb(day_type, t):
    return ikb([
        [btn("✅ Yes, join this group", f"join:{day_type}:{t}")],
        [btn("❌ Cancel",              f"day:{day_type}")],
    ])

def group_sec_kb(day_type):
    return ikb([
        [btn(lbl, f"gsec:{day_type}:{key}")]
        for lbl, key in GROUP_SECTIONS
    ] + [
        [btn("🔄 Change Group", "change_group")],
        back_btn("back:main")
    ])

async def univ_kb():
    cats = await db_get_ucats()
    return ikb([
        [btn(c["name"], f"ucat:{c['id']}")]
        for c in cats
    ] + [back_btn("back:main")])

async def mock_kb():
    secs = await db_get_msecs()
    return ikb([
        [btn(s["name"], f"msec:{s['id']}")]
        for s in secs
    ] + [back_btn("back:main")])

def simple_back_kb(data):
    return ikb([back_btn(data)])

# ─────────────────────────────────────────────
#  STATES
# ─────────────────────────────────────────────
class JoinGroup(StatesGroup):
    code = State()

class SetCode(StatesGroup):
    day_type    = State()
    lesson_time = State()
    code        = State()

class AddGroup(StatesGroup):
    section  = State()
    day_type = State()
    title    = State()
    content  = State()

class DelGroup(StatesGroup):
    cid = State()

class UCat(StatesGroup):
    waiting = State()

class UContent(StatesGroup):
    cat_id  = State()
    title   = State()
    content = State()

class DelUContent(StatesGroup):
    cid = State()

class MSec(StatesGroup):
    waiting = State()

class MContent(StatesGroup):
    sec_id     = State()
    title      = State()
    content    = State()

class AddMock(StatesGroup):
    sec_id     = State()
    subsection = State()
    test_num   = State()
    content    = State()

class DelMContent(StatesGroup):
    cid = State()

class Reminder(StatesGroup):
    day_type    = State()
    lesson_time = State()
    message     = State()

# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────
router = Router()
isa = lambda uid: uid == ADMIN_ID

async def send_item(bot, chat_id, item):
    title    = item.get("title", "")
    body     = item.get("body", "")
    file_id  = item.get("file_id", "")
    file_type = item.get("file_type", "")
    caption  = f"<b>{title}</b>" + (f"\n{body}" if body else "")
    try:
        if file_id and file_type == "photo":
            await bot.send_photo(chat_id=chat_id, photo=file_id, caption=caption, parse_mode="HTML")
        elif file_id and file_type == "document":
            await bot.send_document(chat_id=chat_id, document=file_id, caption=caption, parse_mode="HTML")
        elif file_id and file_type == "video":
            await bot.send_video(chat_id=chat_id, video=file_id, caption=caption, parse_mode="HTML")
        elif file_id and file_type == "audio":
            await bot.send_audio(chat_id=chat_id, audio=file_id, caption=caption, parse_mode="HTML")
        elif file_id and file_type == "voice":
            await bot.send_voice(chat_id=chat_id, voice=file_id, caption=caption, parse_mode="HTML")
        else:
            await bot.send_message(chat_id=chat_id, text=caption, parse_mode="HTML")
    except Exception as e:
        logging.warning(f"Failed to send item to {chat_id}: {e}")

async def save_content_from_msg(m: Message, state: FSMContext, save_fn, *args):
    if m.photo:
        await save_fn(*args, file_id=m.photo[-1].file_id, file_type="photo",
                      body=m.caption or "")
    elif m.document:
        await save_fn(*args, file_id=m.document.file_id, file_type="document",
                      body=m.caption or "")
    elif m.video:
        await save_fn(*args, file_id=m.video.file_id, file_type="video",
                      body=m.caption or "")
    elif m.audio:
        await save_fn(*args, file_id=m.audio.file_id, file_type="audio",
                      body=m.caption or "")
    elif m.voice:
        await save_fn(*args, file_id=m.voice.file_id, file_type="voice")
    elif m.text:
        body = "" if m.text == "/skip" else m.text
        await save_fn(*args, body=body)
    await state.clear()
    await m.answer("✅ Saved!")

# ─────────────────────────────────────────────
#  STUDENT HANDLERS
# ─────────────────────────────────────────────
@router.message(CommandStart())
async def cmd_start(m: Message, state: FSMContext):
    await state.clear()
    student = await db_get_student(m.from_user.id)
    if student:
        txt = (f"👋 Welcome back, <b>{m.from_user.first_name}</b>!\n"
               f"📅 <b>{'Odd' if student['day_type']=='odd' else 'Even'} Days</b> "
               f"⏰ <b>{student['lesson_time']}</b>\n\nChoose:")
    else:
        txt = f"👋 Hi <b>{m.from_user.first_name}</b>! Welcome to Everest.\n\nChoose a section:"
    await m.answer(txt, reply_markup=main_menu_kb())

@router.callback_query(F.data == "back:main")
async def back_main(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Choose a section:", reply_markup=main_menu_kb())

# ── Groups
@router.callback_query(F.data == "m:groups")
async def groups_menu(cb: CallbackQuery):
    student = await db_get_student(cb.from_user.id)
    if student:
        label = "Odd" if student["day_type"] == "odd" else "Even"
        await cb.message.edit_text(
            f"👥 <b>{label} Days</b> — ⏰ <b>{student['lesson_time']}</b>\n\nYour materials:",
            reply_markup=group_sec_kb(student["day_type"]))
    else:
        await cb.message.edit_text("Choose your group type:", reply_markup=day_type_kb())

@router.callback_query(F.data == "change_group")
async def change_group(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text(
        "🔄 <b>Change Group</b>\n\nChoose your new group type:",
        reply_markup=day_type_kb())

@router.callback_query(F.data.startswith("day:"))
async def pick_day(cb: CallbackQuery):
    day_type = cb.data[4:]
    label = "🔵 Odd Days" if day_type == "odd" else "🟢 Even Days"
    await cb.message.edit_text(f"{label}\n\nChoose your lesson time:",
                                reply_markup=times_kb(day_type))

@router.callback_query(F.data.startswith("time:"))
async def pick_time(cb: CallbackQuery):
    parts = cb.data.split(":")
    day_type = parts[1]
    t = ":".join(parts[2:])
    label = "Odd Days" if day_type == "odd" else "Even Days"
    await cb.message.edit_text(
        f"<b>{label}</b> at <b>{t}</b>\n\nConfirm joining this group?",
        reply_markup=confirm_kb(day_type, t))

@router.callback_query(F.data.startswith("join:"))
async def confirm_join(cb: CallbackQuery, state: FSMContext):
    parts = cb.data.split(":")
    day_type = parts[1]
    t = ":".join(parts[2:])
    await state.update_data(day_type=day_type, lesson_time=t)
    await state.set_state(JoinGroup.code)
    await cb.message.edit_text(
        "🔐 Enter the <b>access code</b> given by your teacher:",
        reply_markup=simple_back_kb("m:groups"))

@router.message(JoinGroup.code, F.text)
async def check_code(m: Message, state: FSMContext):
    d = await state.get_data()
    day_type, lesson_time = d["day_type"], d["lesson_time"]
    correct = await db_get_code(day_type, lesson_time)
    if correct is None:
        await state.clear()
        return await m.answer(
            "⚠️ No code set for this group yet. Ask your teacher.",
            reply_markup=main_menu_kb())
    if m.text.strip() != correct:
        return await m.answer("❌ Wrong code. Try again:")
    u = m.from_user
    await db_save_student(u.id, u.username, u.full_name, day_type, lesson_time)
    await state.clear()
    label = "Odd Days" if day_type == "odd" else "Even Days"
    await m.answer(
        f"✅ Joined <b>{label}</b> at <b>{lesson_time}</b>!\n\nYour materials:",
        reply_markup=group_sec_kb(day_type))

@router.callback_query(F.data.startswith("gsec:"))
async def group_section(cb: CallbackQuery):
    parts = cb.data.split(":")
    day_type, section = parts[1], parts[2]
    student = await db_get_student(cb.from_user.id)
    if not student or student["day_type"] != day_type:
        return await cb.answer("You are not in this group!", show_alert=True)
    label = SEC_LABELS.get(section, section)
    items = await db_get_group(day_type, section)
    if not items:
        return await cb.message.edit_text(
            f"<b>{label}</b>\n\n📭 Nothing here yet!",
            reply_markup=simple_back_kb(f"gsecback:{day_type}"))
    await cb.message.edit_text(
        f"<b>{label}</b> — Sending <b>{len(items)}</b> item(s)...",
        reply_markup=simple_back_kb(f"gsecback:{day_type}"))
    for item in items:
        await send_item(cb.bot, cb.from_user.id, item)

@router.callback_query(F.data.startswith("gsecback:"))
async def gsec_back(cb: CallbackQuery):
    day_type = cb.data[9:]
    label = "Odd" if day_type == "odd" else "Even"
    await cb.message.edit_text(
        f"👥 <b>{label} Days</b>\n\nYour materials:",
        reply_markup=group_sec_kb(day_type))

# ── Universal
@router.callback_query(F.data == "m:universal")
async def univ_menu(cb: CallbackQuery):
    await cb.message.edit_text(
        "🌐 <b>Universal Resources</b>\n\nChoose a category:",
        reply_markup=await univ_kb())

@router.callback_query(F.data.startswith("ucat:"))
async def univ_cat(cb: CallbackQuery):
    cat_id = int(cb.data[5:])
    cats = await db_get_ucats()
    cat = next((c for c in cats if c["id"] == cat_id), None)
    if not cat:
        return await cb.answer("Category not found.", show_alert=True)
    items = await db_get_ucontent(cat_id)
    if not items:
        return await cb.message.edit_text(
            f"<b>{cat['name']}</b>\n\n📭 Nothing here yet!",
            reply_markup=simple_back_kb("m:universal"))
    await cb.message.edit_text(
        f"<b>{cat['name']}</b> — Sending <b>{len(items)}</b> item(s)...",
        reply_markup=simple_back_kb("m:universal"))
    for item in items:
        await send_item(cb.bot, cb.from_user.id, item)

# ── Mock Tests
@router.callback_query(F.data == "m:mock")
async def mock_menu(cb: CallbackQuery):
    await cb.message.edit_text(
        "📝 <b>Mock Tests</b>\n\nChoose a section:",
        reply_markup=await mock_kb())

@router.callback_query(F.data.startswith("msec:"))
async def mock_sec(cb: CallbackQuery):
    sec_id = int(cb.data[5:])
    secs = await db_get_msecs()
    sec = next((s for s in secs if s["id"] == sec_id), None)
    if not sec:
        return await cb.answer("Section not found.", show_alert=True)
    subsecs = MOCK_SUBSECTIONS.get(sec["name"])
    if subsecs:
        # Show subsection buttons (Parts/Passages)
        kb = ikb([
            [btn(sub, f"msubsec:{sec_id}:{sub}")]
            for sub in subsecs
        ] + [back_btn("m:mock")])
        await cb.message.edit_text(
            f"<b>{sec['name']}</b>\n\nChoose section:",
            reply_markup=kb)
    else:
        # Writing/Speaking — show test numbers directly
        tests = await db_get_mock_tests(sec_id, "")
        if not tests:
            return await cb.message.edit_text(
                f"<b>{sec['name']}</b>\n\n📭 Nothing here yet!",
                reply_markup=simple_back_kb("m:mock"))
        kb = ikb([
            [btn(f"📝 Test {t}", f"mtest:{sec_id}::{t}")]
            for t in tests
        ] + [back_btn("m:mock")])
        await cb.message.edit_text(
            f"<b>{sec['name']}</b>\n\nChoose test:",
            reply_markup=kb)

@router.callback_query(F.data.startswith("msubsec:"))
async def mock_subsec(cb: CallbackQuery):
    parts = cb.data.split(":", 2)
    sec_id = int(parts[1])
    subsec = parts[2]
    secs = await db_get_msecs()
    sec = next((s for s in secs if s["id"] == sec_id), None)
    tests = await db_get_mock_tests(sec_id, subsec)
    if not tests:
        return await cb.message.edit_text(
            f"<b>{sec['name'] if sec else ''}</b> — <b>{subsec}</b>\n\n📭 Nothing here yet!",
            reply_markup=simple_back_kb(f"msec:{sec_id}"))
    kb = ikb([
        [btn(f"📝 Test {t}", f"mtest:{sec_id}:{subsec}:{t}")]
        for t in tests
    ] + [back_btn(f"msec:{sec_id}")])
    await cb.message.edit_text(
        f"<b>{sec['name'] if sec else ''}</b> — <b>{subsec}</b>\n\nChoose test:",
        reply_markup=kb)

@router.callback_query(F.data.startswith("mtest:"))
async def mock_test(cb: CallbackQuery):
    parts = cb.data.split(":")
    sec_id = int(parts[1])
    # parts[2] may be subsec (could contain spaces), parts[-1] is test_num
    test_num = int(parts[-1])
    subsec = ":".join(parts[2:-1])
    back_target = f"msubsec:{sec_id}:{subsec}" if subsec else f"msec:{sec_id}"
    items = await db_get_mcontent(sec_id, subsec if subsec else None)
    items = [i for i in items if i["test_num"] == test_num]
    if not items:
        return await cb.message.edit_text(
            f"📭 No content for Test {test_num} yet!",
            reply_markup=simple_back_kb(back_target))
    await cb.message.edit_text(
        f"📤 Sending <b>Test {test_num}</b> — <b>{len(items)}</b> file(s)...",
        reply_markup=simple_back_kb(back_target))
    for item in items:
        await send_item(cb.bot, cb.from_user.id, item)

# ─────────────────────────────────────────────
#  ADMIN HANDLERS
# ─────────────────────────────────────────────
@router.message(Command("admin"))
async def cmd_admin(m: Message):
    if not isa(m.from_user.id): return await m.answer("Not authorized.")
    await m.answer(
        "🔧 <b>Admin Panel</b>\n\n"
        "<b>Group Codes:</b>\n"
        "/set_code — Set join code\n\n"
        "<b>Group Content:</b>\n"
        "/add_group — Add content to a group\n"
        "/list_group — List all group content (with IDs)\n"
        "/del_group — Delete group content by ID\n\n"
        "<b>Universal:</b>\n"
        "/add_ucat — Add category\n"
        "/del_ucat — Delete category\n"
        "/rename_ucat — Rename category\n"
        "/add_ucontent — Add content to category\n"
        "/del_ucontent — Delete content by ID\n\n"
        "<b>Mock Tests:</b>\n"
        "/add_mock — Add mock test (button-based)\n"
        "/add_msec — Add section\n"
        "/del_msec — Delete section\n"
        "/rename_msec — Rename section\n"
        "/add_mcontent — Add content to section (legacy)\n"
        "/del_mcontent — Delete content by ID\n\n"
        "<b>Messages:</b>\n"
        "/reminder — Send reminder to group\n"
        "/broadcast — Send to ALL students\n"
        "/students — View registered students\n\n"
        "/cancel — Cancel current action"
    )

# ── Set code
@router.message(Command("set_code"))
async def cmd_set_code(m: Message, state: FSMContext):
    if not isa(m.from_user.id): return await m.answer("Not authorized.")
    await state.set_state(SetCode.day_type)
    await m.answer("Set join code.\n\nDay type: <code>odd</code> or <code>even</code>")

@router.message(SetCode.day_type, F.text)
async def sc_day(m: Message, state: FSMContext):
    v = m.text.strip().lower()
    if v not in ("odd", "even"):
        return await m.answer("Send <code>odd</code> or <code>even</code>")
    await state.update_data(day_type=v)
    await state.set_state(SetCode.lesson_time)
    await m.answer(f"Day: <b>{v}</b>\n\nLesson time: <code>9:30</code> / <code>14:30</code> / <code>16:30</code> / <code>18:30</code>")

@router.message(SetCode.lesson_time, F.text)
async def sc_time(m: Message, state: FSMContext):
    t = m.text.strip()
    if t not in LESSON_TIMES:
        return await m.answer(f"Valid times: {', '.join(LESSON_TIMES)}")
    await state.update_data(lesson_time=t)
    await state.set_state(SetCode.code)
    await m.answer(f"Time: <b>{t}</b>\n\nNow send the access code:")

@router.message(SetCode.code, F.text)
async def sc_save(m: Message, state: FSMContext):
    d = await state.get_data()
    await db_set_code(d["day_type"], d["lesson_time"], m.text.strip())
    await state.clear()
    await m.answer(
        f"✅ Code set!\n"
        f"Group: <b>{'Odd' if d['day_type']=='odd' else 'Even'} Days</b> "
        f"| Time: <b>{d['lesson_time']}</b>\n"
        f"Code: <code>{m.text.strip()}</code>")

# ── Add group content
def ag_group_kb():
    """Step 1: Choose Odd/Even + Time"""
    rows = []
    for t in LESSON_TIMES:
        rows.append([
            btn(f"🔵 Odd {t}", f"ag_grp:odd:{t}"),
            btn(f"🟢 Even {t}", f"ag_grp:even:{t}")
        ])
    rows.append([btn("❌ Cancel", "ag_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def ag_section_kb(day_type, lesson_time):
    """Step 2: Choose section"""
    return InlineKeyboardMarkup(inline_keyboard=[
        *[[btn(lbl, f"ag_sec:{day_type}:{lesson_time}:{key}")] for lbl, key in GROUP_SECTIONS],
        [btn("⬅️ Back", "ag_back:group"), btn("❌ Cancel", "ag_cancel")]
    ])

@router.message(Command("add_group"))
async def cmd_add_group(m: Message, state: FSMContext):
    if not isa(m.from_user.id): return await m.answer("Not authorized.")
    await state.set_state(AddGroup.day_type)
    await m.answer("Add group content.\n\nChoose group:", reply_markup=ag_group_kb())

@router.callback_query(F.data == "ag_cancel")
async def ag_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("❌ Cancelled.")

@router.callback_query(F.data == "ag_back:group")
async def ag_back_group(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AddGroup.day_type)
    await cb.message.edit_text("Add group content.\n\nChoose group:", reply_markup=ag_group_kb())

@router.callback_query(F.data.startswith("ag_grp:"), AddGroup.day_type)
async def ag_group_cb(cb: CallbackQuery, state: FSMContext):
    parts = cb.data.split(":")
    day_type = parts[1]
    lesson_time = ":".join(parts[2:])
    await state.update_data(day_type=day_type, lesson_time=lesson_time)
    await state.set_state(AddGroup.section)
    label = "🔵 Odd" if day_type == "odd" else "🟢 Even"
    await cb.message.edit_text(
        f"Group: <b>{label} Days — {lesson_time}</b>\n\nChoose section:",
        reply_markup=ag_section_kb(day_type, lesson_time))

@router.callback_query(F.data.startswith("ag_sec:"), AddGroup.section)
async def ag_section_cb(cb: CallbackQuery, state: FSMContext):
    parts = cb.data.split(":")
    day_type = parts[1]
    lesson_time = ":".join(parts[2:-1])
    section = parts[-1]
    valid = [k for _, k in GROUP_SECTIONS]
    if section not in valid:
        return await cb.answer("Invalid section.")
    await state.update_data(section=section)
    await state.set_state(AddGroup.title)
    label = "🔵 Odd" if day_type == "odd" else "🟢 Even"
    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [btn("⬅️ Back", f"ag_back:sec:{day_type}:{lesson_time}"), btn("❌ Cancel", "ag_cancel")]
    ])
    await cb.message.edit_text(
        f"Group: <b>{label} Days — {lesson_time}</b>\nSection: <b>{SEC_LABELS.get(section, section)}</b>\n\nSend the <b>title</b>:",
        reply_markup=back_kb)

@router.callback_query(F.data.startswith("ag_back:sec:"))
async def ag_back_sec(cb: CallbackQuery, state: FSMContext):
    parts = cb.data.split(":")
    day_type = parts[2]
    lesson_time = ":".join(parts[3:])
    await state.update_data(day_type=day_type, lesson_time=lesson_time)
    await state.set_state(AddGroup.section)
    label = "🔵 Odd" if day_type == "odd" else "🟢 Even"
    await cb.message.edit_text(
        f"Group: <b>{label} Days — {lesson_time}</b>\n\nChoose section:",
        reply_markup=ag_section_kb(day_type, lesson_time))

@router.message(AddGroup.title, F.text)
async def ag_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text.strip())
    await state.set_state(AddGroup.content)
    await m.answer("Title saved!\n\nSend content:\ntext / photo / document / video / audio / voice\n\nOr /cancel to stop.")

@router.message(AddGroup.content)
async def ag_content(m: Message, state: FSMContext):
    d = await state.get_data()
    day_type, section, title = d["day_type"], d["section"], d["title"]
    await save_content_from_msg(
        m, state,
        lambda **kw: db_add_group(day_type, section, title, **kw)
    )

# ── List / delete group content
@router.message(Command("list_group"))
async def cmd_list_group(m: Message):
    if not isa(m.from_user.id): return await m.answer("Not authorized.")
    rows = await db_list_group()
    if not rows: return await m.answer("No group content yet.")
    txt = "<b>Group Content</b>\n\n"
    for r in rows:
        day = "Odd" if r["day_type"] == "odd" else "Even"
        txt += f"ID <code>{r['id']}</code> | {day} | {r['section']} | {r['title']}\n"
    await m.answer(txt[:4000])

@router.message(Command("del_group"))
async def cmd_del_group(m: Message, state: FSMContext):
    if not isa(m.from_user.id): return await m.answer("Not authorized.")
    await state.set_state(DelGroup.cid)
    await m.answer("Send the content <b>ID</b> to delete.\nUse /list_group to find IDs.")

@router.message(DelGroup.cid, F.text)
async def do_del_group(m: Message, state: FSMContext):
    try:
        await db_del_group(int(m.text.strip()))
        await state.clear()
        await m.answer("✅ Deleted!")
    except Exception as e:
        await m.answer(f"Error: {e}\nSend a valid ID number.")

# ── Universal categories
@router.message(Command("add_ucat"))
async def cmd_add_ucat(m: Message, state: FSMContext):
    if not isa(m.from_user.id): return await m.answer("Not authorized.")
    await state.set_state(UCat.waiting)
    await state.update_data(action="add")
    await m.answer("Send the name for the new Universal category:")

@router.message(Command("del_ucat"))
async def cmd_del_ucat(m: Message, state: FSMContext):
    if not isa(m.from_user.id): return await m.answer("Not authorized.")
    cats = await db_get_ucats()
    if not cats: return await m.answer("No categories yet.")
    txt = "Universal categories:\n" + "\n".join(f"ID <code>{c['id']}</code> — {c['name']}" for c in cats)
    await m.answer(txt + "\n\nSend the <b>ID</b> to delete:")
    await state.set_state(UCat.waiting)
    await state.update_data(action="del")

@router.message(Command("rename_ucat"))
async def cmd_rename_ucat(m: Message, state: FSMContext):
    if not isa(m.from_user.id): return await m.answer("Not authorized.")
    cats = await db_get_ucats()
    if not cats: return await m.answer("No categories yet.")
    txt = "Universal categories:\n" + "\n".join(f"ID <code>{c['id']}</code> — {c['name']}" for c in cats)
    await m.answer(txt + "\n\nSend: <code>ID NewName</code>")
    await state.set_state(UCat.waiting)
    await state.update_data(action="rename")

@router.message(UCat.waiting, F.text)
async def ucat_handler(m: Message, state: FSMContext):
    d = await state.get_data()
    action = d.get("action", "")
    try:
        if action == "add":
            await db_add_ucat(m.text.strip())
            await state.clear()
            await m.answer(f"✅ Category '<b>{m.text.strip()}</b>' added!")
        elif action == "del":
            await db_del_ucat(int(m.text.strip()))
            await state.clear()
            await m.answer("✅ Category deleted!")
        elif action == "rename":
            parts = m.text.strip().split(" ", 1)
            if len(parts) < 2: return await m.answer("Send: <code>ID NewName</code>")
            await db_rename_ucat(int(parts[0]), parts[1])
            await state.clear()
            await m.answer(f"✅ Renamed to '<b>{parts[1]}</b>'!")
    except Exception as e:
        await m.answer(f"Error: {e}\nTry again or /cancel")

# ── Universal content
@router.message(Command("add_ucontent"))
async def cmd_add_ucontent(m: Message, state: FSMContext):
    if not isa(m.from_user.id): return await m.answer("Not authorized.")
    cats = await db_get_ucats()
    if not cats: return await m.answer("No categories yet. Use /add_ucat first.")
    txt = "Universal categories:\n" + "\n".join(f"ID <code>{c['id']}</code> — {c['name']}" for c in cats)
    await m.answer(txt + "\n\nSend the category <b>ID</b>:")
    await state.set_state(UContent.cat_id)

@router.message(UContent.cat_id, F.text)
async def ucontent_cat(m: Message, state: FSMContext):
    try:
        cat_id = int(m.text.strip())
        await state.update_data(cat_id=cat_id)
        await state.set_state(UContent.title)
        await m.answer("Category selected!\n\nSend the <b>title</b>:")
    except:
        await m.answer("Send a valid number ID.")

@router.message(UContent.title, F.text)
async def ucontent_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text.strip())
    await state.set_state(UContent.content)
    await m.answer("Title saved!\n\nSend content (text/photo/document/video/audio/voice) or /skip:")

@router.message(UContent.content)
async def ucontent_body(m: Message, state: FSMContext):
    d = await state.get_data()
    cat_id, title = d["cat_id"], d["title"]
    await save_content_from_msg(
        m, state,
        lambda **kw: db_add_ucontent(cat_id, title, **kw)
    )

@router.message(Command("del_ucontent"))
async def cmd_del_ucontent(m: Message, state: FSMContext):
    if not isa(m.from_user.id): return await m.answer("Not authorized.")
    p = await get_pool()
    async with p.acquire() as c:
        rows = await c.fetch("""
            SELECT uc.id, uc.title, cat.name
            FROM universal_content uc
            JOIN universal_categories cat ON cat.id=uc.category_id
            ORDER BY cat.name, uc.created_at DESC
        """)
    if not rows: return await m.answer("No universal content yet.")
    txt = "<b>Universal Content:</b>\n" + "\n".join(
        f"ID <code>{r['id']}</code> [{r['name']}] {r['title']}" for r in rows)
    await m.answer(txt[:4000] + "\n\nSend <b>ID</b> to delete:")
    await state.set_state(DelUContent.cid)

@router.message(DelUContent.cid, F.text)
async def do_del_ucontent(m: Message, state: FSMContext):
    try:
        await db_del_ucontent(int(m.text.strip()))
        await state.clear()
        await m.answer("✅ Deleted!")
    except Exception as e:
        await m.answer(f"Error: {e}\nSend a valid ID.")

# ── Mock sections
@router.message(Command("add_msec"))
async def cmd_add_msec(m: Message, state: FSMContext):
    if not isa(m.from_user.id): return await m.answer("Not authorized.")
    await state.set_state(MSec.waiting)
    await state.update_data(action="add")
    await m.answer("Send the name for the new Mock Test section:")

@router.message(Command("del_msec"))
async def cmd_del_msec(m: Message, state: FSMContext):
    if not isa(m.from_user.id): return await m.answer("Not authorized.")
    secs = await db_get_msecs()
    if not secs: return await m.answer("No mock sections yet.")
    txt = "Mock sections:\n" + "\n".join(f"ID <code>{s['id']}</code> — {s['name']}" for s in secs)
    await m.answer(txt + "\n\nSend <b>ID</b> to delete:")
    await state.set_state(MSec.waiting)
    await state.update_data(action="del")

@router.message(Command("rename_msec"))
async def cmd_rename_msec(m: Message, state: FSMContext):
    if not isa(m.from_user.id): return await m.answer("Not authorized.")
    secs = await db_get_msecs()
    if not secs: return await m.answer("No mock sections yet.")
    txt = "Mock sections:\n" + "\n".join(f"ID <code>{s['id']}</code> — {s['name']}" for s in secs)
    await m.answer(txt + "\n\nSend: <code>ID NewName</code>")
    await state.set_state(MSec.waiting)
    await state.update_data(action="rename")

@router.message(MSec.waiting, F.text)
async def msec_handler(m: Message, state: FSMContext):
    d = await state.get_data()
    action = d.get("action", "")
    try:
        if action == "add":
            await db_add_msec(m.text.strip())
            await state.clear()
            await m.answer(f"✅ Section '<b>{m.text.strip()}</b>' added!")
        elif action == "del":
            await db_del_msec(int(m.text.strip()))
            await state.clear()
            await m.answer("✅ Section deleted!")
        elif action == "rename":
            parts = m.text.strip().split(" ", 1)
            if len(parts) < 2: return await m.answer("Send: <code>ID NewName</code>")
            await db_rename_msec(int(parts[0]), parts[1])
            await state.clear()
            await m.answer(f"✅ Renamed to '<b>{parts[1]}</b>'!")
    except Exception as e:
        await m.answer(f"Error: {e}\nTry again or /cancel")

# ── Mock content
@router.message(Command("add_mcontent"))
async def cmd_add_mcontent(m: Message, state: FSMContext):
    if not isa(m.from_user.id): return await m.answer("Not authorized.")
    secs = await db_get_msecs()
    if not secs: return await m.answer("No sections yet. Use /add_msec first.")
    txt = "Mock sections:\n" + "\n".join(f"ID <code>{s['id']}</code> — {s['name']}" for s in secs)
    await m.answer(txt + "\n\nSend section <b>ID</b>:")
    await state.set_state(MContent.sec_id)

@router.message(MContent.sec_id, F.text)
async def mcontent_sec(m: Message, state: FSMContext):
    try:
        await state.update_data(sec_id=int(m.text.strip()))
        await state.set_state(MContent.title)
        await m.answer("Section selected!\n\nSend the <b>title</b>:")
    except:
        await m.answer("Send a valid number ID.")

@router.message(MContent.title, F.text)
async def mcontent_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text.strip())
    await state.set_state(MContent.content)
    await m.answer("Title saved!\n\nSend content or /skip:")

@router.message(MContent.content)
async def mcontent_body(m: Message, state: FSMContext):
    d = await state.get_data()
    sec_id, title = d["sec_id"], d["title"]
    await save_content_from_msg(
        m, state,
        lambda **kw: db_add_mcontent(sec_id, title, **kw)
    )

# ── /add_mock — button-based mock content upload
def am_section_kb(secs):
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn(s["name"], f"am_sec:{s['id']}:{s['name']}")]
        for s in secs
    ] + [[btn("❌ Cancel", "am_cancel")]])

def am_subsec_kb(sec_id, sec_name):
    subsecs = MOCK_SUBSECTIONS.get(sec_name, [])
    if not subsecs:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn(sub, f"am_sub:{sec_id}:{sub}")]
        for sub in subsecs
    ] + [[btn("⬅️ Back", "am_back:sec"), btn("❌ Cancel", "am_cancel")]])

def am_testnum_kb(sec_id, subsec, existing):
    next_num = max(existing, default=0) + 1
    nums = sorted(set(existing + [next_num]))
    rows = [[btn(f"📝 Test {n}" + (" ✚" if n == next_num else ""), f"am_test:{sec_id}:{subsec}:{n}")] for n in nums]
    rows.append([btn("⬅️ Back", f"am_back:sub:{sec_id}:{subsec}"), btn("❌ Cancel", "am_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@router.message(Command("add_mock"))
async def cmd_add_mock(m: Message, state: FSMContext):
    if not isa(m.from_user.id): return await m.answer("Not authorized.")
    await state.clear()
    secs = await db_get_msecs()
    if not secs: return await m.answer("No mock sections yet.")
    await state.set_state(AddMock.sec_id)
    await m.answer("➕ <b>Add Mock Test</b>\n\nChoose section:", reply_markup=am_section_kb(secs))

@router.callback_query(F.data == "am_cancel")
async def am_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("❌ Cancelled.")

@router.callback_query(F.data == "am_back:sec")
async def am_back_sec(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AddMock.sec_id)
    secs = await db_get_msecs()
    await cb.message.edit_text("➕ <b>Add Mock Test</b>\n\nChoose section:", reply_markup=am_section_kb(secs))

@router.callback_query(F.data.startswith("am_sec:"), AddMock.sec_id)
async def am_sec_cb(cb: CallbackQuery, state: FSMContext):
    parts = cb.data.split(":", 2)
    sec_id, sec_name = int(parts[1]), parts[2]
    await state.update_data(sec_id=sec_id, sec_name=sec_name)
    sub_kb = am_subsec_kb(sec_id, sec_name)
    if sub_kb:
        await state.set_state(AddMock.subsection)
        await cb.message.edit_text(
            f"Section: <b>{sec_name}</b>\n\nChoose part/passage:",
            reply_markup=sub_kb)
    else:
        # No subsection — go straight to test number
        await state.update_data(subsection="")
        await state.set_state(AddMock.test_num)
        existing = await db_get_mock_tests(sec_id, "")
        await cb.message.edit_text(
            f"Section: <b>{sec_name}</b>\n\nChoose test number (✚ = new):",
            reply_markup=am_testnum_kb(sec_id, "", existing))

@router.callback_query(F.data.startswith("am_back:sub:"))
async def am_back_sub(cb: CallbackQuery, state: FSMContext):
    parts = cb.data.split(":", 3)
    sec_id, subsec = int(parts[2]), parts[3]
    d = await state.get_data()
    sec_name = d.get("sec_name", "")
    sub_kb = am_subsec_kb(sec_id, sec_name)
    if sub_kb:
        await state.set_state(AddMock.subsection)
        await cb.message.edit_text(
            f"Section: <b>{sec_name}</b>\n\nChoose part/passage:",
            reply_markup=sub_kb)
    else:
        await am_back_sec(cb, state)

@router.callback_query(F.data.startswith("am_sub:"), AddMock.subsection)
async def am_sub_cb(cb: CallbackQuery, state: FSMContext):
    parts = cb.data.split(":", 2)
    sec_id, subsec = int(parts[1]), parts[2]
    await state.update_data(subsection=subsec)
    await state.set_state(AddMock.test_num)
    existing = await db_get_mock_tests(sec_id, subsec)
    d = await state.get_data()
    sec_name = d.get("sec_name", "")
    await cb.message.edit_text(
        f"Section: <b>{sec_name}</b> — <b>{subsec}</b>\n\nChoose test number (✚ = new):",
        reply_markup=am_testnum_kb(sec_id, subsec, existing))

@router.callback_query(F.data.startswith("am_test:"), AddMock.test_num)
async def am_test_cb(cb: CallbackQuery, state: FSMContext):
    parts = cb.data.split(":")
    sec_id = int(parts[1])
    subsec = ":".join(parts[2:-1])
    test_num = int(parts[-1])
    await state.update_data(test_num=test_num)
    await state.set_state(AddMock.content)
    d = await state.get_data()
    sec_name = d.get("sec_name", "")
    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[[btn("❌ Cancel", "am_cancel")]])
    await cb.message.edit_text(
        f"Section: <b>{sec_name}</b>{' — ' + subsec if subsec else ''}\n"
        f"Test: <b>Test {test_num}</b>\n\n"
        f"📤 Send the file (video/audio/photo/document/text):",
        reply_markup=cancel_kb)

@router.message(AddMock.content)
async def am_content(m: Message, state: FSMContext):
    d = await state.get_data()
    sec_id   = d["sec_id"]
    subsec   = d.get("subsection", "")
    test_num = d.get("test_num", 1)
    sec_name = d.get("sec_name", "")
    title    = f"Test {test_num}" + (f" — {subsec}" if subsec else "")
    await save_content_from_msg(
        m, state,
        lambda **kw: db_add_mcontent(sec_id, title, subsection=subsec, test_num=test_num, **kw)
    )
    label = f"{sec_name}{' — ' + subsec if subsec else ''} — Test {test_num}"
    await m.answer(f"✅ Uploaded to <b>{label}</b>!")

@router.message(Command("del_mcontent"))
async def cmd_del_mcontent(m: Message, state: FSMContext):
    if not isa(m.from_user.id): return await m.answer("Not authorized.")
    p = await get_pool()
    async with p.acquire() as c:
        rows = await c.fetch("""
            SELECT mc.id, mc.title, ms.name
            FROM mock_content mc
            JOIN mock_sections ms ON ms.id=mc.section_id
            ORDER BY ms.name, mc.created_at DESC
        """)
    if not rows: return await m.answer("No mock content yet.")
    txt = "<b>Mock Content:</b>\n" + "\n".join(
        f"ID <code>{r['id']}</code> [{r['name']}] {r['title']}" for r in rows)
    await m.answer(txt[:4000] + "\n\nSend <b>ID</b> to delete:")
    await state.set_state(DelMContent.cid)

@router.message(DelMContent.cid, F.text)
async def do_del_mcontent(m: Message, state: FSMContext):
    try:
        await db_del_mcontent(int(m.text.strip()))
        await state.clear()
        await m.answer("✅ Deleted!")
    except Exception as e:
        await m.answer(f"Error: {e}\nSend a valid ID.")

# ── Reminders
@router.message(Command("reminder"))
async def cmd_reminder(m: Message, state: FSMContext):
    if not isa(m.from_user.id): return await m.answer("Not authorized.")
    await state.set_state(Reminder.day_type)
    await m.answer(
        "📢 Send reminder.\n\n"
        "Day type: <code>odd</code> / <code>even</code> / <code>all</code>")

@router.message(Reminder.day_type, F.text)
async def rem_day(m: Message, state: FSMContext):
    v = m.text.strip().lower()
    if v not in ("odd", "even", "all"):
        return await m.answer("Send: <code>odd</code>, <code>even</code>, or <code>all</code>")
    await state.update_data(day_type=v)
    if v == "all":
        await state.update_data(lesson_time="all")
        await state.set_state(Reminder.message)
        await m.answer("Sending to ALL students.\n\nType your message:")
    else:
        await state.set_state(Reminder.lesson_time)
        await m.answer(f"Day: <b>{'Odd' if v=='odd' else 'Even'} Days</b>\n\nTime: <code>9:30</code> / <code>14:30</code> / <code>16:30</code> / <code>18:30</code> / <code>all</code>")

@router.message(Reminder.lesson_time, F.text)
async def rem_time(m: Message, state: FSMContext):
    t = m.text.strip()
    if t != "all" and t not in LESSON_TIMES:
        return await m.answer(f"Valid: {', '.join(LESSON_TIMES)} or <code>all</code>")
    await state.update_data(lesson_time=t)
    await state.set_state(Reminder.message)
    await m.answer("Now type your reminder message:")

@router.message(Reminder.message, F.text)
async def rem_send(m: Message, state: FSMContext):
    d = await state.get_data()
    day_type    = d.get("day_type", "all")
    lesson_time = d.get("lesson_time", "all")
    msg_text    = m.text
    await state.clear()
    students = await db_get_students(
        None if day_type == "all" else day_type,
        None if lesson_time == "all" else lesson_time
    )
    if not students:
        return await m.answer("⚠️ No students found in that group.")
    sent = failed = 0
    for s in students:
        try:
            await m.bot.send_message(
                s["user_id"],
                f"📢 <b>Message from your teacher:</b>\n\n{msg_text}",
                parse_mode="HTML")
            sent += 1
        except Exception:
            failed += 1
    await m.answer(f"✅ Done! Sent: <b>{sent}</b> | Failed: <b>{failed}</b>")

@router.message(Command("broadcast"))
async def cmd_broadcast(m: Message, state: FSMContext):
    if not isa(m.from_user.id): return await m.answer("Not authorized.")
    await state.update_data(day_type="all", lesson_time="all")
    await state.set_state(Reminder.message)
    await m.answer("Type your broadcast message (sent to ALL students):")

@router.message(Command("students"))
async def cmd_students(m: Message):
    if not isa(m.from_user.id): return await m.answer("Not authorized.")
    students = await db_get_students()
    if not students: return await m.answer("No students registered yet.")
    txt = f"<b>Students ({len(students)}):</b>\n\n"
    for s in students:
        name = s.get("full_name") or s.get("username") or str(s["user_id"])
        day  = "Odd" if s["day_type"] == "odd" else "Even"
        txt += f"• {name} | {day} Days | {s['lesson_time']}\n"
    await m.answer(txt[:4000])

@router.message(Command("cancel"))
async def cmd_cancel(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("✅ Cancelled.", reply_markup=main_menu_kb())

# ─────────────────────────────────────────────
#  MAIN ENTRY
# ─────────────────────────────────────────────
async def main():
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format="%(asctime)s %(levelname)s %(message)s"
    )
    log = logging.getLogger(__name__)

    if not BOT_TOKEN:
        log.error("BOT_TOKEN is not set!")
        sys.exit(1)
    if not DATABASE_URL:
        log.error("DATABASE_URL is not set!")
        sys.exit(1)

    log.info("Connecting to database...")
    try:
        await init_db()
        log.info("Database ready!")
    except Exception as e:
        log.error(f"Database error: {e}")
        sys.exit(1)

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    log.info("Bot starting...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())
