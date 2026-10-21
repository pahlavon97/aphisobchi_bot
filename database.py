import sqlite3
from datetime import datetime
from config import DB_FILE


def get_connection():
    """SQLite ma'lumotlar bazasiga ulanish yaratadi."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Kerakli jadvallarni yaratadi va yangilaydi (migration)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Foydalanuvchilar jadvali
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Barcha moliyaviy amallar jadvali
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                user_name TEXT DEFAULT '',
                type TEXT NOT NULL,
                amount REAL NOT NULL,
                category TEXT,
                comment TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        """)

        # user_name ustuni mavjudligini tekshirish va qo'shish
        cursor.execute("PRAGMA table_info(transactions)")
        columns = [row["name"] for row in cursor.fetchall()]
        if "user_name" not in columns:
            cursor.execute("ALTER TABLE transactions ADD COLUMN user_name TEXT DEFAULT ''")

        # Mavjud bo'sh nomli yozuvlarni users jadvalidan to'ldirish
        cursor.execute("""
            UPDATE transactions
            SET user_name = (
                SELECT COALESCE(users.full_name, 'Pahlavon')
                FROM users
                WHERE users.user_id = transactions.user_id
            )
            WHERE user_name IS NULL OR user_name = ''
        """)

        conn.commit()


def register_user(user_id: int, username: str, full_name: str):
    """Foydalanuvchini ro'yxatdan o'tkazish yoki ma'lumotlarini yangilash."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (user_id, username, full_name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                full_name = excluded.full_name
        """, (user_id, username or "", full_name or ""))
        conn.commit()


def get_all_users() -> list:
    """Barcha ro'yxatdan o'tgan oila a'zolarini olish."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, username, full_name FROM users")
        return cursor.fetchall()


def add_transaction(user_id: int, user_name: str, trans_type: str, amount: float, category: str = "", comment: str = "") -> int:
    """Yangi tranzaksiya (harajat, daromad yoki omonat) qo'shish."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO transactions (user_id, user_name, type, amount, category, comment)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, user_name or "Oila a'zosi", trans_type, amount, category, comment))
        conn.commit()
        return cursor.lastrowid


def get_balance_summary(user_id: int = None) -> dict:
    """
    Umumiy oilaviy balans va shaxslar bo'yicha taqsimotni qaytaradi.
    (Ikkala oila a'zosi uchun ham umumiy byudjet ko'rinadi).
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Jami oilaviy daromad
        cursor.execute("""
            SELECT COALESCE(SUM(amount), 0) FROM transactions
            WHERE type = 'income'
        """)
        total_income = cursor.fetchone()[0]

        # Jami oilaviy harajat
        cursor.execute("""
            SELECT COALESCE(SUM(amount), 0) FROM transactions
            WHERE type = 'expense'
        """)
        total_expense = cursor.fetchone()[0]

        # Omonatga kiritilgan jami mablag'
        cursor.execute("""
            SELECT COALESCE(SUM(amount), 0) FROM transactions
            WHERE type = 'savings_add'
        """)
        savings_in = cursor.fetchone()[0]

        # Omonatdan yechib olingan mablag'
        cursor.execute("""
            SELECT COALESCE(SUM(amount), 0) FROM transactions
            WHERE type = 'savings_withdraw'
        """)
        savings_out = cursor.fetchone()[0]

        current_savings = max(0.0, savings_in - savings_out)
        
        # Hamyondagi erkin qoldiq
        wallet_balance = total_income - total_expense - current_savings
        
        # Umumiy sof kapital
        total_net_worth = wallet_balance + current_savings

        # Shaxslar (er-xotin) bo'yicha taqsimot
        cursor.execute("""
            SELECT user_name,
                   SUM(CASE WHEN type = 'expense' THEN amount ELSE 0 END) as total_exp,
                   SUM(CASE WHEN type = 'income' THEN amount ELSE 0 END) as total_inc
            FROM transactions
            GROUP BY user_name
            ORDER BY total_exp DESC
        """)
        members_summary = cursor.fetchall()

        return {
            "total_income": total_income,
            "total_expense": total_expense,
            "current_savings": current_savings,
            "wallet_balance": wallet_balance,
            "total_net_worth": total_net_worth,
            "members_summary": members_summary
        }


def get_monthly_report(user_id: int = None, year: int = None, month: int = None) -> dict:
    """Joriy oy bo'yicha umumiy oilaviy hisobot va har bir a'zoning hissasi."""
    now = datetime.now()
    if year is None:
        year = now.year
    if month is None:
        month = now.month

    month_prefix = f"{year:04d}-{month:02d}%"

    with get_connection() as conn:
        cursor = conn.cursor()

        # Oylik jami daromad
        cursor.execute("""
            SELECT COALESCE(SUM(amount), 0) FROM transactions
            WHERE type = 'income' AND created_at LIKE ?
        """, (month_prefix,))
        month_income = cursor.fetchone()[0]

        # Oylik jami harajat
        cursor.execute("""
            SELECT COALESCE(SUM(amount), 0) FROM transactions
            WHERE type = 'expense' AND created_at LIKE ?
        """, (month_prefix,))
        month_expense = cursor.fetchone()[0]

        # Oylik omonatga qo'shilgan
        cursor.execute("""
            SELECT COALESCE(SUM(amount), 0) FROM transactions
            WHERE type = 'savings_add' AND created_at LIKE ?
        """, (month_prefix,))
        month_savings = cursor.fetchone()[0]

        # Oylik harajatlar kategoriyalar bo'yicha
        cursor.execute("""
            SELECT category, SUM(amount) as cat_sum, COUNT(id) as count
            FROM transactions
            WHERE type = 'expense' AND created_at LIKE ?
            GROUP BY category
            ORDER BY cat_sum DESC
        """, (month_prefix,))
        expense_by_cat = cursor.fetchall()

        # Oylik daromadlar manbalar bo'yicha
        cursor.execute("""
            SELECT category, SUM(amount) as cat_sum, COUNT(id) as count
            FROM transactions
            WHERE type = 'income' AND created_at LIKE ?
            GROUP BY category
            ORDER BY cat_sum DESC
        """, (month_prefix,))
        income_by_cat = cursor.fetchall()

        # Oila a'zolari bo'yicha oylik taqsimot
        cursor.execute("""
            SELECT user_name,
                   SUM(CASE WHEN type = 'expense' THEN amount ELSE 0 END) as exp_sum,
                   SUM(CASE WHEN type = 'income' THEN amount ELSE 0 END) as inc_sum
            FROM transactions
            WHERE created_at LIKE ?
            GROUP BY user_name
            ORDER BY exp_sum DESC
        """, (month_prefix,))
        members_monthly = cursor.fetchall()

        return {
            "year": year,
            "month": month,
            "income": month_income,
            "expense": month_expense,
            "savings": month_savings,
            "expense_by_cat": expense_by_cat,
            "income_by_cat": income_by_cat,
            "members_monthly": members_monthly
        }


def get_recent_transactions(user_id: int = None, limit: int = 8) -> list:
    """Oilaning oxirgi amallari (kim kiritgani bilan)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, user_id, user_name, type, amount, category, comment, created_at
            FROM transactions
            ORDER BY id DESC
            LIMIT ?
        """, (limit,))
        return cursor.fetchall()


def get_savings_history(user_id: int = None, limit: int = 6) -> list:
    """Omonat bo'yicha oxirgi amallar."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, user_id, user_name, type, amount, category, comment, created_at
            FROM transactions
            WHERE type IN ('savings_add', 'savings_withdraw')
            ORDER BY id DESC
            LIMIT ?
        """, (limit,))
        return cursor.fetchall()


def format_money(amount: float) -> str:
    """Raqamlarni chiroyli qilib formatlash (masalan: 1 250 000 so'm)."""
    return f"{amount:,.0f}".replace(",", " ") + " so'm"
