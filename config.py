import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
env_path = BASE_DIR / ".env"

# .env faylini o'qish (dotenv kutubxonasi bo'lsa undan, bo'lmasa oddiy o'qish)
try:
    from dotenv import load_dotenv
    load_dotenv(env_path)
except ImportError:
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip())

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Faqat ruxsat berilgan foydalanuvchilar ID lari
allowed_str = os.getenv("ALLOWED_USERS", "").strip()
ALLOWED_USERS = set()
if allowed_str:
    for item in allowed_str.split(","):
        item = item.strip()
        if item.isdigit():
            ALLOWED_USERS.add(int(item))

# Asosiy admin ID si (Pahlavon)
ADMIN_ID = 6999530323
ALLOWED_USERS.add(ADMIN_ID)


def add_allowed_user(new_id: int):
    """Yangi foydalanuvchini (masalan ayolingizni) ALLOWED_USERS ro'yxatiga va .env ga saqlash."""
    ALLOWED_USERS.add(new_id)
    # .env faylini yangilash
    lines = []
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    new_line = f"ALLOWED_USERS={','.join(str(uid) for uid in ALLOWED_USERS)}\n"
    found = False
    new_lines = []
    for line in lines:
        if line.startswith("ALLOWED_USERS="):
            new_lines.append(new_line)
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(new_line)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()



def save_groq_key(key: str):
    """Groq API kalitini .env ga saqlash."""
    global GROQ_API_KEY
    GROQ_API_KEY = key.strip()
    lines = []
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    new_line = f"GROQ_API_KEY={key.strip()}\n"
    found = False
    new_lines = []
    for line in lines:
        if line.startswith("GROQ_API_KEY="):
            new_lines.append(new_line)
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(new_line)

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


DB_FILE = BASE_DIR / "finance.db"



