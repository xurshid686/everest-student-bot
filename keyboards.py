from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

LEVELS = ["Beginner", "Elementary", "Pre-IELTS", "IELTS Introduction", "IELTS Graduation"]
GROUPS = ["Hunters", "Hackers", "Assassins"]
SECTIONS = ["Tasks", "Homework", "Materials", "Books", "Recorded Lessons", "Lesson Files"]
SECTION_MAP = {
    "Tasks": "task", "Homework": "homework", "Materials": "material",
    "Books": "book", "Recorded Lessons": "recorded_lesson", "Lesson Files": "lesson_file",
}

def levels_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=lvl, callback_data=f"level:{lvl}")] for lvl in LEVELS])

def groups_keyboard(level):
    buttons = [[InlineKeyboardButton(text=grp, callback_data=f"group:{level}:{grp}")] for grp in GROUPS]
    buttons.append([InlineKeyboardButton(text="⬅️ Back to Levels", callback_data="back:levels")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def sections_keyboard(level, group):
    buttons = [[InlineKeyboardButton(text=sec, callback_data=f"section:{level}:{group}:{SECTION_MAP[sec]}")] for sec in SECTIONS]
    buttons.append([InlineKeyboardButton(text="⬅️ Back to Groups", callback_data=f"back:groups:{level}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def back_to_sections_keyboard(level, group):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Back to Sections", callback_data=f"back:sections:{level}:{group}")]])

def admin_level_keyboard():
    buttons = [[InlineKeyboardButton(text=lvl, callback_data=f"admin_level:{lvl}")] for lvl in LEVELS]
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="admin_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_group_keyboard(level):
    buttons = [[InlineKeyboardButton(text=grp, callback_data=f"admin_group:{level}:{grp}")] for grp in GROUPS]
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="admin_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
