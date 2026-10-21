from aiogram.fsm.state import State, StatesGroup


class ExpenseState(StatesGroup):
    amount = State()      # Harajat summasi
    category = State()    # Kategoriya tanlash
    comment = State()     # Izoh


class IncomeState(StatesGroup):
    amount = State()      # Daromad summasi
    category = State()    # Manba tanlash
    comment = State()     # Izoh


class SavingsDepositState(StatesGroup):
    amount = State()      # Omonatga qo'shiladigan summa
    comment = State()     # Maqsad yoki izoh


class SavingsWithdrawState(StatesGroup):
    amount = State()      # Omonatdan yechiladigan summa
    comment = State()     # Sabab yoki izoh
