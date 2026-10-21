import base64
import json
import logging
import os
import re
import aiohttp
from typing import Optional, Tuple
from aiogram import Bot
from aiogram.types import Voice

import config

logger = logging.getLogger(__name__)


async def process_voice_message(bot: Bot, voice: Voice) -> Tuple[Optional[dict], Optional[str], Optional[str]]:
    """
    Ovozli xabarni qabul qilib, uni matnga aylantiradi va moliyaviy ma'lumotlarni ajratadi.
    Gemini (1-o'rinda), Groq yoki OpenAI orqali tahlil qiladi.
    Qaytaradi: (parsed_data, recognized_text, error_message)
    """
    # 1. Telegramdan ovozli xabar faylini yuklab olish
    try:
        file = await bot.get_file(voice.file_id)
        file_bytes = await bot.download_file(file.file_path)
        audio_content = file_bytes.read()
    except Exception as e:
        logger.error(f"Ovozni yuklab olishda xatolik: {e}")
        return None, None, f"Ovozli faylni yuklab bo'lmadi: {str(e)}"

    # 2. Agar GEMINI API kaliti bo'lsa (Google Gemini orqali tahlil)
    if config.GEMINI_API_KEY:
        return await _process_with_gemini(audio_content)

    # 3. Agar GROQ yoki OPENAI API kaliti bo'lsa
    if config.GROQ_API_KEY or config.OPENAI_API_KEY:
        return await _process_with_whisper_and_llm(audio_content)

    return None, None, "API_KEY_MISSING"


async def _process_with_gemini(audio_bytes: bytes) -> Tuple[Optional[dict], Optional[str], Optional[str]]:
    """Google Gemini orqali ovozni to'g'ridan-to'g'ri tahlil qilish."""
    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
    api_key = config.GEMINI_API_KEY

    prompt = (
        "Sen o'zbek tilidagi shaxsiy moliya hisobchi botisan. "
        "Ushbu audio ovozli xabarni diqqat bilan tingla. "
        "Foydalanuvchi aytgan gapdan summa, amal turi, kategoriya va izohni aniq ajratib ol. "
        "Faqat quyidagi JSON formatda javob ber, ortiqcha so'z yozma:\n"
        "{\n"
        '  "is_financial": true,\n'
        '  "recognized_text": "Eshitilgan to\'liq o\'zbekcha matn",\n'
        '  "type": "expense" yoki "income" yoki "savings_add" yoki "savings_withdraw",\n'
        '  "amount": summa raqam ko\'rinishida (masalan: 50000 yoki 1500000),\n'
        '  "category": "Oziq-ovqat" | "Transport" | "Kommunal" | "Kiyim-kechak" | "Salomatlik" | "Ko\'ngilochar" | "Aloqa" | "Oylik maosh" | "Frilans" | "Biznes" | "Boshqa",\n'
        '  "comment": "qisqa izoh yoki nima olinganligi"\n'
        "}\n\n"
        "Qoidalar:\n"
        "1. 'ming' so'zi kelsa 1 000 ga, 'million' yoki 'mln' kelsa 1 000 000 ga ko'paytir (masalan: 'ellik ming' -> 50000, 'ikki yarim million' -> 2500000).\n"
        "2. Agar gapda moliyaviy harajat, daromad yoki omonat bo'lmasa, 'is_financial': false qilib ber."
    )

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "inlineData": {
                            "mimeType": "audio/ogg",
                            "data": audio_b64
                        }
                    },
                    {
                        "text": prompt
                    }
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json"
        }
    }

    # Sinab ko'rish uchun modellar (eng barqaror va tezkor modellar)
    models_to_try = ["gemini-flash-latest", "gemini-2.5-flash", "gemini-2.5-pro"]

    async with aiohttp.ClientSession() as session:
        for model in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            try:
                async with session.post(url, json=payload, headers={"Content-Type": "application/json"}) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        candidates = data.get("candidates", [])
                        if not candidates:
                            continue
                        text_content = candidates[0]["content"]["parts"][0]["text"].strip()
                        parsed = json.loads(text_content)
                        recognized_text = parsed.get("recognized_text", "")

                        if not parsed.get("is_financial") or not parsed.get("amount"):
                            return None, recognized_text, "Xabarda moliyaviy harajat yoki summa aniqlanmadi."

                        return parsed, recognized_text, None
                    else:
                        err_text = await resp.text()
                        logger.warning(f"Gemini {model} xatoligi ({resp.status}): {err_text}")
                        continue
            except Exception as e:
                logger.error(f"Gemini {model} ulanish xatosi: {e}")
                continue

    return None, None, "Gemini xizmati orqali ovozni tahlil qilib bo'lmadi."


async def _process_with_whisper_and_llm(audio_content: bytes) -> Tuple[Optional[dict], Optional[str], Optional[str]]:
    """Groq yoki OpenAI orqali tahlil qilish."""
    api_key = config.GROQ_API_KEY or config.OPENAI_API_KEY
    is_groq = bool(config.GROQ_API_KEY)
    base_url = "https://api.groq.com/openai/v1" if is_groq else "https://api.openai.com/v1"
    whisper_model = "whisper-large-v3" if is_groq else "whisper-1"
    llm_model = "llama-3.3-70b-versatile" if is_groq else "gpt-4o-mini"

    recognized_text = ""
    try:
        headers = {"Authorization": f"Bearer {api_key}"}
        form_data = aiohttp.FormData()
        form_data.add_field(
            name="file",
            value=audio_content,
            filename="voice.ogg",
            content_type="audio/ogg"
        )
        form_data.add_field("model", whisper_model)
        form_data.add_field("language", "uz")

        async with aiohttp.ClientSession() as session:
            async with session.post(f"{base_url}/audio/transcriptions", headers=headers, data=form_data) as resp:
                if resp.status != 200:
                    err_body = await resp.text()
                    logger.error(f"Whisper API xatoligi ({resp.status}): {err_body}")
                    return None, None, f"Whisper xatoligi: {err_body}"

                result = await resp.json()
                recognized_text = result.get("text", "").strip()

    except Exception as e:
        logger.error(f"Transkripsiyada xatolik: {e}")
        return None, None, f"Ovozni matnga aylantirishda xatolik: {str(e)}"

    if not recognized_text:
        return None, None, "Ovozda hech qanday so'z aniqlanmadi."

    system_prompt = (
        "Sen o'zbek tilidagi shaxsiy moliya hisobchi botisan. "
        "Foydalanuvchining ovozli xabar matnidan summa, amal turi, kategoriya va izohni aniq ajratib ol. "
        "Faqat quyidagi JSON formatda javob ber:\n"
        "{\n"
        '  "is_financial": true,\n'
        '  "type": "expense" / "income" / "savings_add" / "savings_withdraw",\n'
        '  "amount": summa raqam ko\'rinishida,\n'
        '  "category": "tegishli kategoriya nomi",\n'
        '  "comment": "izoh"\n'
        "}\n\n"
        "Kategoriyalar: Oziq-ovqat, Transport, Kommunal, Kiyim-kechak, Salomatlik, Ko'ngilochar, Aloqa, Oylik maosh, Frilans, Biznes, Boshqa"
    )

    try:
        chat_payload = {
            "model": llm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": recognized_text}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(f"{base_url}/chat/completions", headers=headers, json=chat_payload) as resp:
                if resp.status != 200:
                    err_body = await resp.text()
                    return None, recognized_text, f"Tahlil qilish xatoligi: {err_body}"

                res_json = await resp.json()
                content = res_json["choices"][0]["message"]["content"]
                parsed = json.loads(content)

                if not parsed.get("is_financial") or not parsed.get("amount"):
                    return None, recognized_text, "Xabarda moliyaviy summa aniqlanmadi."

                return parsed, recognized_text, None

    except Exception as e:
        logger.error(f"LLM orqali tahlilda xatolik: {e}")
        return None, recognized_text, f"Tahlil qilishda xatolik: {str(e)}"


# ==========================================
# MATNLI XABARLARNI AI ORQALI TAHLIL QILISH
# ==========================================

async def process_text_message(text: str) -> Tuple[Optional[dict], Optional[str]]:
    """
    Foydalanuvchi yozgan matnni (guruh yoki shaxsiy chatdan) tahlil qilib,
    moliyaviy xarajat yoki daromad ma'lumotlarini ajratadi.
    Qaytaradi: (parsed_data, error_message)
    """
    cleaned_text = re.sub(r"@[A-Za-z0-9_]+", "", text).strip()
    if not cleaned_text:
        return None, "Xabar matni bo'sh"

    # 1. Google Gemini orqali tahlil qilish
    if config.GEMINI_API_KEY:
        parsed, err = await _process_text_with_gemini(cleaned_text)
        if parsed:
            return parsed, None

    # 2. Groq yoki OpenAI orqali tahlil qilish
    if config.GROQ_API_KEY or config.OPENAI_API_KEY:
        parsed, err = await _process_text_with_llm(cleaned_text)
        if parsed:
            return parsed, None

    # 3. Agar AI ishlamasa, aqlli zaxira (regex) orqali aniqlash
    return _process_text_fallback(cleaned_text)


async def _process_text_with_gemini(text: str) -> Tuple[Optional[dict], Optional[str]]:
    """Google Gemini orqali matnni tahlil qilish."""
    api_key = config.GEMINI_API_KEY
    prompt = (
        "Sen o'zbek tilidagi shaxsiy va guruh moliyaviy hisobchi botisan. "
        "Foydalanuvchi yozgan ushbu matndan summa, amal turi, toifa (kategoriya) va izohni aniq ajratib ol. "
        "Faqat quyidagi JSON formatda javob ber, boshqa hech qanday so'z yozma:\n"
        "{\n"
        '  "is_financial": true,\n'
        '  "type": "expense" yoki "income" yoki "savings_add" yoki "savings_withdraw",\n'
        '  "amount": summa raqam ko\'rinishida (masalan: 50000 yoki 1500000),\n'
        '  "category": "Oziq-ovqat" | "Transport" | "Kommunal" | "Kiyim-kechak" | "Salomatlik" | "Ko\'ngilochar" | "Aloqa" | "Oylik maosh" | "Frilans" | "Biznes" | "Boshqa",\n'
        '  "comment": "izoh yoki olingan narsa"\n'
        "}\n\n"
        "Qoidalar:\n"
        "1. 'ming', 'k' kelsa 1 000 ga, 'million', 'mln', 'm' kelsa 1 000 000 ga ko'paytir (masalan: 'ellik ming' -> 50000, '2.5 mln' -> 2500000, '35k' -> 35000).\n"
        "2. Xarajat bo'lsa (tushlik, taksi, bozor, dori, benzin, magazin, to'lov va h.k.), type='expense'.\n"
        "3. Daromad bo'lsa (oylik, maosh, avans, daromad, pul tushdi, qaytardi), type='income'.\n"
        "4. Agar gapda moliyaviy harajat, daromad yoki summa bo'lmasa, 'is_financial': false qilib ber.\n\n"
        f"Matn: {text}"
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"}
    }

    models_to_try = ["gemini-flash-latest", "gemini-2.5-flash", "gemini-2.5-pro"]
    async with aiohttp.ClientSession() as session:
        for model in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            try:
                async with session.post(url, json=payload, headers={"Content-Type": "application/json"}) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        candidates = data.get("candidates", [])
                        if not candidates:
                            continue
                        text_content = candidates[0]["content"]["parts"][0]["text"].strip()
                        parsed = json.loads(text_content)
                        if not parsed.get("is_financial") or not parsed.get("amount"):
                            return None, "Xabarda moliyaviy summa aniqlanmadi."
                        return parsed, None
                    else:
                        err_text = await resp.text()
                        logger.warning(f"Gemini matn {model} xatosi ({resp.status}): {err_text}")
            except Exception as e:
                logger.error(f"Gemini {model} ulanish xatosi: {e}")
                continue

    return None, "Gemini orqali matnni tahlil qilib bo'lmadi."


async def _process_text_with_llm(text: str) -> Tuple[Optional[dict], Optional[str]]:
    """Groq yoki OpenAI orqali matnni tahlil qilish."""
    api_key = config.GROQ_API_KEY or config.OPENAI_API_KEY
    is_groq = bool(config.GROQ_API_KEY)
    base_url = "https://api.groq.com/openai/v1" if is_groq else "https://api.openai.com/v1"
    llm_model = "llama-3.3-70b-versatile" if is_groq else "gpt-4o-mini"

    system_prompt = (
        "Sen o'zbek tilidagi shaxsiy va guruh moliyaviy hisobchi botisan. "
        "Foydalanuvchi yozgan matndan summa, amal turi, toifa va izohni aniq ajratib ol. "
        "Faqat quyidagi JSON formatda javob ber:\n"
        "{\n"
        '  "is_financial": true,\n'
        '  "type": "expense" / "income" / "savings_add" / "savings_withdraw",\n'
        '  "amount": summa raqam ko\'rinishida,\n'
        '  "category": "tegishli kategoriya nomi",\n'
        '  "comment": "izoh"\n'
        "}\n\n"
        "Kategoriyalar: Oziq-ovqat, Transport, Kommunal, Kiyim-kechak, Salomatlik, Ko'ngilochar, Aloqa, Oylik maosh, Frilans, Biznes, Boshqa"
    )

    try:
        chat_payload = {
            "model": llm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(f"{base_url}/chat/completions", headers=headers, json=chat_payload) as resp:
                if resp.status == 200:
                    res_json = await resp.json()
                    content = res_json["choices"][0]["message"]["content"]
                    parsed = json.loads(content)
                    if parsed.get("is_financial") and parsed.get("amount"):
                        return parsed, None
    except Exception as e:
        logger.error(f"LLM matn tahlilida xatolik: {e}")

    return None, "LLM orqali tahlil qilib bo'lmadi."


def _process_text_fallback(text: str) -> Tuple[Optional[dict], Optional[str]]:
    """AI javob bermaganda yoki API bo'lmaganda regex yordamida ajratish."""
    clean = text.lower().strip()

    # Summani qidirish: masalan 50000, 50k, 50 ming, 2.5 mln
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(k|ming|mln|million|m)?", clean)
    if not m:
        return None, "Xabarda summa aniqlanmadi"

    num_str = m.group(1).replace(",", ".")
    unit = m.group(2) or ""
    try:
        val = float(num_str)
        if unit in ("mln", "million", "m"):
            amount = val * 1_000_000
        elif unit in ("k", "ming"):
            amount = val * 1_000
        else:
            amount = val
    except ValueError:
        return None, "Summani hisoblab bo'lmadi"

    if amount <= 0:
        return None, "Noto'g'ri summa"

    # Amal turi
    is_income = any(w in clean for w in ["oylik", "maosh", "daromad", "avans", "tushdi", "ish haqi", "daromat"])
    t_type = "income" if is_income else "expense"

    # Kategoriya aniqlash
    category = "Boshqa"
    if any(w in clean for w in ["tushlik", "ovqat", "bozor", "go'sht", "non", "osh", "kafe", "restoran", "somsa", "shashlik", "choyxona"]):
        category = "Oziq-ovqat"
    elif any(w in clean for w in ["taksi", "benzin", "metan", "yo'lkira", "avtobus", "moy", "zapchast", "mashina"]):
        category = "Transport"
    elif any(w in clean for w in ["gaz", "svet", "suv", "kommunal", "musor", "kvartira", "ijara"]):
        category = "Kommunal"
    elif any(w in clean for w in ["dori", "apteka", "shifoxona", "doktor", "tabib", "analiz"]):
        category = "Salomatlik"
    elif any(w in clean for w in ["oylik", "maosh", "avans"]):
        category = "Oylik maosh"
    elif any(w in clean for w in ["internet", "paynet", "telefon", "aloqa", "wifi"]):
        category = "Aloqa"
    elif any(w in clean for w in ["kiyim", "krossovka", "shim", "ko'ylak"]):
        category = "Kiyim-kechak"

    comment = text.strip()

    return {
        "is_financial": True,
        "type": t_type,
        "amount": amount,
        "category": category,
        "comment": comment
    }, None

