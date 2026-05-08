from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from keyboards import groups_keyboard, sections_keyboard, back_to_sections_keyboard
from database import get_content, get_announcements, log_access

router = Router()

SECTION_LABELS = {
    "task": "Tasks", "homework": "Homework", "material": "Materials",
    "book": "Books", "recorded_lesson": "Recorded Lessons", "lesson_file": "Lesson Files",
}
FILE_SENDERS = {"photo":"send_photo","document":"send_document","audio":"send_audio","video":"send_video","voice":"send_voice"}

@router.message(CommandStart())
async def cmd_start(message: Message):
    announcements = await get_announcements()
    intro = "<b>Welcome to Everest Learning Center!</b>\n\nChoose your group:"
    if announcements:
        intro += f"\n\nAnnouncement:\n{announcements[0]['message']}"
    await message.answer(intro, reply_markup=groups_keyboard(), parse_mode="HTML")

@router.callback_query(F.data.startswith("group:"))
async def handle_group(callback: CallbackQuery):
    group = callback.data.split(":")[1]
    await callback.message.edit_text(
        f"Group: <b>{group}</b>\n\nWhat would you like to access?",
        reply_markup=sections_keyboard(group), parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("section:"))
async def handle_section(callback: CallbackQuery):
    _, group, section = callback.data.split(":", 2)
    label = SECTION_LABELS.get(section, section)
    u = callback.from_user
    await log_access(u.id, u.username or "", u.full_name or "", group, section)
    items = await get_content(group, section)
    if not items:
        return await callback.message.edit_text(
            f"<b>{label}</b> — {group}\n\nNo content yet!",
            reply_markup=back_to_sections_keyboard(group), parse_mode="HTML"
        )
    await callback.message.edit_text(
        f"<b>{label}</b> — {group}\n\nSending {len(items)} item(s)...",
        reply_markup=back_to_sections_keyboard(group), parse_mode="HTML"
    )
    bot = callback.bot
    for item in items:
        caption = f"<b>{item['title']}</b>" + (f"\n{item['body']}" if item["body"] else "")
        ft, fid = item.get("file_type"), item.get("file_id")
        if fid and ft in FILE_SENDERS:
            method = getattr(bot, FILE_SENDERS[ft])
            kw = {"chat_id": callback.from_user.id, "caption": caption, "parse_mode": "HTML"}
            if ft == "photo": kw["photo"] = fid
            elif ft == "document": kw["document"] = fid
            elif ft == "audio": kw["audio"] = fid
            elif ft == "video": kw["video"] = fid
            elif ft == "voice": kw["voice"] = fid
            await method(**kw)
        else:
            await bot.send_message(chat_id=callback.from_user.id, text=caption, parse_mode="HTML")

@router.callback_query(F.data == "back:groups")
async def back_to_groups(callback: CallbackQuery):
    await callback.message.edit_text("Choose your group:", reply_markup=groups_keyboard())

@router.callback_query(F.data.startswith("back:sections:"))
async def back_to_sections(callback: CallbackQuery):
    group = callback.data.split(":", 2)[2]
    await callback.message.edit_text(
        f"Group: <b>{group}</b>\n\nWhat would you like to access?",
        reply_markup=sections_keyboard(group), parse_mode="HTML"
    )
