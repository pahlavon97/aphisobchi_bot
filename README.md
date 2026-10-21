# 💰 Shaxsiy Moliya va Harajatlar Telegram Boti

Ushbu bot Telegram orqali shaxsiy byudjetni boshqarish, kunlik harajatlar, daromadlar va omonatlarni (jamg'armalarni) hisoblab borish uchun mo'ljallangan.

---

## 🌟 Botning asosiy imkoniyatlari

1. **💸 Harajatlar bo'limi:**
   - Harajat summasini kiritish (masalan: `50000`, `50k`, `1.5mln`)
   - Toifalar bo'yicha saralash (Oziq-ovqat, Transport, Kommunal, Kiyim-kechak, Salomatlik, Dam olish va boshqalar)
   - Ixtiyoriy izoh qoldirish yoki o'tkazib yuborish

2. **💰 Daromadlar bo'limi:**
   - Daromad summasini kiritish
   - Manbani tanlash (Oylik maosh, Frilans, Savdo/Biznes, Sovg'a, Ijara va boshqalar)
   - Tushgan mablag'ni hamyon balansiga qo'shish

3. **🏦 Omonatlar (Jamg'armalar) bo'limi:**
   - Maqsadli jamg'armalarga pul ajratish (masalan: *Mashina uchun*, *Favqulodda fond*, *Depozit*)
   - Omonatdan zarur bo'lganda mablag'ni erkin hamyonga yechib olish
   - Omonat bo'yicha kirdi-chiqdi amallar tarixi

4. **📊 Balans va Hisobotlar:**
   - **Hamyondagi erkin qoldiq** (Daromad - Harajat - Omonat)
   - **Omonatdagi mablag'**
   - **Umumiy sof kapital** (Hamyon + Omonat)
   - **Joriy oy hisoboti:** Oylik daromad va harajatlar, kategoriyalar bo'yicha foiz taqsimoti

5. **📜 Oxirgi amallar:**
   - So'nggi amallarni sana, tur va izohlari bilan ko'rish

---

## 📁 Loyiha tarkibi

- [bot.py](file:///c:/Users/Olga/Desktop/Proektlarim/bot.py) — Botning asosiy boshqaruvchi kodi va barcha buyruqlar handleri
- [database.py](file:///c:/Users/Olga/Desktop/Proektlarim/database.py) — SQLite ma'lumotlar bazasi (jadvallar, hisob-kitoblar va statistikalar)
- [keyboards.py](file:///c:/Users/Olga/Desktop/Proektlarim/keyboards.py) — Asosiy menyu, toifalar va inline tugmalar
- [states.py](file:///c:/Users/Olga/Desktop/Proektlarim/states.py) — FSM (bosqichma-bosqich kiritish holatlari)
- [config.py](file:///c:/Users/Olga/Desktop/Proektlarim/config.py) — Sozlamalar va `.env` faylini o'qish
- [requirements.txt](file:///c:/Users/Olga/Desktop/Proektlarim/requirements.txt) — Kerakli Python kutubxonalari
- [.env.example](file:///c:/Users/Olga/Desktop/Proektlarim/.env.example) — Bot token namunasi

---

## 🚀 O'rnatish va Ishga tushirish

### 1-qadam: Kutubxonalarni o'rnatish
Terminal yoki buyruqlar satrida loyiha papkasida quyidagilarni o'rnating:

```bash
pip install -r requirements.txt
```

### 2-qadam: Telegram Bot tokenini olish
1. Telegramda [@BotFather](https://t.me/BotFather) botiga kiring.
2. `/newbot` buyrug'ini yuboring.
3. Botingizga nom va username bering.
4. `@BotFather` sizga **API Token** beradi (masalan: `123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ`).

### 3-qadam: `.env` faylini yaratish
Loyiha papkasida `.env` faylini yarating (yoki `.env.example` nusxasini olib) va tokenni yozing:

```env
BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
```

### 4-qadam: Botni ishga tushirish
Quyidagi buyruqni bering:

```bash
python bot.py
```

Endi Telegramda botingizga o'tib `/start` tugmasini bosing! 🎉
