from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Asosiy menyu tugmalari."""
    keyboard = [
        [
            KeyboardButton(text="💸 Harajat qo'shish"),
            KeyboardButton(text="💰 Daromad qo'shish")
        ],
        [
            KeyboardButton(text="🏦 Omonatlar"),
            KeyboardButton(text="📊 Balans va Hisobot")
        ],
        [
            KeyboardButton(text="📜 Oxirgi amallar"),
            KeyboardButton(text="ℹ️ Yordam")
        ]
    ]
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        input_field_placeholder="Quyidagi bo'limlardan birini tanlang..."
    )


def cancel_keyboard() -> ReplyKeyboardMarkup:
    """Amalni bekor qilish tugmasi."""
    keyboard = [
        [KeyboardButton(text="❌ Bekor qilish")]
    ]
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True
    )


def skip_or_cancel_keyboard() -> ReplyKeyboardMarkup:
    """Izohni o'tkazib yuborish yoki bekor qilish tugmasi."""
    keyboard = [
        [KeyboardButton(text="⏭ O'tkazib yuborish")],
        [KeyboardButton(text="❌ Bekor qilish")]
    ]
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True
    )


def expense_categories_keyboard() -> InlineKeyboardMarkup:
    """Harajat kategoriyalari (Inline)."""
    inline_keyboard = [
        [
            InlineKeyboardButton(text="🍔 Oziq-ovqat", callback_data="exp:Oziq-ovqat"),
            InlineKeyboardButton(text="🚕 Transport", callback_data="exp:Transport")
        ],
        [
            InlineKeyboardButton(text="🏠 Kommunal / Uy", callback_data="exp:Kommunal"),
            InlineKeyboardButton(text="👕 Kiyim-kechak", callback_data="exp:Kiyim-kechak")
        ],
        [
            InlineKeyboardButton(text="💊 Salomatlik", callback_data="exp:Salomatlik"),
            InlineKeyboardButton(text="☕️ Kafe / Dam olish", callback_data="exp:Ko'ngilochar")
        ],
        [
            InlineKeyboardButton(text="📱 Aloqa / Internet", callback_data="exp:Aloqa"),
            InlineKeyboardButton(text="📦 Boshqa harajat", callback_data="exp:Boshqa")
        ],
        [
            InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_action")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def income_categories_keyboard() -> InlineKeyboardMarkup:
    """Daromad manbalari (Inline)."""
    inline_keyboard = [
        [
            InlineKeyboardButton(text="💼 Oylik maosh", callback_data="inc:Oylik maosh"),
            InlineKeyboardButton(text="💻 Frilans / Qo'shimcha ish", callback_data="inc:Frilans")
        ],
        [
            InlineKeyboardButton(text="📈 Biznes / Savdo", callback_data="inc:Biznes"),
            InlineKeyboardButton(text="🎁 Sovg'a / Mukofot", callback_data="inc:Sovg'a")
        ],
        [
            InlineKeyboardButton(text="🏠 Ijara daromadi", callback_data="inc:Ijara"),
            InlineKeyboardButton(text="📦 Boshqa daromad", callback_data="inc:Boshqa")
        ],
        [
            InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_action")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def savings_menu_keyboard() -> InlineKeyboardMarkup:
    """Omonatlar bo'limi menyusi (Inline)."""
    inline_keyboard = [
        [
            InlineKeyboardButton(text="➕ Omonatga pul qo'shish", callback_data="savings:deposit")
        ],
        [
            InlineKeyboardButton(text="➖ Omonatdan pul yechish", callback_data="savings:withdraw")
        ],
        [
            InlineKeyboardButton(text="📜 Omonat tarixi", callback_data="savings:history")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def report_menu_keyboard() -> InlineKeyboardMarkup:
    """Hisobot ko'rish menyusi (Inline)."""
    inline_keyboard = [
        [
            InlineKeyboardButton(text="📅 Joriy oy hisoboti", callback_data="rep:monthly"),
            InlineKeyboardButton(text="💼 Umumiy balans", callback_data="rep:general")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
