import os
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from keyboards import admin_group_keyboard
from database import add_content, delete_content, show_content_by_section, add_announcement, get_stats

router = Router()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

class AddContent(StatesGroup):
    choosing_group  = State()
    waiting_title   = State()
    waiting_content = State()

class DeleteContent(StatesGroup):
    waiting_id = State()

class ShowContent(StatesGroup):
    waiting_section = State()

class Announce(StatesGroup):
    waiting_message = State()

def is_admin(uid): return uid == ADMIN_ID

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id): return await message.answer("Not authorized.")
    await message.answer(
        "<b>Admin Commands</b>\n\n"
        "/add_task /add_homework /add_material\n"
        "/add_book /add_recorded_lesson /add_lesson_file\n"
        "/show_content /delete_content\n"
        "/announcement /stats /cancel", parse_mode="HTML"
    )

async def start_add(message, state, section):
    if not is_admin(message.from_user.id): return await message.answer("Not authorized.")
    await state.update_data(section=section)
    await state.set_state(AddContent.choosing_group)
    await message.answer("Choose a group:", reply_markup=admin_group_keyboard())

@router.message(Command("add_task"))
async def c1(m, state: FSMContext): await start_add(m, state, "task")
@router.message(Command("add_homework"))
async def c2(m, state: FSMContext): await start_add(m, state, "homework")
@router.message(Command("add_material"))
async def c3(m, state: FSMContext): await start_add(m, state, "material")
@router.message(Command("add_book"))
async def c4(m, state: FSMContext): await start_add(m, state, "book")
@router.message(Command("add_recorded_lesson"))
async def c5(m, state: FSMContext): await start_add(m, state, "recorded_lesson")
@router.message(Command("add_lesson_file"))
async def c6(m, state: FSMContext): await start_add(m, state, "lesson_file")

@router.callback_query(AddContent.choosing_group, F.data.startswith("admin_group:"))
async def pick_group(cb: CallbackQuery, state: FSMContext):
    group = cb.data.split(":")[1]
    await state.update_data(group=group)
    await state.set_state(AddContent.waiting_title)
    await cb.message.edit_text(f"Group: <b>{group}</b>\n\nSend the title:", parse_mode="HTML")

@router.message(AddContent.waiting_title, F.text)
async def get_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text)
    await state.set_state(AddContent.waiting_content)
    await m.answer("Title saved! Now send the content (text, photo, document, audio, video, voice) or /skip", parse_mode="HTML")

@router.message(AddContent.waiting_content, F.text)
async def get_text(m: Message, state: FSMContext):
    d = await state.get_data()
    body = None if m.text == "/skip" else m.text
    await add_content(d["group"], d["section"], d["title"], body=body)
    await state.clear(); await m.answer("Saved!")

@router.message(AddContent.waiting_content, F.photo)
async def get_photo(m: Message, state: FSMContext):
    d = await state.get_data()
    await add_content(d["group"], d["section"], d["title"], body=m.caption or "", file_id=m.photo[-1].file_id, file_type="photo")
    await state.clear(); await m.answer("Photo saved!")

@router.message(AddContent.waiting_content, F.document)
async def get_doc(m: Message, state: FSMContext):
    d = await state.get_data()
    await add_content(d["group"], d["section"], d["title"], body=m.caption or m.document.file_name or "", file_id=m.document.file_id, file_type="document")
    await state.clear(); await m.answer("Document saved!")

@router.message(AddContent.waiting_content, F.audio)
async def get_audio(m: Message, state: FSMContext):
    d = await state.get_data()
    await add_content(d["group"], d["section"], d["title"], body=m.caption or "", file_id=m.audio.file_id, file_type="audio")
    await state.clear(); await m.answer("Audio saved!")

@router.message(AddContent.waiting_content, F.video)
async def get_video(m: Message, state: FSMContext):
    d = await state.get_data()
    await add_content(d["group"], d["section"], d["title"], body=m.caption or "", file_id=m.video.file_id, file_type="video")
    await state.clear(); await m.answer("Video saved!")

@router.message(AddContent.waiting_content, F.voice)
async def get_voice(m: Message, state: FSMContext):
    d = await state.get_data()
    await add_content(d["group"], d["section"], d["title"], file_id=m.voice.file_id, file_type="voice")
    await state.clear(); await m.answer("Voice saved!")

@router.message(Command("delete_content"))
async def cmd_delete(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id): return await m.answer("Not authorized.")
    await state.set_state(DeleteContent.waiting_id)
    await m.answer("Send the content ID to delete. Use /show_content to find IDs.")

@router.message(DeleteContent.waiting_id, F.text)
async def do_delete(m: Message, state: FSMContext):
    try:
        await delete_content(int(m.text.strip()))
        await state.clear(); await m.answer("Deleted!")
    except: await m.answer("Send a valid number.")

VALID = ["task","homework","material","book","recorded_lesson","lesson_file"]

@router.message(Command("show_content"))
async def cmd_show(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id): return await m.answer("Not authorized.")
    await state.set_state(ShowContent.waiting_section)
    await m.answer("Which section?\ntask | homework | material | book | recorded_lesson | lesson_file")

@router.message(ShowContent.waiting_section, F.text)
async def do_show(m: Message, state: FSMContext):
    s = m.text.strip().lower()
    if s not in VALID: return await m.answer("Invalid section.")
    rows = await show_content_by_section(s)
    await state.clear()
    if not rows: return await m.answer("No content found.")
    text = f"Section: {s}\n\n"
    for r in rows:
        text += f"ID: {r['id']} | {r['group_name']}\nTitle: {r['title']}\n{'File: '+r['file_type'] if r['file_id'] else 'Text only'}\n\n"
    await m.answer(text[:4000])

@router.message(Command("stats"))
async def cmd_stats(m: Message):
    if not is_admin(m.from_user.id): return await m.answer("Not authorized.")
    s = await get_stats()
    text = (
        f"<b>Bot Statistics</b>\n\n"
        f"Total unique students: <b>{s['total_users']}</b>\n"
        f"Accesses today: <b>{s['today']}</b>\n\n"
        f"<b>Most active groups:</b>\n"
    )
    for g in s["groups"]:
        text += f"  {g['group_name']}: {g['cnt']} accesses\n"
    text += "\n<b>Most accessed sections:</b>\n"
    for sec in s["sections"]:
        text += f"  {sec['section']}: {sec['cnt']} times\n"
    text += "\n<b>Recent students:</b>\n"
    for u in s["recent"]:
        name = u["full_name"] or u["username"] or f"ID:{u['user_id']}"
        text += f"  {name} ({u['last'][:10]})\n"
    await m.answer(text, parse_mode="HTML")

@router.message(Command("announcement"))
async def cmd_ann(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id): return await m.answer("Not authorized.")
    await state.set_state(Announce.waiting_message)
    await m.answer("Type your announcement:")

@router.message(Announce.waiting_message, F.text)
async def save_ann(m: Message, state: FSMContext):
    await add_announcement(m.text); await state.clear()
    await m.answer("Announcement saved!")

@router.message(Command("cancel"))
async def cmd_cancel(m: Message, state: FSMContext):
    await state.clear(); await m.answer("Cancelled.")

@router.callback_query(F.data == "admin_cancel")
async def cb_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear(); await cb.message.edit_text("Cancelled.")
