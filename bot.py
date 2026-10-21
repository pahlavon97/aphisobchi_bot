import asyncio
import io
import logging
import re
import sys
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, Optional

from aiogram import BaseMiddleware, Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, TelegramObject

import config
import database as db
import keyboards as kb
import voice_service
from states import ExpenseState, IncomeState, SavingsDepositState, SavingsWithdrawState


# Windows terminalida (cp1251 yoki cp866) xatolik chiqmasligi uchun UTF-8 ga moslash
if sys.platform.startswith("win"):
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

# Loglarni sozlash
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def parse_amount(text: str) -> Optional[float]:
    """
    Foydalanuvchi kiritgan summani tozalab, songa aylantiradi.
    Masalan:
    '50000' -> 50000.0
    '50 000' -> 50000.0
    '50k' -> 50000.0
    '1.5k' -> 1500.0
    '2 mln' -> 2000000.0
    '2.5mln' -> 2500000.0
    """
    text = text.strip().lower()
    text = text.replace(" ", "").replace(",", ".")

    try:
        if "mln" in text or ("m" in text and not text.endswith("ming")):
            cleaned = re.sub(r"[^\d.]", "", text)
            return float(cleaned) * 1_000_000
        elif "k" in text or "ming" in text:
            cleaned = re.sub(r"[^\d.]", "", text)
            return float(cleaned) * 1_000
        else:
            cleaned = re.sub(r"[^\d.]", "", text)
            val = float(cleaned)
            return val if val > 0 else None
    except (ValueError, TypeError):
        return None


# ==========================================
# XAVFSIZLIK MIDDLEWARE (FAQAT OILAVIY KIRISH)
# ==========================================

class FamilyAuthMiddleware(BaseMiddleware):
    """Faqat ruxsat berilgan foydalanuvchilar (Pahlavon va Ayoli) uchun tekshiruvchi middleware."""
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        # Guruh yoki superguruhlarda guruh a'zolarini bloklamaymiz
        if isinstance(event, Message) and event.chat.type in ("group", "supergroup"):
            return await handler(event, data)
        if isinstance(event, CallbackQuery) and event.message and event.message.chat.type in ("group", "supergroup"):
            return await handler(event, data)

        # Shaxsiy chatda (private) ruxsat berilganlar ro'yxatini tekshirish
        if user.id not in config.ALLOWED_USERS:
            if isinstance(event, Message):
                await event.answer(
                    f"🚫 <b>Kechirasiz, bu bot faqat oilaviy foydalanish uchun himoyalangan!</b>\n\n"
                    f"Sizning Telegram ID raqamingiz: <code>{user.id}</code>\n\n"
                    f"Foydalanish uchun ushbu ID raqamni bot egasiga (Pahlavonga) yuboring.",
                    parse_mode="HTML"
                )
            elif isinstance(event, CallbackQuery):
                await event.answer(
                    f"🚫 Ruxsat berilmagan! Sizning ID: {user.id}",
                    show_alert=True
                )
            return

        return await handler(event, data)


async def notify_partner(bot: Bot, current_user_id: int, current_user_name: str, action_text: str):
    """Ikkinchi oila a'zosiga real vaqtda xabar yuborish."""
    for uid in config.ALLOWED_USERS:
        if uid != current_user_id:
            try:
                msg = (
                    f"🔔 <b>Oilaviy byudjet yangilandi:</b>\n"
                    f"👤 <b>{current_user_name}</b> {action_text}"
                )
                await bot.send_message(uid, msg, parse_mode="HTML")
            except Exception:
                pass


# Dispatcher yaratish
dp = Dispatcher()
dp.message.middleware(FamilyAuthMiddleware())
dp.callback_query.middleware(FamilyAuthMiddleware())


# ==========================================
# OILAVIY BOSHQARUV BUYRUQLARI (/qoshish, /oilam)
# ==========================================

@dp.message(Command("qoshish"))
@dp.message(Command("add"))
async def cmd_add_family_member(message: Message):
    """Ayolingizning Telegram ID sini botga kiritish."""
    if message.from_user.id != config.ADMIN_ID:
        await message.answer("⚠️ Bu buyruq faqat bot admini uchun ruxsat etilgan.")
        return

    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer(
            "ℹ️ <b>Yangi oila a'zosini qo'shish tartibi:</b>\n\n"
            "1. Ayolingiz botga kirib /start tugmasini bosadi.\n"
            "2. Bot unga o'zining Telegram ID raqamini ko'rsatadi.\n"
            "3. Siz o'sha raqamni quyidagi formatda yozasiz:\n\n"
            "<code>/qoshish 123456789</code>",
            parse_mode="HTML"
        )
        return

    new_id = int(args[1])
    config.add_allowed_user(new_id)

    await message.answer(
        f"🎉 <b>Yangi a'zo muvaffaqiyatli qo'shildi!</b>\n\n"
        f"ID: <code>{new_id}</code>\n"
        f"Endi u botga kirib /start bosishi va umumiy oilaviy byudjetdan to'liq foydalanishi mumkin.",
        parse_mode="HTML"
    )

    try:
        await message.bot.send_message(
            new_id,
            "🎉 <b>Xush kelibsiz!</b>\n"
            "Sizga oilaviy hisob-kitob botidan foydalanishga ruxsat berildi.\n"
            "Boshlash uchun /start buyrug'ini bosing.",
            parse_mode="HTML"
        )
    except Exception:
        pass


@dp.message(Command("oilam"))
async def cmd_show_family(message: Message):
    """Ro'yxatdan o'tgan oila a'zolarini ko'rish."""
    users = db.get_all_users()
    text = "👥 <b>Oilaviy byudjet foydalanuvchilari:</b>\n\n"
    if users:
        for u in users:
            name = u["full_name"] or u["username"] or "A'zo"
            text += f"• 👤 <b>{name}</b> (ID: <code>{u['user_id']}</code>)\n"
    else:
        text += "Hozircha faqat siz ro'yxatdansiz.\n"

    text += (
        f"\n🔐 <i>Ruxsat etilganlar soni: {len(config.ALLOWED_USERS)} ta</i>\n"
        f"💡 <i>Yangi a'zo qo'shish: <code>/qoshish &lt;ID&gt;</code></i>"
    )
    await message.answer(text, parse_mode="HTML")


# ==========================================
# /start VA ASOSIY MENYU
# ==========================================

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    db.register_user(user.id, user.username or "", user.full_name or user.first_name)

    text = (
        f"Assalomu alaykum, <b>{user.first_name}</b>! 👋\n\n"
        f"<b>Umumiy Oilaviy Byudjet</b> hisob-kitob botiga xush kelibsiz.\n\n"
        f"Bu botda har ikkalangiz ham:\n"
        f"• 💸 <b>Harajatlarni</b> kiritishingiz (kim kiritgani ko'rinadi)\n"
        f"• 💰 <b>Daromadlarni</b> qayd etishingiz\n"
        f"• 🏦 <b>Omonat (jamg'arma)</b> mablag'laringizni kuzatishingiz\n"
        f"• 📊 <b>Umumiy oila balansi va oylik hisobotlarni</b> ko'rishingiz mumkin.\n\n"
        f"Boshlash uchun quyidagi bo'limlardan birini tanlang:"
    )
    await message.answer(text, reply_markup=kb.main_menu_keyboard(), parse_mode="HTML")


@dp.message(Command("help"))
@dp.message(F.text == "ℹ️ Yordam")
async def cmd_help(message: Message, state: FSMContext):
    await state.clear()
    text = (
        "📖 <b>Oilaviy botdan foydalanish bo'yicha qo'llanma:</b>\n\n"
        "1. 💸 <b>Harajat qo'shish:</b> Chiqimlaringizni summasi va toifasini tanlab kiritasiz. "
        "Harajat sizning ismingiz bilan saqlanadi va ikkinchi a'zoga xabar boradi.\n"
        "2. 💰 <b>Daromad qo'shish:</b> Tushgan oylik, savdo yoki boshqa tushumlarni kiritish.\n"
        "3. 🏦 <b>Omonatlar:</b> Oilaviy jamg'armalarga pul ajratish yoki yechib olish.\n"
        "4. 📊 <b>Balans va Hisobot:</b> Umumiy oila hamyoni, jami kapital va har bir a'zoning oylik hissasi.\n"
        "5. 📜 <b>Oxirgi amallar:</b> Eng so'nggi 8 ta moliyaviy amal (har bir amal egasining ismi bilan).\n\n"
        "👥 <b>Maxsus buyruqlar:</b>\n"
        "• <code>/oilam</code> — Oila a'zolarini ko'rish\n"
        "• <code>/qoshish &lt;ID&gt;</code> — Ayolingizni botga qo'shish (Admin uchun)\n"
        "• <code>/set_key &lt;kalit&gt;</code> — Ovozli xabarlar uchun Groq API kalitini kiritish\n\n"
        "🎙 <b>Ovozli xabar:</b> Botga to'g'ridan-to'g'ri ovoz yuborishingiz mumkin (masalan: <i>\"Bozorlikka 150 ming ketdi\"</i>)."
    )
    await message.answer(text, reply_markup=kb.main_menu_keyboard(), parse_mode="HTML")


@dp.message(Command("set_key"))
async def cmd_set_key(message: Message):
    """Groq API kalitini sozlash."""
    if message.from_user.id != config.ADMIN_ID:
        await message.answer("⚠️ Bu buyruq faqat bot egasi uchun ruxsat etilgan.")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer(
            "ℹ️ <b>Groq API kalitini sozlash:</b>\n\n"
            "Kalitni quyidagi formatda yuboring:\n"
            "<code>/set_key gsk_xxxxxxxxx</code>\n\n"
            "<i>(Agar kalit bo'lmasa, uni <a href='https://console.groq.com/keys'>console.groq.com/keys</a> dan bepul olishingiz mumkin)</i>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return

    key = args[1].strip()
    config.save_groq_key(key)
    await message.answer(
        "✅ <b>Groq API kaliti muvaffaqiyatli saqlandi!</b>\n\n"
        "Endi botga xohlagan paytingizda ovozli xabar (audio) yuborishingiz mumkin. "
        "U sizning gapingizni tinglab, summani avtomatik hisob-kitobga kiritadi! 🎙",
        parse_mode="HTML"
    )


# ==========================================
# OVOZLI XABARLARNI QABUL QILISH (VOICE MESSAGES)
# ==========================================

@dp.message(F.voice)
async def handle_voice_message(message: Message, state: FSMContext):
    await state.clear()
    user_name = message.from_user.first_name
    wait_msg = await message.answer("🎙 <i>Ovozli xabaringiz tinglanmoqda va tahlil qilinmoqda...</i>", parse_mode="HTML")

    parsed, recognized_text, err = await voice_service.process_voice_message(message.bot, message.voice)

    if err == "API_KEY_MISSING":
        await wait_msg.edit_text(
            "🎙 <b>Ovozli xabarlarni aniqlash uchun bepul API kalit kerak!</b>\n\n"
            "O'zbek tilidagi ovozni 100% aniq tushunish uchun <b>Groq API kaliti</b> kerak bo'ladi (mutlaqo bepul).\n\n"
            "🔑 <b>Qanday olinadi (1 daqiqada):</b>\n"
            "1. <a href='https://console.groq.com/keys'>console.groq.com/keys</a> saytiga kiring.\n"
            "2. Google hisobingiz orqali ro'yxatdan o'ting.\n"
            "3. <b>Create API Key</b> tugmasini bosib, kalitdan nusxa oling.\n"
            "4. Kalitni botga quyidagicha yuboring:\n\n"
            "<code>/set_key gsk_xxxxxx</code>\n\n"
            "Shundan so'ng ovozli xabarlar to'liq ishlay boshlaydi! 🚀",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return

    if err or not parsed:
        msg_text = "⚠️ <b>Ovozli xabarni to'liq tushunib bo'lmadi.</b>\n"
        if recognized_text:
            msg_text += f"\n<i>Eshitilgan matn:</i> \"<b>{recognized_text}</b>\"\n"
        if err and err != "API_KEY_MISSING":
            msg_text += f"\nIzoh: {err}\n"
        msg_text += "\n💡 <i>Iltimos, aniqroq qilib ayting (Masalan: \"Bozorlikka 120 ming ketdi\" yoki \"Taksiga 20 ming berdim\").</i>"
        await wait_msg.edit_text(msg_text, parse_mode="HTML")
        return

    # Muvaffaqiyatli tahlil qilindi!
    t_type = parsed.get("type", "expense")
    amount = float(parsed.get("amount", 0))
    category = parsed.get("category", "Boshqa")
    comment = parsed.get("comment", "")

    # Bazaga yozish
    db.add_transaction(
        user_id=message.from_user.id,
        user_name=user_name,
        trans_type=t_type,
        amount=amount,
        category=category,
        comment=comment
    )

    summary = db.get_balance_summary()

    if t_type == "expense":
        title = "💸 Harajat muvaffaqiyatli saqlandi!"
        sign = "-"
        action_verb = "harajat kiritdi"
    elif t_type == "income":
        title = "💰 Daromad muvaffaqiyatli saqlandi!"
        sign = "+"
        action_verb = "daromad kiritdi"
    elif t_type == "savings_add":
        title = "🏦 Omonatga mablag' qo'shildi!"
        sign = "📥 +"
        action_verb = "omonatga pul qo'shdi"
    elif t_type == "savings_withdraw":
        title = "📤 Omonatdan mablag' yechildi!"
        sign = "📤 -"
        action_verb = "omonatdan pul yechdi"
    else:
        title = "✅ Amal saqlandi!"
        sign = ""
        action_verb = "amal kiritdi"

    comment_line = f"\n📝 Izoh: <i>{comment}</i>" if comment else ""

    response_text = (
        f"🎙 <i>Eshitildi:</i> \"<b>{recognized_text}</b>\"\n\n"
        f"✅ <b>{title}</b>\n\n"
        f"Summa: <b>{sign}{db.format_money(amount)}</b>\n"
        f"🏷 Kategoriya: <b>{category}</b>\n"
        f"👤 Kiritdi: <b>{user_name}</b>"
        f"{comment_line}\n\n"
        f"💵 Oila hamyonida qoldi: <b>{db.format_money(summary['wallet_balance'])}</b>"
    )

    await wait_msg.edit_text(response_text, parse_mode="HTML")

    # Hamrohga xabar yuborish
    partner_comment = f" — <i>{comment}</i>" if comment else ""
    await notify_partner(
        message.bot,
        message.from_user.id,
        user_name,
        f"ovozli xabar orqali {action_verb}:\n"
        f"<b>{sign}{db.format_money(amount)}</b> ({category}{partner_comment})\n"
        f"💵 Yangilangan hamyon: <b>{db.format_money(summary['wallet_balance'])}</b>"
    )


# ==========================================
# GURUH VA SUPERGURUHLARDA ISHLASH (AI GROUP HANDLER)
# ==========================================

async def is_bot_mentioned_or_replied(message: Message, bot: Bot) -> bool:
    """Xabar botga qaratilganmi (bot tag qilingan yoki unga reply berilganmi) tekshiradi."""
    try:
        me = await bot.get_me()
        bot_username = (me.username or "").lower()
        bot_id = me.id
    except Exception:
        bot_username = "aphisobchi_bot"
        bot_id = None

    # 1. Reply botning xabariga qilingan bo'lsa
    if message.reply_to_message and message.reply_to_message.from_user:
        if bot_id and message.reply_to_message.from_user.id == bot_id:
            return True
        if bot_username and (message.reply_to_message.from_user.username or "").lower() == bot_username:
            return True

    # 2. Xabar matnida yoki captionda @bot_username bo'lsa
    text = (message.text or message.caption or "").lower()
    if bot_username and f"@{bot_username}" in text:
        return True

    # 3. Entities orqali tekshirish
    entities = message.entities or message.caption_entities or []
    for ent in entities:
        if ent.type == "mention":
            full_raw = message.text or message.caption or ""
            mention_text = full_raw[ent.offset:ent.offset + ent.length].lower()
            if bot_username and f"@{bot_username}" == mention_text:
                return True
        elif ent.type == "text_mention" and ent.user:
            if bot_id and ent.user.id == bot_id:
                return True

    return False


@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def handle_group_message(message: Message):
    """
    Guruhdagi xabarlarni kuzatish:
    Faqat bot belgilanganda (@aphisobchi_bot) yoki botga reply qilinganda
    AI xabarni tahlil qiladi va umumiy hisob-kitobga kiritadi.
    """
    # 1. Botga qaratilganligini tekshirish
    is_targeted = await is_bot_mentioned_or_replied(message, message.bot)
    if not is_targeted:
        # Botga tegishli bo'lmagan oddiy xabarlarni o'tkazib yuboramiz
        return

    user = message.from_user
    if not user:
        return

    user_name = user.full_name or user.username or "Guruh a'zosi"
    db.register_user(user.id, user.username or "", user_name)

    try:
        me = await message.bot.get_me()
        bot_username = me.username or "aphisobchi_bot"
    except Exception:
        bot_username = "aphisobchi_bot"

    # 2. Agar ovozli xabar bo'lsa (guruhda botga reply qilingan audio)
    if message.voice:
        wait_msg = await message.reply("🎙 <i>Guruhdagi ovozli xabar tinglanmoqda va AI tahlil qilmoqda...</i>", parse_mode="HTML")
        parsed, recognized_text, err = await voice_service.process_voice_message(message.bot, message.voice)
        if not parsed:
            err_msg = err or "Moliyaviy summa aniqlanmadi"
            await wait_msg.edit_text(
                f"⚠️ <b>Ovoz tahlil qilinmadi:</b> {err_msg}\n"
                f"{f'<i>Eshitildi:</i> {recognized_text}' if recognized_text else ''}\n\n"
                f"💡 <i>Iltimos, aniqroq ayting (masalan: \"Tushlikka 45 ming ketdi\").</i>",
                parse_mode="HTML"
            )
            return

        t_type = parsed.get("type", "expense")
        amount = float(parsed.get("amount", 0))
        category = parsed.get("category", "Boshqa")
        comment = parsed.get("comment", "")

        db.add_transaction(
            user_id=user.id,
            user_name=user_name,
            trans_type=t_type,
            amount=amount,
            category=category,
            comment=comment
        )
        summary = db.get_balance_summary()

        sign = "-" if t_type == "expense" else "+"
        title = "🔴 Harajat umumiy hisobga qo'shildi!" if t_type == "expense" else "🟢 Daromad umumiy hisobga qo'shildi!"
        comment_str = f"\n📝 <b>Izoh:</b> <i>{comment}</i>" if comment else ""
        cat_str = f"\n🏷 <b>Toifa:</b> {category}" if category else ""

        resp = (
            f"🎙 <i>Eshitildi:</i> \"<b>{recognized_text}</b>\"\n\n"
            f"✅ <b>{title}</b>\n\n"
            f"👤 <b>Kim:</b> <b>{user_name}</b>\n"
            f"💰 <b>Summa:</b> <b>{sign}{db.format_money(amount)}</b>"
            f"{cat_str}"
            f"{comment_str}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💵 <b>Oila erkin hamyoni:</b> <b>{db.format_money(summary['wallet_balance'])}</b>"
        )
        await wait_msg.edit_text(resp, parse_mode="HTML")
        return

    # 3. Matnli xabar bo'lsa
    raw_text = message.text or message.caption or ""
    # Bot username ni tozalash
    clean_text = re.sub(rf"@{bot_username}", "", raw_text, flags=re.IGNORECASE).strip()
    clean_text = re.sub(r"@[A-Za-z0-9_]+", "", clean_text).strip()

    # Buyruqlar tekshiruvi: /start, /help, /balans
    lower_clean = clean_text.lower()
    if lower_clean in ("/start", "/help", "help", "yordam", "salom"):
        await message.reply(
            f"👋 <b>Assalomu alaykum, {user.first_name}!</b>\n\n"
            f"Men guruhdagi xarajat va daromadlarni hisoblab boruvchi sun'iy intellekt (AI) botman. 🤖\n\n"
            f"Guruhda xarajat yoki daromad kiritish uchun meni shunchaki belgilab yozing:\n"
            f"👉 <code>@{bot_username} tushlikka 45 ming ketdi</code>\n"
            f"👉 <code>@{bot_username} 120 000 so'mga benzin quydim</code>\n"
            f"👉 <code>@{bot_username} oylik tushdi 3.5 mln</code>\n"
            f"👉 <code>@{bot_username} dorixonadan 85k ga dori oldik</code>\n\n"
            f"yoki mening xabarimga <b>javob (reply)</b> qilib yozing. AI avtomatik tarzda umumiy byudjetga qo'shadi! 📊",
            parse_mode="HTML"
        )
        return

    if lower_clean in ("/balans", "balans", "/hisobot", "hisobot"):
        summary = db.get_balance_summary()
        balans_text = (
            f"📊 <b>Umumiy Balans va Byudjet:</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 Jami daromad: <b>+{db.format_money(summary['total_income'])}</b>\n"
            f"💸 Jami harajat: <b>-{db.format_money(summary['total_expense'])}</b>\n"
            f"🏦 Omonat: <b>{db.format_money(summary['current_savings'])}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💵 <b>Erkin hamyon: {db.format_money(summary['wallet_balance'])}</b>\n"
            f"💎 <b>Sof kapital: {db.format_money(summary['total_net_worth'])}</b>"
        )
        await message.reply(balans_text, parse_mode="HTML")
        return

    if not clean_text:
        await message.reply(
            f"👋 <b>Meni belgiladingiz!</b>\n\n"
            f"Xarajat yoki daromadni yozing, masalan:\n"
            f"👉 <code>@{bot_username} tushlikka 45 ming ketdi</code>",
            parse_mode="HTML"
        )
        return

    # AI tahlili davomida yozish indikatori (typing)
    try:
        await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    except Exception:
        pass

    parsed, err = await voice_service.process_text_message(clean_text)

    if not parsed or not parsed.get("is_financial") or not parsed.get("amount"):
        await message.reply(
            f"⚠️ <b>Xabarda moliyaviy summa aniqlanmadi.</b>\n\n"
            f"Iltimos, summani aniq ko'rsatib yozing, masalan:\n"
            f"👉 <code>@{bot_username} tushlikka 45 ming ketdi</code>\n"
            f"👉 <code>@{bot_username} doriga 50 000 so'm berdim</code>",
            parse_mode="HTML"
        )
        return

    # Bazaga yozish
    t_type = parsed.get("type", "expense")
    amount = float(parsed.get("amount", 0))
    category = parsed.get("category", "Boshqa")
    comment = parsed.get("comment", clean_text)

    db.add_transaction(
        user_id=user.id,
        user_name=user_name,
        trans_type=t_type,
        amount=amount,
        category=category,
        comment=comment
    )

    summary = db.get_balance_summary()

    if t_type == "expense":
        icon = "🔴"
        title = "Harajat umumiy hisobga qo'shildi!"
        sign = "-"
        action_verb = "harajat kiritdi"
    elif t_type == "income":
        icon = "🟢"
        title = "Daromad umumiy hisobga qo'shildi!"
        sign = "+"
        action_verb = "daromad kiritdi"
    elif t_type == "savings_add":
        icon = "🔵"
        title = "Omonatga qo'shildi!"
        sign = "📥 +"
        action_verb = "omonatga qo'shdi"
    elif t_type == "savings_withdraw":
        icon = "🟡"
        title = "Omonatdan yechildi!"
        sign = "📤 -"
        action_verb = "omonatdan yechdi"
    else:
        icon = "⚪️"
        title = "Amal saqlandi!"
        sign = ""
        action_verb = "amal kiritdi"

    comment_line = f"\n📝 <b>Izoh:</b> <i>{comment}</i>" if comment else ""
    cat_line = f"\n🏷 <b>Toifa:</b> {category}" if category else ""

    resp = (
        f"{icon} <b>{title}</b>\n\n"
        f"👤 <b>Kim:</b> <b>{user_name}</b>\n"
        f"💰 <b>Summa:</b> <b>{sign}{db.format_money(amount)}</b>"
        f"{cat_line}"
        f"{comment_line}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💵 <b>Erkin hamyonda:</b> <b>{db.format_money(summary['wallet_balance'])}</b>"
    )

    await message.reply(resp, parse_mode="HTML")

    # Boshqa oila a'zolariga shaxsiy xabar yuborish
    partner_comment = f" — <i>{comment}</i>" if comment else ""
    await notify_partner(
        message.bot,
        user.id,
        user_name,
        f"guruh orqali {action_verb}:\n"
        f"<b>{sign}{db.format_money(amount)}</b> ({category}{partner_comment})\n"
        f"💵 Yangilangan hamyon: <b>{db.format_money(summary['wallet_balance'])}</b>"
    )


# ==========================================
# AMALLARNI BEKOR QILISH
# ==========================================

@dp.message(F.text == "❌ Bekor qilish")
async def process_cancel_text(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Amal bekor qilindi. Bosh menyudasiz.", reply_markup=kb.main_menu_keyboard())


@dp.callback_query(F.data == "cancel_action")
async def process_cancel_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await callback.message.answer("Amal bekor qilindi. Bosh menyudasiz.", reply_markup=kb.main_menu_keyboard())
    await callback.answer()


# ==========================================
# HARAJATLAR BO'LIMI (EXPENSES)
# ==========================================

@dp.message(F.text == "💸 Harajat qo'shish")
async def start_expense(message: Message, state: FSMContext):
    await state.set_state(ExpenseState.amount)
    await message.answer(
        "💸 <b>Harajat summasini kiriting:</b>\n"
        "<i>Masalan: 45000, 50k yoki 150 000</i>",
        reply_markup=kb.cancel_keyboard(),
        parse_mode="HTML"
    )


@dp.message(ExpenseState.amount)
async def process_expense_amount(message: Message, state: FSMContext):
    amount = parse_amount(message.text)
    if not amount or amount <= 0:
        await message.answer(
            "⚠️ Iltimos, to'g'ri summa kiriting!\n<i>Masalan: 50000 yoki 50k</i>",
            parse_mode="HTML"
        )
        return

    await state.update_data(amount=amount)
    await state.set_state(ExpenseState.category)
    await message.answer(
        f"Summa: <b>{db.format_money(amount)}</b>\n\n"
        f"Endi harajat kategoriyasini tanlang:",
        reply_markup=kb.expense_categories_keyboard(),
        parse_mode="HTML"
    )


@dp.callback_query(ExpenseState.category, F.data.startswith("exp:"))
async def process_expense_category(callback: CallbackQuery, state: FSMContext):
    category = callback.data.split(":", 1)[1]
    await state.update_data(category=category)
    await state.set_state(ExpenseState.comment)

    await callback.message.delete()
    await callback.message.answer(
        f"Kategoriya: <b>{category}</b>\n\n"
        f"Ushbu harajat uchun izoh kiriting (masalan: <i>Bozorlik</i> yoki <i>Tushlik</i>):\n"
        f"Yoki pastdagi <b>⏭ O'tkazib yuborish</b> tugmasini bosing:",
        reply_markup=kb.skip_or_cancel_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.message(ExpenseState.comment)
async def process_expense_comment(message: Message, state: FSMContext):
    comment = "" if message.text == "⏭ O'tkazib yuborish" else message.text.strip()
    data = await state.get_data()
    amount = data["amount"]
    category = data["category"]
    user_name = message.from_user.first_name

    # Bazaga yozish (foydalanuvchi nomi bilan)
    db.add_transaction(
        user_id=message.from_user.id,
        user_name=user_name,
        trans_type="expense",
        amount=amount,
        category=category,
        comment=comment
    )

    summary = db.get_balance_summary()
    await state.clear()

    comment_text = f"\nIzoh: <i>{comment}</i>" if comment else ""
    await message.answer(
        f"✅ <b>Harajat saqlandi!</b>\n\n"
        f"💸 Summa: <b>{db.format_money(amount)}</b>\n"
        f"🏷 Kategoriya: <b>{category}</b>\n"
        f"👤 Kiritdi: <b>{user_name}</b>"
        f"{comment_text}\n\n"
        f"💵 Oila hamyonida qoldi: <b>{db.format_money(summary['wallet_balance'])}</b>",
        reply_markup=kb.main_menu_keyboard(),
        parse_mode="HTML"
    )

    # Hamrohga bildirishnoma yuborish
    comment_info = f" — <i>{comment}</i>" if comment else ""
    await notify_partner(
        message.bot,
        message.from_user.id,
        user_name,
        f"yangi harajat kiritdi:\n"
        f"💸 <b>-{db.format_money(amount)}</b> ({category}{comment_info})\n"
        f"💵 Hamyonda qoldi: <b>{db.format_money(summary['wallet_balance'])}</b>"
    )


# ==========================================
# DAROMADLAR BO'LIMI (INCOME)
# ==========================================

@dp.message(F.text == "💰 Daromad qo'shish")
async def start_income(message: Message, state: FSMContext):
    await state.set_state(IncomeState.amount)
    await message.answer(
        "💰 <b>Daromad summasini kiriting:</b>\n"
        "<i>Masalan: 3000000, 3mln yoki 500k</i>",
        reply_markup=kb.cancel_keyboard(),
        parse_mode="HTML"
    )


@dp.message(IncomeState.amount)
async def process_income_amount(message: Message, state: FSMContext):
    amount = parse_amount(message.text)
    if not amount or amount <= 0:
        await message.answer(
            "⚠️ Iltimos, to'g'ri summa kiriting!\n<i>Masalan: 2000000 yoki 2mln</i>",
            parse_mode="HTML"
        )
        return

    await state.update_data(amount=amount)
    await state.set_state(IncomeState.category)
    await message.answer(
        f"Summa: <b>{db.format_money(amount)}</b>\n\n"
        f"Daromad manbasini tanlang:",
        reply_markup=kb.income_categories_keyboard(),
        parse_mode="HTML"
    )


@dp.callback_query(IncomeState.category, F.data.startswith("inc:"))
async def process_income_category(callback: CallbackQuery, state: FSMContext):
    category = callback.data.split(":", 1)[1]
    await state.update_data(category=category)
    await state.set_state(IncomeState.comment)

    await callback.message.delete()
    await callback.message.answer(
        f"Manba: <b>{category}</b>\n\n"
        f"Ushbu daromad uchun izoh kiriting (masalan: <i>Oylik maosh</i> yoki <i>Mukofot</i>):\n"
        f"Yoki <b>⏭ O'tkazib yuborish</b> tugmasini bosing:",
        reply_markup=kb.skip_or_cancel_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.message(IncomeState.comment)
async def process_income_comment(message: Message, state: FSMContext):
    comment = "" if message.text == "⏭ O'tkazib yuborish" else message.text.strip()
    data = await state.get_data()
    amount = data["amount"]
    category = data["category"]
    user_name = message.from_user.first_name

    db.add_transaction(
        user_id=message.from_user.id,
        user_name=user_name,
        trans_type="income",
        amount=amount,
        category=category,
        comment=comment
    )

    summary = db.get_balance_summary()
    await state.clear()

    comment_text = f"\nIzoh: <i>{comment}</i>" if comment else ""
    await message.answer(
        f"🎉 <b>Daromad muvaffaqiyatli saqlandi!</b>\n\n"
        f"💰 Summa: <b>+{db.format_money(amount)}</b>\n"
        f"💼 Manba: <b>{category}</b>\n"
        f"👤 Kiritdi: <b>{user_name}</b>"
        f"{comment_text}\n\n"
        f"💵 Yangi oilaviy hamyon balansi: <b>{db.format_money(summary['wallet_balance'])}</b>",
        reply_markup=kb.main_menu_keyboard(),
        parse_mode="HTML"
    )

    # Hamrohga bildirishnoma
    comment_info = f" — <i>{comment}</i>" if comment else ""
    await notify_partner(
        message.bot,
        message.from_user.id,
        user_name,
        f"yangi daromad kiritdi:\n"
        f"💰 <b>+{db.format_money(amount)}</b> ({category}{comment_info})\n"
        f"💵 Yangi oilaviy balans: <b>{db.format_money(summary['wallet_balance'])}</b>"
    )


# ==========================================
# OMONATLAR BO'LIMI (SAVINGS / JAMG'ARMA)
# ==========================================

@dp.message(F.text == "🏦 Omonatlar")
async def show_savings_menu(message: Message, state: FSMContext):
    await state.clear()
    summary = db.get_balance_summary()

    text = (
        f"🏦 <b>Oilaviy Omonatlar va Jamg'armalar</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💎 Omonatdagi jami zaxira: <b>{db.format_money(summary['current_savings'])}</b>\n"
        f"💵 Oila hamyonidagi erkin pul: <b>{db.format_money(summary['wallet_balance'])}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"Kerakli amalni tanlang:"
    )
    await message.answer(text, reply_markup=kb.savings_menu_keyboard(), parse_mode="HTML")


@dp.callback_query(F.data == "savings:deposit")
async def start_savings_deposit(callback: CallbackQuery, state: FSMContext):
    await state.set_state(SavingsDepositState.amount)
    await callback.message.delete()
    await callback.message.answer(
        "➕ <b>Omonatga qo'shmoqchi bo'lgan summani kiriting:</b>\n"
        "<i>Masalan: 500000 yoki 500k</i>",
        reply_markup=kb.cancel_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.message(SavingsDepositState.amount)
async def process_savings_deposit_amount(message: Message, state: FSMContext):
    amount = parse_amount(message.text)
    if not amount or amount <= 0:
        await message.answer("⚠️ Iltimos, to'g'ri summa kiriting!", parse_mode="HTML")
        return

    await state.update_data(amount=amount)
    await state.set_state(SavingsDepositState.comment)
    await message.answer(
        f"Summa: <b>{db.format_money(amount)}</b>\n\n"
        f"Omonat maqsadi yoki izohini yozing (masalan: <i>Mashina uchun</i>, <i>Sayohat</i> yoki <i>Zaxira</i>):\n"
        f"Yoki <b>⏭ O'tkazib yuborish</b> tugmasini bosing:",
        reply_markup=kb.skip_or_cancel_keyboard(),
        parse_mode="HTML"
    )


@dp.message(SavingsDepositState.comment)
async def process_savings_deposit_comment(message: Message, state: FSMContext):
    comment = "" if message.text == "⏭ O'tkazib yuborish" else message.text.strip()
    data = await state.get_data()
    amount = data["amount"]
    user_name = message.from_user.first_name

    db.add_transaction(
        user_id=message.from_user.id,
        user_name=user_name,
        trans_type="savings_add",
        amount=amount,
        category="Omonatga qo'shildi",
        comment=comment
    )

    summary = db.get_balance_summary()
    await state.clear()

    comment_text = f"\nMaqsad: <i>{comment}</i>" if comment else ""
    await message.answer(
        f"🏦 <b>Omonatga mablag' qo'shildi!</b>\n\n"
        f"📥 Qo'shilgan summa: <b>+{db.format_money(amount)}</b>\n"
        f"👤 Kiritdi: <b>{user_name}</b>"
        f"{comment_text}\n"
        f"💎 Omonatdagi jami pul: <b>{db.format_money(summary['current_savings'])}</b>\n"
        f"💵 Qolgan erkin hamyon: <b>{db.format_money(summary['wallet_balance'])}</b>",
        reply_markup=kb.main_menu_keyboard(),
        parse_mode="HTML"
    )

    # Hamrohga xabar
    await notify_partner(
        message.bot,
        message.from_user.id,
        user_name,
        f"omonatga mablag' qo'shdi:\n"
        f"📥 <b>+{db.format_money(amount)}</b>\n"
        f"💎 Omonatdagi jami pul: <b>{db.format_money(summary['current_savings'])}</b>"
    )


@dp.callback_query(F.data == "savings:withdraw")
async def start_savings_withdraw(callback: CallbackQuery, state: FSMContext):
    summary = db.get_balance_summary()

    if summary["current_savings"] <= 0:
        await callback.answer("⚠️ Hozircha omonatda mablag' mavjud emas!", show_alert=True)
        return

    await state.set_state(SavingsWithdrawState.amount)
    await callback.message.delete()
    await callback.message.answer(
        f"➖ <b>Omonatdan yechib olmoqchi bo'lgan summani kiriting:</b>\n"
        f"<i>Omonatdagi mavjud mablag': {db.format_money(summary['current_savings'])}</i>",
        reply_markup=kb.cancel_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.message(SavingsWithdrawState.amount)
async def process_savings_withdraw_amount(message: Message, state: FSMContext):
    amount = parse_amount(message.text)
    summary = db.get_balance_summary()

    if not amount or amount <= 0:
        await message.answer("⚠️ Iltimos, to'g'ri summa kiriting!", parse_mode="HTML")
        return

    if amount > summary["current_savings"]:
        await message.answer(
            f"⚠️ Siz ko'rsatgan summa omonatdagi mablag'dan ko'p!\n"
            f"Omonatdagi jami mablag': <b>{db.format_money(summary['current_savings'])}</b>\n"
            f"Qaytadan summa kiriting:",
            parse_mode="HTML"
        )
        return

    await state.update_data(amount=amount)
    await state.set_state(SavingsWithdrawState.comment)
    await message.answer(
        f"Yechilayotgan summa: <b>{db.format_money(amount)}</b>\n\n"
        f"Sabab yoki izohni yozing:\n"
        f"Yoki <b>⏭ O'tkazib yuborish</b> tugmasini bosing:",
        reply_markup=kb.skip_or_cancel_keyboard(),
        parse_mode="HTML"
    )


@dp.message(SavingsWithdrawState.comment)
async def process_savings_withdraw_comment(message: Message, state: FSMContext):
    comment = "" if message.text == "⏭ O'tkazib yuborish" else message.text.strip()
    data = await state.get_data()
    amount = data["amount"]
    user_name = message.from_user.first_name

    db.add_transaction(
        user_id=message.from_user.id,
        user_name=user_name,
        trans_type="savings_withdraw",
        amount=amount,
        category="Omonatdan yechildi",
        comment=comment
    )

    summary = db.get_balance_summary()
    await state.clear()

    comment_text = f"\nSabab: <i>{comment}</i>" if comment else ""
    await message.answer(
        f"📤 <b>Omonatdan pul yechildi va oila hamyoniga qaytarildi!</b>\n\n"
        f"➖ Yechilgan summa: <b>{db.format_money(amount)}</b>\n"
        f"👤 Yechdi: <b>{user_name}</b>"
        f"{comment_text}\n"
        f"💎 Omonatda qoldi: <b>{db.format_money(summary['current_savings'])}</b>\n"
        f"💵 Yangilangan erkin hamyon: <b>{db.format_money(summary['wallet_balance'])}</b>",
        reply_markup=kb.main_menu_keyboard(),
        parse_mode="HTML"
    )

    # Hamrohga xabar
    await notify_partner(
        message.bot,
        message.from_user.id,
        user_name,
        f"omonatdan pul yechib hamyonga qaytardi:\n"
        f"📤 <b>-{db.format_money(amount)}</b>\n"
        f"💵 Yangilangan hamyon: <b>{db.format_money(summary['wallet_balance'])}</b>"
    )


@dp.callback_query(F.data == "savings:history")
async def show_savings_history(callback: CallbackQuery):
    history = db.get_savings_history(limit=8)
    if not history:
        await callback.answer("Omonat bo'yicha amallar mavjud emas.", show_alert=True)
        return

    text = "📜 <b>Omonat bo'yicha oxirgi amallar:</b>\n\n"
    for item in history:
        sign = "➕" if item["type"] == "savings_add" else "➖"
        amount = db.format_money(item["amount"])
        date = item["created_at"][:16]
        who = item["user_name"] or "A'zo"
        comment = f" ({item['comment']})" if item["comment"] else ""
        text += f"{sign} <b>{amount}</b> | 👤 {who} - {date}{comment}\n"

    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


# ==========================================
# BALANS VA HISOBOTLAR BO'LIMI
# ==========================================

@dp.message(F.text == "📊 Balans va Hisobot")
async def show_balance_and_report(message: Message, state: FSMContext):
    await state.clear()
    summary = db.get_balance_summary()

    text = (
        f"📊 <b>Umumiy Oilaviy Moliyaviy Holat:</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Jami daromadlar: <b>+{db.format_money(summary['total_income'])}</b>\n"
        f"💸 Jami harajatlar: <b>-{db.format_money(summary['total_expense'])}</b>\n"
        f"🏦 Omonatdagi mablag': <b>{db.format_money(summary['current_savings'])}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💵 <b>Oila erkin hamyon qoldig'i:</b> <b>{db.format_money(summary['wallet_balance'])}</b>\n"
        f"💎 <b>Oilaning umumiy sof kapitali:</b> <b>{db.format_money(summary['total_net_worth'])}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
    )

    if summary["members_summary"]:
        text += "\n👥 <b>A'zolar hissasi (Jami):</b>\n"
        for m in summary["members_summary"]:
            m_name = m["user_name"] or "A'zo"
            text += f"• 👤 <b>{m_name}</b>:\n   💸 Harajat: -{db.format_money(m['total_exp'])}\n   💰 Daromad: +{db.format_money(m['total_inc'])}\n"

    text += "\n<i>Batafsil hisobot uchun quyidagilardan birini tanlang:</i>"
    await message.answer(text, reply_markup=kb.report_menu_keyboard(), parse_mode="HTML")


@dp.callback_query(F.data == "rep:general")
async def show_general_report(callback: CallbackQuery):
    summary = db.get_balance_summary()

    text = (
        f"💼 <b>Umumiy Oilaviy Balans Ko'rsatkichlari:</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Kiritilgan jami daromad: <b>+{db.format_money(summary['total_income'])}</b>\n"
        f"💸 Qilingan jami harajat: <b>-{db.format_money(summary['total_expense'])}</b>\n"
        f"🏦 Omonatdagi zaxira: <b>{db.format_money(summary['current_savings'])}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💵 Hamyonda qolgan: <b>{db.format_money(summary['wallet_balance'])}</b>\n"
        f"💎 Umumiy kapital (Hamyon + Omonat): <b>{db.format_money(summary['total_net_worth'])}</b>\n"
    )
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "rep:monthly")
async def show_monthly_report(callback: CallbackQuery):
    now = datetime.now()
    month_names = [
        "", "Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun",
        "Iyul", "Avgust", "Sentyabr", "Oktyabr", "Noyabr", "Dekabr"
    ]
    cur_month_name = month_names[now.month]

    report = db.get_monthly_report(year=now.year, month=now.month)

    text = (
        f"📅 <b>{cur_month_name} {now.year} — Oylik Oilaviy Hisobot:</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Oylik daromad: <b>+{db.format_money(report['income'])}</b>\n"
        f"💸 Oylik harajat: <b>-{db.format_money(report['expense'])}</b>\n"
        f"🏦 Omonatga o'tkazilgan: <b>{db.format_money(report['savings'])}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
    )

    if report["members_monthly"]:
        text += "\n👥 <b>Bu oydagi a'zolar taqsimoti:</b>\n"
        for m in report["members_monthly"]:
            m_name = m["user_name"] or "A'zo"
            text += f"• 👤 <b>{m_name}</b>: 💸 -{db.format_money(m['exp_sum'])} | 💰 +{db.format_money(m['inc_sum'])}\n"

    if report["expense_by_cat"]:
        text += "\n🏷 <b>Harajatlar toifalar bo'yicha:</b>\n"
        for row in report["expense_by_cat"]:
            cat_sum = row["cat_sum"]
            cat_name = row["category"]
            percent = (cat_sum / report["expense"] * 100) if report["expense"] > 0 else 0
            text += f"• {cat_name}: <b>{db.format_money(cat_sum)}</b> (<i>{percent:.1f}%</i>)\n"

    if report["income_by_cat"]:
        text += "\n💼 <b>Daromadlar manbalar bo'yicha:</b>\n"
        for row in report["income_by_cat"]:
            inc_sum = row["cat_sum"]
            inc_name = row["category"]
            text += f"• {inc_name}: <b>+{db.format_money(inc_sum)}</b>\n"

    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


# ==========================================
# OXIRGI AMALLAR TARIXI (HISTORY)
# ==========================================

@dp.message(F.text == "📜 Oxirgi amallar")
async def show_recent_transactions(message: Message, state: FSMContext):
    await state.clear()
    history = db.get_recent_transactions(limit=8)

    if not history:
        await message.answer(
            "📜 Hozircha sizda hech qanday amallar mavjud emas.\n"
            "Harajat yoki daromad qo'shish orqali boshlashingiz mumkin!",
            reply_markup=kb.main_menu_keyboard()
        )
        return

    text = "📜 <b>Oilaning oxirgi amallari:</b>\n\n"
    for item in history:
        t_type = item["type"]
        amount = db.format_money(item["amount"])
        date = item["created_at"][:16]
        category = item["category"] or "Umumiy"
        who = item["user_name"] or "Oila a'zosi"
        comment = f" — <i>{item['comment']}</i>" if item["comment"] else ""

        if t_type == "expense":
            icon = "🔴 Harajat"
            sign = "-"
        elif t_type == "income":
            icon = "🟢 Daromad"
            sign = "+"
        elif t_type == "savings_add":
            icon = "🔵 Omonatga"
            sign = "📥"
        elif t_type == "savings_withdraw":
            icon = "🟡 Omonatdan"
            sign = "📤"
        else:
            icon = "⚪️ Amal"
            sign = ""

        text += (
            f"{icon}: <b>{sign}{amount}</b>\n"
            f"🏷 {category} | 👤 <b>{who}</b>\n"
            f"🕒 {date}{comment}\n\n"
        )

    await message.answer(text, reply_markup=kb.main_menu_keyboard(), parse_mode="HTML")


# ==========================================
# SHAXSIY CHATDA MATNLI AI XABARLARNI QABUL QILISH
# ==========================================

@dp.message(F.chat.type == "private", F.text)
async def handle_private_ai_text(message: Message, state: FSMContext):
    """
    Shaxsiy chatda foydalanuvchi menyusiz to'g'ridan-to'g'ri xarajat yoki daromad yozsa,
    AI orqali tahlil qilib bazaga kiritish (masalan: '50 ming tushlikka ketdi').
    """
    current_state = await state.get_state()
    if current_state is not None:
        return

    text = message.text.strip()
    if text.startswith("/") or text in [
        "💸 Harajat qo'shish", "💰 Daromad qo'shish", "🏦 Omonatlar",
        "📊 Balans va Hisobot", "📜 Oxirgi amallar", "ℹ️ Yordam", "❌ Bekor qilish"
    ]:
        return

    try:
        await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    except Exception:
        pass

    parsed, err = await voice_service.process_text_message(text)
    if not parsed or not parsed.get("is_financial") or not parsed.get("amount"):
        await message.answer(
            "💡 <b>Xabarni tushunmadim.</b>\n\n"
            "Pastdagi menyu tugmalaridan foydalanishingiz yoki xarajatni to'g'ridan-to'g'ri yozishingiz mumkin:\n"
            "Masalan: <i>\"Tushlikka 45 ming ketdi\"</i> yoki <i>\"Taksiga 20 000\"</i>.",
            reply_markup=kb.main_menu_keyboard(),
            parse_mode="HTML"
        )
        return

    user = message.from_user
    user_name = user.first_name or user.full_name or "Oila a'zosi"
    t_type = parsed.get("type", "expense")
    amount = float(parsed.get("amount", 0))
    category = parsed.get("category", "Boshqa")
    comment = parsed.get("comment", text)

    db.add_transaction(
        user_id=user.id,
        user_name=user_name,
        trans_type=t_type,
        amount=amount,
        category=category,
        comment=comment
    )

    summary = db.get_balance_summary()

    if t_type == "expense":
        title = "💸 Harajat muvaffaqiyatli saqlandi!"
        sign = "-"
        action_verb = "harajat kiritdi"
    elif t_type == "income":
        title = "💰 Daromad muvaffaqiyatli saqlandi!"
        sign = "+"
        action_verb = "daromad kiritdi"
    elif t_type == "savings_add":
        title = "🏦 Omonatga mablag' qo'shildi!"
        sign = "📥 +"
        action_verb = "omonatga pul qo'shdi"
    elif t_type == "savings_withdraw":
        title = "📤 Omonatdan mablag' yechildi!"
        sign = "📤 -"
        action_verb = "omonatdan pul yechdi"
    else:
        title = "✅ Amal saqlandi!"
        sign = ""
        action_verb = "amal kiritdi"

    comment_line = f"\n📝 Izoh: <i>{comment}</i>" if comment else ""
    cat_line = f"\n🏷 Kategoriya: <b>{category}</b>" if category else ""

    response_text = (
        f"🤖 <i>AI tahlili:</i>\n\n"
        f"✅ <b>{title}</b>\n\n"
        f"Summa: <b>{sign}{db.format_money(amount)}</b>"
        f"{cat_line}"
        f"\n👤 Kiritdi: <b>{user_name}</b>"
        f"{comment_line}\n\n"
        f"💵 Oila hamyonida qoldi: <b>{db.format_money(summary['wallet_balance'])}</b>"
    )

    await message.answer(response_text, reply_markup=kb.main_menu_keyboard(), parse_mode="HTML")

    partner_comment = f" — <i>{comment}</i>" if comment else ""
    await notify_partner(
        message.bot,
        user.id,
        user_name,
        f"matn orqali {action_verb}:\n"
        f"<b>{sign}{db.format_money(amount)}</b> ({category}{partner_comment})\n"
        f"💵 Yangilangan hamyon: <b>{db.format_money(summary['wallet_balance'])}</b>"
    )


# ==========================================
# ASOSIY ISHGA TUSHIRISH (MAIN)
# ==========================================

async def main():
    # Ma'lumotlar bazasini ishga tushirish
    db.init_db()
    print("[OK] Ma'lumotlar bazasi tayyor!")

    if not config.BOT_TOKEN or config.BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("\n[!] DIQQAT: Bot token topilmadi!")
        print("1. .env faylini oching.")
        print("2. BOT_TOKEN=qismiga Telegram @BotFather bergan tokenni yozing.")
        print("3. Botni qaytadan ishga tushiring.\n")
        return

    bot = Bot(token=config.BOT_TOKEN)
    print(f"[INFO] Bot ishga tushmoqda... Ruxsat etilgan foydalanuvchilar: {config.ALLOWED_USERS}")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("[INFO] Bot to'xtatildi.")
