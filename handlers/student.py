from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from keyboards import levels_keyboard, groups_keyboard, sections_keyboard, back_to_sections_keyboard
from database import get_content, get_announcements

router = Router()

SECTION_LABELS = {
    "task": "📝 Tasks", "homework": "📚 Homework", "material": "📄 Materials",
    "book": "📖 Books", "recorded_lesson": "🎬 Recorded Lessons", "lesson_file": "📁 Lesson Files",
}
FILE_SENDERS = {"photo": "send_photo", "document": "send_document", "audio": "send_audio", "video": "send_video", "voice": "send_voice"}

@router.message(CommandStart())
async def cmd_start(message: Message):
    announcements = await get_announcements()
    intro = "👋 <b>Welcome to Everest Learning Center!</b>\n\nChoose your level:"
    if announcements:
        intro += f"\n\n📢 <b>Announcement:</b>\n{announcements[0]['message']}"
    await message.answer(intro, reply_markup=levels_keyboard(), parse_mode="HTML")

@router.callback_query(F.data.startswith("level:"))
async def handle_level(callback: CallbackQuery):
    level = callback.data.split(":")[1]
    await callback.message.edit_text(f"📚 <b>Level: {level}</b>\n\nChoose your group:", reply_markup=groups_keyboard(level), parse_mode="HTML")

@router.callback_query(F.data.startswith("group:"))
async def handle_group(callback: CallbackQuery):
    _, level, group = callback.data.split(":", 2)
    await callback.message.edit_text(f"📚 <b>{level}</b>  |  👥 <b>{group}</b>\n\nWhat would you like to access?", reply_markup=sections_keyboard(level, group), parse_mode="HTML")

@router.callback_query(F.data.startswith("section:"))
async def handle_section(callback: CallbackQuery):
    _, level, group, section = callback.data.split(":", 3)
    items = await get_content(level, group, section)
    label = SECTION_LABELS.get(section, section)
    if not items:
        return await callback.message.edit_text(f"<b>{label}</b>\n{level} / {group}\n\n📭 No content yet!", reply_markup=back_to_sections_keyboard(level, group), parse_mode="HTML")
    await callback.message.edit_text(f"<b>{label}</b> — {level} / {group}\n\nSending <b>{len(items)}</b> item(s)...", reply_markup=back_to_sections_keyboard(level, group), parse_mode="HTML")
    bot = callback.bot
    for item in items:
        caption = f"<b>{item['title']}</b>" + (f"\n{item['body']}" if item["body"] else "")
        ft, fid = item.get("file_type"), item.get("file_id")
        if fid and ft in FILE_SENDERS:
            method = getattr(bot, FILE_SENDERS[ft])
            kw = {"chat_id": callback.from_user.id, "caption": caption, "parse_mode": "HTML"}
            kw[ft if ft != "document" else "document"] = fid
            if ft == "photo": kw = {"chat_id": callback.from_user.id, "photo": fid, "caption": caption, "parse_mode": "HTML"}
            await method(**kw)
        else:
            await bot.send_message(chat_id=callback.from_user.id, text=caption, parse_mode="HTML")

@router.callback_query(F.data == "back:levels")
async def back_to_levels(callback: CallbackQuery):
    await callback.message.edit_text("Choose your level:", reply_markup=levels_keyboard())

@router.callback_query(F.data.startswith("back:groups:"))
async def back_to_groups(callback: CallbackQuery):
    level = callback.data.split(":", 2)[2]
    await callback.message.edit_text(f"📚 <b>Level: {level}</b>\n\nChoose your group:", reply_markup=groups_keyboard(level), parse_mode="HTML")

@router.callback_query(F.data.startswith("back:sections:"))
async def back_to_sections(callback: CallbackQuery):
    _, _, level, group = callback.data.split(":", 3)
    await callback.message.edit_text(f"📚 <b>{level}</b>  |  👥 <b>{group}</b>\n\nWhat would you like to access?", reply_markup=sections_keyboard(level, group), parse_mode="HTML")
