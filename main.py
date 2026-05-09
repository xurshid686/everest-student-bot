import asyncio, logging, sys, os
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

BOT_TOKEN    = os.getenv("BOT_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
ADMIN_ID     = int(os.getenv("ADMIN_ID", "0"))

# ════════════════════════════════════════════════════════════════
#  DATABASE
# ════════════════════════════════════════════════════════════════
_pool = None

async def pool():
    global _pool
    if _pool is None:
        url = DATABASE_URL + ("" if "sslmode" in DATABASE_URL else "?sslmode=require")
        _pool = await asyncpg.create_pool(url)
    return _pool

async def init_db():
    p = await pool()
    async with p.acquire() as c:
        await c.execute("""
        CREATE TABLE IF NOT EXISTS students (
            user_id    BIGINT PRIMARY KEY,
            username   TEXT,
            full_name  TEXT,
            day_type   TEXT,
            lesson_time TEXT,
            joined_at  TIMESTAMP DEFAULT NOW()
        )""")
        await c.execute("""
        CREATE TABLE IF NOT EXISTS group_content (
            id         SERIAL PRIMARY KEY,
            day_type   TEXT NOT NULL,
            section    TEXT NOT NULL,
            title      TEXT NOT NULL,
            body       TEXT,
            file_id    TEXT,
            file_type  TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )""")
        await c.execute("""
        CREATE TABLE IF NOT EXISTS universal_categories (
            id       SERIAL PRIMARY KEY,
            name     TEXT NOT NULL UNIQUE,
            position INT DEFAULT 0
        )""")
        await c.execute("""
        CREATE TABLE IF NOT EXISTS universal_content (
            id          SERIAL PRIMARY KEY,
            category_id INT REFERENCES universal_categories(id) ON DELETE CASCADE,
            title       TEXT NOT NULL,
            body        TEXT,
            file_id     TEXT,
            file_type   TEXT,
            created_at  TIMESTAMP DEFAULT NOW()
        )""")
        await c.execute("""
        CREATE TABLE IF NOT EXISTS mock_sections (
            id       SERIAL PRIMARY KEY,
            name     TEXT NOT NULL UNIQUE,
            position INT DEFAULT 0
        )""")
        await c.execute("""
        CREATE TABLE IF NOT EXISTS mock_content (
            id         SERIAL PRIMARY KEY,
            section_id INT REFERENCES mock_sections(id) ON DELETE CASCADE,
            title      TEXT NOT NULL,
            body       TEXT,
            file_id    TEXT,
            file_type  TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )""")
        await c.execute("""
        CREATE TABLE IF NOT EXISTS group_codes (
            id        SERIAL PRIMARY KEY,
            day_type  TEXT NOT NULL,
            lesson_time TEXT NOT NULL,
            code      TEXT NOT NULL,
            UNIQUE(day_type, lesson_time)
        )""")
        await c.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id         SERIAL PRIMARY KEY,
            day_type   TEXT,
            lesson_time TEXT,
            message    TEXT NOT NULL,
            sent_at    TIMESTAMP DEFAULT NOW()
        )""")
        # Default mock sections
        for name, pos in [("🎧 Listening",1),("📖 Reading",2),("✍️ Writing",3),("🎤 Speaking",4)]:
            await c.execute(
                "INSERT INTO mock_sections(name,position) VALUES($1,$2) ON CONFLICT(name) DO NOTHING",
                name, pos)
        # Default universal categories
        for name, pos in [("📚 Grammar",1),("📝 Vocabulary",2),("🗣️ Speaking Tips",3),("📄 Other",4)]:
            await c.execute(
                "INSERT INTO universal_categories(name,position) VALUES($1,$2) ON CONFLICT(name) DO NOTHING",
                name, pos)

# ── student helpers
async def save_student(uid, uname, fname, day_type, lesson_time):
    p = await pool()
    async with p.acquire() as c:
        await c.execute("""
            INSERT INTO students(user_id,username,full_name,day_type,lesson_time)
            VALUES($1,$2,$3,$4,$5)
            ON CONFLICT(user_id) DO UPDATE
            SET username=$2, full_name=$3, day_type=$4, lesson_time=$5
        """, uid, uname, fname, day_type, lesson_time)

async def get_student(uid):
    p = await pool()
    async with p.acquire() as c:
        row = await c.fetchrow("SELECT * FROM students WHERE user_id=$1", uid)
        return dict(row) if row else None

async def get_students_by_group(day_type, lesson_time=None):
    p = await pool()
    async with p.acquire() as c:
        if lesson_time:
            rows = await c.fetch("SELECT * FROM students WHERE day_type=$1 AND lesson_time=$2", day_type, lesson_time)
        else:
            rows = await c.fetch("SELECT * FROM students WHERE day_type=$1", day_type)
        return [dict(r) for r in rows]

async def get_all_students():
    p = await pool()
    async with p.acquire() as c:
        rows = await c.fetch("SELECT * FROM students")
        return [dict(r) for r in rows]

# ── group code helpers
async def get_code(day_type, lesson_time):
    p = await pool()
    async with p.acquire() as c:
        row = await c.fetchrow("SELECT code FROM group_codes WHERE day_type=$1 AND lesson_time=$2", day_type, lesson_time)
        return row["code"] if row else None

async def set_code(day_type, lesson_time, code):
    p = await pool()
    async with p.acquire() as c:
        await c.execute("""
            INSERT INTO group_codes(day_type,lesson_time,code) VALUES($1,$2,$3)
            ON CONFLICT(day_type,lesson_time) DO UPDATE SET code=$3
        """, day_type, lesson_time, code)

# ── group content helpers
async def add_group_content(day_type, section, title, body=None, file_id=None, file_type=None):
    p = await pool()
    async with p.acquire() as c:
        await c.execute(
            "INSERT INTO group_content(day_type,section,title,body,file_id,file_type) VALUES($1,$2,$3,$4,$5,$6)",
            day_type, section, title, body, file_id, file_type)

async def get_group_content(day_type, section):
    p = await pool()
    async with p.acquire() as c:
        rows = await c.fetch(
            "SELECT * FROM group_content WHERE day_type=$1 AND section=$2 ORDER BY created_at DESC",
            day_type, section)
        return [dict(r) for r in rows]

async def delete_group_content(cid):
    p = await pool()
    async with p.acquire() as c:
        await c.execute("DELETE FROM group_content WHERE id=$1", cid)

# ── universal helpers
async def get_univ_cats():
    p = await pool()
    async with p.acquire() as c:
        rows = await c.fetch("SELECT * FROM universal_categories ORDER BY position, id")
        return [dict(r) for r in rows]

async def add_univ_cat(name):
    p = await pool()
    async with p.acquire() as c:
        await c.execute("INSERT INTO universal_categories(name) VALUES($1) ON CONFLICT DO NOTHING", name)

async def del_univ_cat(cid):
    p = await pool()
    async with p.acquire() as c:
        await c.execute("DELETE FROM universal_categories WHERE id=$1", cid)

async def rename_univ_cat(cid, name):
    p = await pool()
    async with p.acquire() as c:
        await c.execute("UPDATE universal_categories SET name=$2 WHERE id=$1", cid, name)

async def add_univ_content(cat_id, title, body=None, file_id=None, file_type=None):
    p = await pool()
    async with p.acquire() as c:
        await c.execute(
            "INSERT INTO universal_content(category_id,title,body,file_id,file_type) VALUES($1,$2,$3,$4,$5)",
            cat_id, title, body, file_id, file_type)

async def get_univ_content(cat_id):
    p = await pool()
    async with p.acquire() as c:
        rows = await c.fetch(
            "SELECT * FROM universal_content WHERE category_id=$1 ORDER BY created_at DESC", cat_id)
        return [dict(r) for r in rows]

async def del_univ_content(cid):
    p = await pool()
    async with p.acquire() as c:
        await c.execute("DELETE FROM universal_content WHERE id=$1", cid)

# ── mock helpers
async def get_mock_secs():
    p = await pool()
    async with p.acquire() as c:
        rows = await c.fetch("SELECT * FROM mock_sections ORDER BY position, id")
        return [dict(r) for r in rows]

async def add_mock_sec(name):
    p = await pool()
    async with p.acquire() as c:
        await c.execute("INSERT INTO mock_sections(name) VALUES($1) ON CONFLICT DO NOTHING", name)

async def del_mock_sec(sid):
    p = await pool()
    async with p.acquire() as c:
        await c.execute("DELETE FROM mock_sections WHERE id=$1", sid)

async def rename_mock_sec(sid, name):
    p = await pool()
    async with p.acquire() as c:
        await c.execute("UPDATE mock_sections SET name=$2 WHERE id=$1", sid, name)

async def add_mock_content(sec_id, title, body=None, file_id=None, file_type=None):
    p = await pool()
    async with p.acquire() as c:
        await c.execute(
            "INSERT INTO mock_content(section_id,title,body,file_id,file_type) VALUES($1,$2,$3,$4,$5)",
            sec_id, title, body, file_id, file_type)

async def get_mock_content(sec_id):
    p = await pool()
    async with p.acquire() as c:
        rows = await c.fetch(
            "SELECT * FROM mock_content WHERE section_id=$1 ORDER BY created_at DESC", sec_id)
        return [dict(r) for r in rows]

async def del_mock_content(cid):
    p = await pool()
    async with p.acquire() as c:
        await c.execute("DELETE FROM mock_content WHERE id=$1", cid)

# ════════════════════════════════════════════════════════════════
#  KEYBOARDS
# ════════════════════════════════════════════════════════════════
LESSON_TIMES = ["9:30", "14:30", "16:30", "18:30"]
GROUP_SECTIONS = [
    ("📝 Homework",         "homework"),
    ("📖 Books",            "book"),
    ("🎬 Recorded Lessons", "recorded_lesson"),
    ("📁 Files",            "files"),
    ("📋 Board Notes",      "board"),
]

def kb(rows): return InlineKeyboardMarkup(inline_keyboard=rows)

def main_menu():
    return kb([
        [InlineKeyboardButton(text="👥 Groups",      callback_data="m:groups")],
        [InlineKeyboardButton(text="🌐 Universal",   callback_data="m:universal")],
        [InlineKeyboardButton(text="📝 Mock Tests",  callback_data="m:mock")],
    ])

def day_type_kb():
    return kb([
        [InlineKeyboardButton(text="🔵 Odd Days",  callback_data="day:odd")],
        [InlineKeyboardButton(text="🟢 Even Days", callback_data="day:even")],
        [InlineKeyboardButton(text="⬅️ Back",      callback_data="back:main")],
    ])

def times_kb(day_type):
    btns = [
        [InlineKeyboardButton(text=f"🕐 {t}", callback_data=f"time:{day_type}:{t}")]
        for t in LESSON_TIMES
    ]
    btns.append([InlineKeyboardButton(text="⬅️ Back", callback_data="m:groups")])
    return kb(btns)

def confirm_kb(day_type, t):
    return kb([
        [InlineKeyboardButton(text="✅ Yes, join", callback_data=f"join:{day_type}:{t}")],
        [InlineKeyboardButton(text="❌ Cancel",    callback_data=f"day:{day_type}")],
    ])

def group_sections_kb(day_type):
    btns = [
        [InlineKeyboardButton(text=lbl, callback_data=f"gsec:{day_type}:{key}")]
        for lbl, key in GROUP_SECTIONS
    ]
    btns.append([InlineKeyboardButton(text="⬅️ Back", callback_data="back:main")])
    return kb(btns)

async def universal_kb():
    cats = await get_univ_cats()
    btns = [
        [InlineKeyboardButton(text=c["name"], callback_data=f"ucat:{c['id']}")]
        for c in cats
    ]
    btns.append([InlineKeyboardButton(text="⬅️ Back", callback_data="back:main")])
    return kb(btns)

async def mock_kb():
    secs = await get_mock_secs()
    btns = [
        [InlineKeyboardButton(text=s["name"], callback_data=f"msec:{s['id']}")]
        for s in secs
    ]
    btns.append([InlineKeyboardButton(text="⬅️ Back", callback_data="back:main")])
    return kb(btns)

def back_kb(cb_data):
    return kb([[InlineKeyboardButton(text="⬅️ Back", callback_data=cb_data)]])

# ════════════════════════════════════════════════════════════════
#  STATES
# ════════════════════════════════════════════════════════════════
class JoinGroup(StatesGroup):
    waiting_code = State()

class AdminAdd(StatesGroup):
    section   = State()
    day_type  = State()
    title     = State()
    content   = State()

class AdminUniv(StatesGroup):
    action   = State()  # add_cat / del_cat / rename_cat / add_content / del_content
    cat_id   = State()
    title    = State()
    content  = State()

class AdminMock(StatesGroup):
    action   = State()
    sec_id   = State()
    title    = State()
    content  = State()

class AdminCode(StatesGroup):
    day_type    = State()
    lesson_time = State()
    code        = State()

class AdminReminder(StatesGroup):
    day_type    = State()
    lesson_time = State()
    message     = State()

# ════════════════════════════════════════════════════════════════
#  ROUTER
# ════════════════════════════════════════════════════════════════
router = Router()
is_admin = lambda uid: uid == ADMIN_ID

# helper: send file or text
async def send_item(bot, chat_id, item):
    cap = f"<b>{item['title']}</b>" + (f"\n{item['body']}" if item.get("body") else "")
    ft, fid = item.get("file_type"), item.get("file_id")
    SEND = {"photo":"send_photo","document":"send_document",
            "audio":"send_audio","video":"send_video","voice":"send_voice"}
    if fid and ft in SEND:
        fn = getattr(bot, SEND[ft])
        kw = {"chat_id": chat_id, "caption": cap, "parse_mode": "HTML", ft: fid}
        await fn(**kw)
    else:
        await bot.send_message(chat_id=chat_id, text=cap, parse_mode="HTML")

# ── /start
@router.message(CommandStart())
async def start(m: Message, state: FSMContext):
    await state.clear()
    student = await get_student(m.from_user.id)
    if student:
        txt = (f"👋 Welcome back, <b>{m.from_user.first_name}</b>!\n"
               f"📅 Group: <b>{student['day_type'].title()} Days</b> | ⏰ <b>{student['lesson_time']}</b>\n\n"
               f"Choose what you need:")
    else:
        txt = f"👋 Hi <b>{m.from_user.first_name}</b>! Welcome to Everest Learning Center.\n\nChoose a section:"
    await m.answer(txt, reply_markup=main_menu())

# ── Back to main
@router.callback_query(F.data == "back:main")
async def back_main(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Choose a section:", reply_markup=main_menu())

# ════════════════════════════════════════════════════════════════
#  GROUPS FLOW
# ════════════════════════════════════════════════════════════════
@router.callback_query(F.data == "m:groups")
async def groups_menu(cb: CallbackQuery):
    student = await get_student(cb.from_user.id)
    if student:
        return await cb.message.edit_text(
            f"👥 Your group: <b>{student['day_type'].title()} Days</b> — ⏰ <b>{student['lesson_time']}</b>\n\nAccess your materials:",
            reply_markup=group_sections_kb(student["day_type"]))
    await cb.message.edit_text("Choose your group type:", reply_markup=day_type_kb())

@router.callback_query(F.data.startswith("day:"))
async def pick_day(cb: CallbackQuery):
    day_type = cb.data[4:]
    label = "🔵 Odd Days" if day_type == "odd" else "🟢 Even Days"
    await cb.message.edit_text(
        f"{label}\n\nChoose your lesson time:",
        reply_markup=times_kb(day_type))

@router.callback_query(F.data.startswith("time:"))
async def pick_time(cb: CallbackQuery):
    _, day_type, t = cb.data.split(":")
    label = "Odd Days" if day_type == "odd" else "Even Days"
    await cb.message.edit_text(
        f"You selected: <b>{label}</b> at <b>{t}</b>\n\nDo you want to join this group?",
        reply_markup=confirm_kb(day_type, t))

@router.callback_query(F.data.startswith("join:"))
async def confirm_join(cb: CallbackQuery, state: FSMContext):
    _, day_type, t = cb.data.split(":")
    await state.update_data(day_type=day_type, lesson_time=t)
    await state.set_state(JoinGroup.waiting_code)
    await cb.message.edit_text(
        "🔐 Please enter the <b>access code</b> provided by your teacher:",
        reply_markup=back_kb("m:groups"))

@router.message(JoinGroup.waiting_code, F.text)
async def check_code(m: Message, state: FSMContext):
    d = await state.get_data()
    day_type, lesson_time = d["day_type"], d["lesson_time"]
    correct = await get_code(day_type, lesson_time)
    if correct is None:
        await m.answer("⚠️ No code set for this group yet. Ask your teacher.", reply_markup=main_menu())
        await state.clear()
        return
    if m.text.strip() != correct:
        return await m.answer("❌ Wrong code. Try again or press Back.")
    u = m.from_user
    await save_student(u.id, u.username or "", u.full_name or "", day_type, lesson_time)
    await state.clear()
    label = "Odd Days" if day_type == "odd" else "Even Days"
    await m.answer(
        f"✅ Welcome! You've joined <b>{label}</b> at <b>{lesson_time}</b>!\n\nAccess your materials:",
        reply_markup=group_sections_kb(day_type))

@router.callback_query(F.data.startswith("gsec:"))
async def group_section(cb: CallbackQuery):
    _, day_type, section = cb.data.split(":")
    student = await get_student(cb.from_user.id)
    if not student or student["day_type"] != day_type:
        return await cb.answer("You are not in this group!", show_alert=True)
    label = dict(GROUP_SECTIONS).get(section, section)
    items = await get_group_content(day_type, section)
    if not items:
        return await cb.message.edit_text(
            f"<b>{label}</b>\n\n📭 Nothing here yet!",
            reply_markup=back_kb(f"gsec_back:{day_type}"))
    await cb.message.edit_text(
        f"<b>{label}</b>\n\nSending <b>{len(items)}</b> item(s)...",
        reply_markup=back_kb(f"gsec_back:{day_type}"))
    for item in items:
        await send_item(cb.bot, cb.from_user.id, item)

@router.callback_query(F.data.startswith("gsec_back:"))
async def gsec_back(cb: CallbackQuery):
    day_type = cb.data[10:]
    await cb.message.edit_text("Choose a section:", reply_markup=group_sections_kb(day_type))

# ════════════════════════════════════════════════════════════════
#  UNIVERSAL FLOW
# ════════════════════════════════════════════════════════════════
@router.callback_query(F.data == "m:universal")
async def univ_menu(cb: CallbackQuery):
    await cb.message.edit_text("🌐 <b>Universal Resources</b>\n\nChoose a category:",
                                reply_markup=await universal_kb())

@router.callback_query(F.data.startswith("ucat:"))
async def univ_cat(cb: CallbackQuery):
    cat_id = int(cb.data[5:])
    cats = await get_univ_cats()
    cat = next((c for c in cats if c["id"] == cat_id), None)
    if not cat:
        return await cb.answer("Category not found.")
    items = await get_univ_content(cat_id)
    if not items:
        return await cb.message.edit_text(
            f"<b>{cat['name']}</b>\n\n📭 Nothing here yet!",
            reply_markup=back_kb("m:universal"))
    await cb.message.edit_text(
        f"<b>{cat['name']}</b>\n\nSending <b>{len(items)}</b> item(s)...",
        reply_markup=back_kb("m:universal"))
    for item in items:
        await send_item(cb.bot, cb.from_user.id, item)

# ════════════════════════════════════════════════════════════════
#  MOCK TESTS FLOW
# ════════════════════════════════════════════════════════════════
@router.callback_query(F.data == "m:mock")
async def mock_menu(cb: CallbackQuery):
    await cb.message.edit_text("📝 <b>Mock Tests</b>\n\nChoose a section:",
                                reply_markup=await mock_kb())

@router.callback_query(F.data.startswith("msec:"))
async def mock_sec(cb: CallbackQuery):
    sec_id = int(cb.data[5:])
    secs = await get_mock_secs()
    sec = next((s for s in secs if s["id"] == sec_id), None)
    if not sec:
        return await cb.answer("Section not found.")
    items = await get_mock_content(sec_id)
    if not items:
        return await cb.message.edit_text(
            f"<b>{sec['name']}</b>\n\n📭 Nothing here yet!",
            reply_markup=back_kb("m:mock"))
    await cb.message.edit_text(
        f"<b>{sec['name']}</b>\n\nSending <b>{len(items)}</b> item(s)...",
        reply_markup=back_kb("m:mock"))
    for item in items:
        await send_item(cb.bot, cb.from_user.id, item)

# ════════════════════════════════════════════════════════════════
#  ADMIN COMMANDS
# ════════════════════════════════════════════════════════════════
@router.message(Command("admin"))
async def cmd_admin(m: Message):
    if not is_admin(m.from_user.id): return await m.answer("Not authorized.")
    await m.answer(
        "🔧 <b>Admin Panel</b>\n\n"
        "<b>Group Content:</b>\n"
        "/add_group — Add content to a group section\n"
        "/show_group — List group content\n"
        "/del_group — Delete group content by ID\n\n"
        "<b>Group Codes:</b>\n"
        "/set_code — Set join code for a group/time\n\n"
        "<b>Universal:</b>\n"
        "/add_ucat — Add a Universal category\n"
        "/del_ucat — Delete a Universal category\n"
        "/rename_ucat — Rename a Universal category\n"
        "/add_ucontent — Add content to a category\n"
        "/del_ucontent — Delete Universal content by ID\n\n"
        "<b>Mock Tests:</b>\n"
        "/add_msec — Add a Mock Test section\n"
        "/del_msec — Delete a Mock Test section\n"
        "/rename_msec — Rename a Mock Test section\n"
        "/add_mcontent — Add content to a Mock section\n"
        "/del_mcontent — Delete Mock content by ID\n\n"
        "<b>Reminders:</b>\n"
        "/reminder — Send reminder to a group\n"
        "/broadcast — Send message to ALL students\n\n"
        "<b>Stats:</b>\n"
        "/students — View all students\n\n"
        "/cancel — Cancel current action"
    )

# ── Set join code
@router.message(Command("set_code"))
async def cmd_set_code(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id): return await m.answer("Not authorized.")
    await state.set_state(AdminCode.day_type)
    await m.answer("Set join code.\n\nSend day type: <code>odd</code> or <code>even</code>")

@router.message(AdminCode.day_type, F.text)
async def scode_day(m: Message, state: FSMContext):
    d = m.text.strip().lower()
    if d not in ("odd","even"): return await m.answer("Send: odd or even")
    await state.update_data(day_type=d)
    await state.set_state(AdminCode.lesson_time)
    await m.answer(f"Day: <b>{d}</b>\n\nSend lesson time (e.g. <code>9:30</code>):")

@router.message(AdminCode.lesson_time, F.text)
async def scode_time(m: Message, state: FSMContext):
    t = m.text.strip()
    if t not in LESSON_TIMES: return await m.answer(f"Valid times: {', '.join(LESSON_TIMES)}")
    await state.update_data(lesson_time=t)
    await state.set_state(AdminCode.code)
    await m.answer(f"Time: <b>{t}</b>\n\nNow send the access <b>code</b>:")

@router.message(AdminCode.code, F.text)
async def scode_save(m: Message, state: FSMContext):
    d = await state.get_data()
    await set_code(d["day_type"], d["lesson_time"], m.text.strip())
    await state.clear()
    await m.answer(f"✅ Code set!\nGroup: <b>{d['day_type'].title()} Days</b> | Time: <b>{d['lesson_time']}</b>\nCode: <code>{m.text.strip()}</code>")

# ── Add group content
@router.message(Command("add_group"))
async def cmd_add_group(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id): return await m.answer("Not authorized.")
    await state.set_state(AdminAdd.day_type)
    secs = "\n".join(f"  <code>{k}</code> — {lbl}" for lbl, k in GROUP_SECTIONS)
    await m.answer(f"Add group content.\n\nFirst, send section key:\n{secs}")

@router.message(AdminAdd.day_type, F.text)
async def agroup_section(m: Message, state: FSMContext):
    sec = m.text.strip().lower()
    if sec not in [k for _, k in GROUP_SECTIONS]:
        return await m.answer("Invalid section. Send one of: " + ", ".join(k for _, k in GROUP_SECTIONS))
    await state.update_data(section=sec)
    await state.set_state(AdminAdd.section)
    await m.answer(f"Section: <code>{sec}</code>\n\nSend day type: <code>odd</code> or <code>even</code>")

@router.message(AdminAdd.section, F.text)
async def agroup_day(m: Message, state: FSMContext):
    d = m.text.strip().lower()
    if d not in ("odd","even"): return await m.answer("Send: odd or even")
    await state.update_data(day_type=d)
    await state.set_state(AdminAdd.title)
    await m.answer(f"Day: <b>{d.title()} Days</b>\n\nSend the <b>title</b>:")

@router.message(AdminAdd.title, F.text)
async def agroup_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text)
    await state.set_state(AdminAdd.content)
    await m.answer("Title saved!\n\nNow send the content:\ntext, photo, document, video, audio, voice\n\nOr /skip for title only.")

@router.message(AdminAdd.content)
async def agroup_content(m: Message, state: FSMContext):
    d = await state.get_data()
    if m.text and m.text == "/skip":
        await add_group_content(d["day_type"], d["section"], d["title"])
    elif m.text:
        await add_group_content(d["day_type"], d["section"], d["title"], body=m.text)
    elif m.photo:
        await add_group_content(d["day_type"], d["section"], d["title"], body=m.caption or "", file_id=m.photo[-1].file_id, file_type="photo")
    elif m.document:
        await add_group_content(d["day_type"], d["section"], d["title"], body=m.caption or "", file_id=m.document.file_id, file_type="document")
    elif m.video:
        await add_group_content(d["day_type"], d["section"], d["title"], body=m.caption or "", file_id=m.video.file_id, file_type="video")
    elif m.audio:
        await add_group_content(d["day_type"], d["section"], d["title"], body=m.caption or "", file_id=m.audio.file_id, file_type="audio")
    elif m.voice:
        await add_group_content(d["day_type"], d["section"], d["title"], file_id=m.voice.file_id, file_type="voice")
    await state.clear()
    await m.answer("✅ Content saved!")

# ── Show / delete group content
@router.message(Command("show_group"))
async def cmd_show_group(m: Message):
    if not is_admin(m.from_user.id): return await m.answer("Not authorized.")
    p = await pool()
    async with p.acquire() as c:
        rows = await c.fetch("SELECT * FROM group_content ORDER BY day_type, section, created_at DESC")
    if not rows: return await m.answer("No group content yet.")
    txt = "<b>Group Content</b>\n\n"
    for r in rows:
        txt += f"ID <code>{r['id']}</code> | {r['day_type'].title()} | {r['section']} | {r['title']}\n"
    await m.answer(txt[:4000])

@router.message(Command("del_group"))
async def cmd_del_group(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id): return await m.answer("Not authorized.")
    await state.set_state(AdminAdd.content)
    await state.update_data(section="__delete__")
    await m.answer("Send the content <b>ID</b> to delete (use /show_group to find IDs):")

# ── Universal category management
@router.message(Command("add_ucat"))
async def cmd_add_ucat(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id): return await m.answer("Not authorized.")
    await state.set_state(AdminUniv.action)
    await state.update_data(action="add_cat")
    await m.answer("Send the name for the new Universal category:")

@router.message(Command("del_ucat"))
async def cmd_del_ucat(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id): return await m.answer("Not authorized.")
    cats = await get_univ_cats()
    txt = "Universal categories:\n" + "\n".join(f"ID <code>{c['id']}</code> — {c['name']}" for c in cats)
    await m.answer(txt + "\n\nSend the ID to delete:")
    await state.set_state(AdminUniv.action)
    await state.update_data(action="del_cat")

@router.message(Command("rename_ucat"))
async def cmd_rename_ucat(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id): return await m.answer("Not authorized.")
    cats = await get_univ_cats()
    txt = "Universal categories:\n" + "\n".join(f"ID <code>{c['id']}</code> — {c['name']}" for c in cats)
    await m.answer(txt + "\n\nSend: <code>ID NewName</code>")
    await state.set_state(AdminUniv.action)
    await state.update_data(action="rename_cat")

@router.message(Command("add_ucontent"))
async def cmd_add_ucontent(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id): return await m.answer("Not authorized.")
    cats = await get_univ_cats()
    txt = "Universal categories:\n" + "\n".join(f"ID <code>{c['id']}</code> — {c['name']}" for c in cats)
    await m.answer(txt + "\n\nSend the category ID:")
    await state.set_state(AdminUniv.action)
    await state.update_data(action="add_content")

@router.message(Command("del_ucontent"))
async def cmd_del_ucontent(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id): return await m.answer("Not authorized.")
    p = await pool()
    async with p.acquire() as c:
        rows = await c.fetch("SELECT uc.id, uc.title, cat.name FROM universal_content uc JOIN universal_categories cat ON cat.id=uc.category_id ORDER BY cat.name, uc.created_at DESC")
    if not rows: return await m.answer("No universal content yet.")
    txt = "Universal content:\n" + "\n".join(f"ID <code>{r['id']}</code> [{r['name']}] {r['title']}" for r in rows)
    await m.answer(txt[:4000] + "\n\nSend ID to delete:")
    await state.set_state(AdminUniv.action)
    await state.update_data(action="del_content")

# ── Mock section management
@router.message(Command("add_msec"))
async def cmd_add_msec(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id): return await m.answer("Not authorized.")
    await state.set_state(AdminMock.action)
    await state.update_data(action="add_sec")
    await m.answer("Send the name for the new Mock Test section:")

@router.message(Command("del_msec"))
async def cmd_del_msec(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id): return await m.answer("Not authorized.")
    secs = await get_mock_secs()
    txt = "Mock sections:\n" + "\n".join(f"ID <code>{s['id']}</code> — {s['name']}" for s in secs)
    await m.answer(txt + "\n\nSend the ID to delete:")
    await state.set_state(AdminMock.action)
    await state.update_data(action="del_sec")

@router.message(Command("rename_msec"))
async def cmd_rename_msec(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id): return await m.answer("Not authorized.")
    secs = await get_mock_secs()
    txt = "Mock sections:\n" + "\n".join(f"ID <code>{s['id']}</code> — {s['name']}" for s in secs)
    await m.answer(txt + "\n\nSend: <code>ID NewName</code>")
    await state.set_state(AdminMock.action)
    await state.update_data(action="rename_sec")

@router.message(Command("add_mcontent"))
async def cmd_add_mcontent(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id): return await m.answer("Not authorized.")
    secs = await get_mock_secs()
    txt = "Mock sections:\n" + "\n".join(f"ID <code>{s['id']}</code> — {s['name']}" for s in secs)
    await m.answer(txt + "\n\nSend section ID:")
    await state.set_state(AdminMock.action)
    await state.update_data(action="add_content")

@router.message(Command("del_mcontent"))
async def cmd_del_mcontent(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id): return await m.answer("Not authorized.")
    p = await pool()
    async with p.acquire() as c:
        rows = await c.fetch("SELECT mc.id, mc.title, ms.name FROM mock_content mc JOIN mock_sections ms ON ms.id=mc.section_id ORDER BY ms.name, mc.created_at DESC")
    if not rows: return await m.answer("No mock content yet.")
    txt = "Mock content:\n" + "\n".join(f"ID <code>{r['id']}</code> [{r['name']}] {r['title']}" for r in rows)
    await m.answer(txt[:4000] + "\n\nSend ID to delete:")
    await state.set_state(AdminMock.action)
    await state.update_data(action="del_content")

# ── Universal FSM handler
@router.message(AdminUniv.action)
async def handle_univ(m: Message, state: FSMContext):
    d = await state.get_data()
    action = d.get("action")
    if action == "add_cat":
        await add_univ_cat(m.text.strip())
        await state.clear()
        return await m.answer(f"✅ Category '<b>{m.text.strip()}</b>' added!")
    if action == "del_cat":
        try:
            await del_univ_cat(int(m.text.strip()))
            await state.clear()
            return await m.answer("✅ Category deleted!")
        except: return await m.answer("Send a valid ID number.")
    if action == "rename_cat":
        parts = m.text.strip().split(" ", 1)
        if len(parts) < 2: return await m.answer("Send: ID NewName")
        await rename_univ_cat(int(parts[0]), parts[1])
        await state.clear()
        return await m.answer(f"✅ Renamed to '<b>{parts[1]}</b>'!")
    if action == "add_content":
        cat_id = int(m.text.strip())
        await state.update_data(cat_id=cat_id, action="add_content_title")
        return await m.answer("Category selected!\n\nNow send the <b>title</b>:")
    if action == "add_content_title":
        await state.update_data(title=m.text, action="add_content_body")
        return await m.answer("Title saved!\n\nSend content (text/photo/document/video/audio/voice) or /skip:")
    if action == "add_content_body":
        cat_id = d.get("cat_id")
        title  = d.get("title")
        if m.text and m.text == "/skip":
            await add_univ_content(cat_id, title)
        elif m.text:
            await add_univ_content(cat_id, title, body=m.text)
        elif m.photo:
            await add_univ_content(cat_id, title, body=m.caption or "", file_id=m.photo[-1].file_id, file_type="photo")
        elif m.document:
            await add_univ_content(cat_id, title, body=m.caption or "", file_id=m.document.file_id, file_type="document")
        elif m.video:
            await add_univ_content(cat_id, title, body=m.caption or "", file_id=m.video.file_id, file_type="video")
        elif m.audio:
            await add_univ_content(cat_id, title, body=m.caption or "", file_id=m.audio.file_id, file_type="audio")
        elif m.voice:
            await add_univ_content(cat_id, title, file_id=m.voice.file_id, file_type="voice")
        await state.clear()
        return await m.answer("✅ Content saved!")
    if action == "del_content":
        try:
            await del_univ_content(int(m.text.strip()))
            await state.clear()
            return await m.answer("✅ Deleted!")
        except: return await m.answer("Send a valid ID number.")

# ── Mock FSM handler
@router.message(AdminMock.action)
async def handle_mock(m: Message, state: FSMContext):
    d = await state.get_data()
    action = d.get("action")
    if action == "add_sec":
        await add_mock_sec(m.text.strip())
        await state.clear()
        return await m.answer(f"✅ Section '<b>{m.text.strip()}</b>' added!")
    if action == "del_sec":
        try:
            await del_mock_sec(int(m.text.strip()))
            await state.clear()
            return await m.answer("✅ Section deleted!")
        except: return await m.answer("Send a valid ID number.")
    if action == "rename_sec":
        parts = m.text.strip().split(" ", 1)
        if len(parts) < 2: return await m.answer("Send: ID NewName")
        await rename_mock_sec(int(parts[0]), parts[1])
        await state.clear()
        return await m.answer(f"✅ Renamed to '<b>{parts[1]}</b>'!")
    if action == "add_content":
        sec_id = int(m.text.strip())
        await state.update_data(sec_id=sec_id, action="add_content_title")
        return await m.answer("Section selected!\n\nSend the <b>title</b>:")
    if action == "add_content_title":
        await state.update_data(title=m.text, action="add_content_body")
        return await m.answer("Title saved!\n\nSend content or /skip:")
    if action == "add_content_body":
        sec_id = d.get("sec_id")
        title  = d.get("title")
        if m.text and m.text == "/skip":
            await add_mock_content(sec_id, title)
        elif m.text:
            await add_mock_content(sec_id, title, body=m.text)
        elif m.photo:
            await add_mock_content(sec_id, title, body=m.caption or "", file_id=m.photo[-1].file_id, file_type="photo")
        elif m.document:
            await add_mock_content(sec_id, title, body=m.caption or "", file_id=m.document.file_id, file_type="document")
        elif m.video:
            await add_mock_content(sec_id, title, body=m.caption or "", file_id=m.video.file_id, file_type="video")
        elif m.audio:
            await add_mock_content(sec_id, title, body=m.caption or "", file_id=m.audio.file_id, file_type="audio")
        elif m.voice:
            await add_mock_content(sec_id, title, file_id=m.voice.file_id, file_type="voice")
        await state.clear()
        return await m.answer("✅ Content saved!")
    if action == "del_content":
        try:
            await del_mock_content(int(m.text.strip()))
            await state.clear()
            return await m.answer("✅ Deleted!")
        except: return await m.answer("Send a valid ID number.")

# ── Reminders
@router.message(Command("reminder"))
async def cmd_reminder(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id): return await m.answer("Not authorized.")
    await state.set_state(AdminReminder.day_type)
    await m.answer(
        "📢 Send reminder to a group.\n\n"
        "Send day type: <code>odd</code> or <code>even</code>\n"
        "(or <code>all</code> to send to everyone)")

@router.message(AdminReminder.day_type, F.text)
async def reminder_day(m: Message, state: FSMContext):
    d = m.text.strip().lower()
    if d not in ("odd","even","all"): return await m.answer("Send: odd, even, or all")
    await state.update_data(day_type=d)
    await state.set_state(AdminReminder.lesson_time)
    if d == "all":
        await state.update_data(lesson_time="all")
        await state.set_state(AdminReminder.message)
        await m.answer("Sending to ALL students.\n\nNow type your reminder message:")
    else:
        await m.answer(f"Day: <b>{d.title()} Days</b>\n\nSend lesson time or <code>all</code> for all times in this group:")

@router.message(AdminReminder.lesson_time, F.text)
async def reminder_time(m: Message, state: FSMContext):
    t = m.text.strip()
    if t != "all" and t not in LESSON_TIMES:
        return await m.answer(f"Valid: {', '.join(LESSON_TIMES)} or all")
    await state.update_data(lesson_time=t)
    await state.set_state(AdminReminder.message)
    await m.answer("Now type your reminder message\n(you can include homework, notes, anything):")

@router.message(AdminReminder.message, F.text)
async def reminder_send(m: Message, state: FSMContext):
    d = await state.get_data()
    day_type    = d["day_type"]
    lesson_time = d["lesson_time"]
    msg = m.text
    await state.clear()

    if day_type == "all":
        students = await get_all_students()
    elif lesson_time == "all":
        students = await get_students_by_group(day_type)
    else:
        students = await get_students_by_group(day_type, lesson_time)

    if not students:
        return await m.answer("No students found in that group.")

    sent, failed = 0, 0
    for s in students:
        try:
            await m.bot.send_message(s["user_id"],
                f"📢 <b>Reminder from your teacher:</b>\n\n{msg}",
                parse_mode="HTML")
            sent += 1
        except:
            failed += 1
    await m.answer(f"✅ Reminder sent!\n✅ Delivered: {sent}\n❌ Failed: {failed}")

# ── Broadcast
@router.message(Command("broadcast"))
async def cmd_broadcast(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id): return await m.answer("Not authorized.")
    await state.update_data(day_type="all", lesson_time="all")
    await state.set_state(AdminReminder.message)
    await m.answer("Type your broadcast message (sent to ALL students):")

# ── Students list
@router.message(Command("students"))
async def cmd_students(m: Message):
    if not is_admin(m.from_user.id): return await m.answer("Not authorized.")
    students = await get_all_students()
    if not students: return await m.answer("No students registered yet.")
    txt = f"<b>Students ({len(students)})</b>\n\n"
    for s in students:
        name = s["full_name"] or s["username"] or str(s["user_id"])
        txt += f"• {name} | {s['day_type'].title()} | {s['lesson_time']}\n"
    await m.answer(txt[:4000])

# ── Cancel
@router.message(Command("cancel"))
async def cmd_cancel(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("✅ Cancelled.", reply_markup=main_menu())

# ════════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════════
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
    dp  = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    print("Everest Bot is running!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
