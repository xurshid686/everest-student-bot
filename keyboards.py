from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

GROUPS = ["Hunters", "Hackers", "Assassins"]
SECTIONS = ["Tasks", "Homework", "Materials", "Books", "Recorded Lessons", "Lesson Files"]
SECTION_MAP = {
    "Tasks": "task", "Homework": "homework", "Materials": "material",
    "Books": "book", "Recorded Lessons": "recorded_lesson", "Lesson Files": "lesson_file",
}

def groups_keyboard():
    buttons = [[InlineKeyboardButton(text=grp, callback_data=f"group:{grp}")] for grp in GROUPS]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def sections_keyboard(group):
    buttons = [[InlineKeyboardButton(text=sec, callback_data=f"section:{group}:{SECTION_MAP[sec]}")] for sec in SECTIONS]
    buttons.append([InlineKeyboardButton(text="⬅️ Back to Groups", callback_data="back:groups")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def back_to_sections_keyboard(group):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Back to Sections", callback_data=f"back:sections:{group}")]
    ])

def admin_group_keyboard():
    buttons = [[InlineKeyboardButton(text=grp, callback_data=f"admin_group:{grp}")] for grp in GROUPS]
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="admin_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
