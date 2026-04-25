# REPLIT AGENT PLEASE ADD THIS = run command "python logs1_director.py" and build command "pip install -r requirements1.txt"
import asyncio
import sqlite3
import requests
import hashlib
import os
import re
from aiohttp import web

from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Update
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from typing import Callable, Dict, Any, Awaitable

# ===== ТОКЕНЫ =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
CRYPTO_TOKEN = os.getenv("CRYPTO_TOKEN")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# ===== АДМИНЫ =====
ADMINS = [6683316915, 5338814259]

# ===== БАЗА ДАННЫХ =====
conn = sqlite3.connect("shop.db")
cur = conn.cursor()

cur.execute("""CREATE TABLE IF NOT EXISTS users(
id INTEGER PRIMARY KEY,
username TEXT,
first_name TEXT,
balance REAL DEFAULT 0,
purchases INTEGER DEFAULT 0,
total_deposit REAL DEFAULT 0)""")

cur.execute("PRAGMA table_info(users)")
columns = [col[1] for col in cur.fetchall()]
if 'banned' not in columns:
    cur.execute("ALTER TABLE users ADD COLUMN banned INTEGER DEFAULT 0")
    conn.commit()

cur.execute("""CREATE TABLE IF NOT EXISTS items(
id INTEGER PRIMARY KEY AUTOINCREMENT,
type TEXT,
name TEXT,
data TEXT,
price REAL,
amount INTEGER)""")

cur.execute("""CREATE TABLE IF NOT EXISTS links(
id INTEGER PRIMARY KEY AUTOINCREMENT,
text TEXT)""")

cur.execute("""
CREATE TABLE IF NOT EXISTS global_stats (
    id INTEGER PRIMARY KEY,
    total_deposit REAL DEFAULT 0,
    total_users_manual INTEGER DEFAULT 0
)
""")
conn.commit()

for admin_id in ADMINS:
    cur.execute("SELECT id FROM users WHERE id = ?", (admin_id,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (id, username, first_name, balance, purchases, total_deposit, banned) VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (admin_id, "admin", "Admin", 0, 0, 0, 0))
        conn.commit()

cur.execute("SELECT id FROM global_stats WHERE id = 1")
if not cur.fetchone():
    cur.execute("INSERT INTO global_stats (id, total_deposit, total_users_manual) VALUES (1, 0, 0)")
    conn.commit()

print("База данных готова")

# ===== ОСНОВНЫЕ ФУНКЦИИ =====
def get_user(uid, username, name):
    cur.execute("SELECT * FROM users WHERE id=?", (uid,))
    u = cur.fetchone()
    if not u:
        cur.execute("INSERT INTO users (id, username, first_name, balance, purchases, total_deposit, banned) VALUES (?,?,?,?,?,?,?)",
                   (uid, username, name, 0, 0, 0, 0))
        conn.commit()
    else:
        cur.execute("UPDATE users SET username=?, first_name=? WHERE id=?", (username, name, uid))
        conn.commit()
    return cur.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()

def get_balance_by_id(uid):
    cur.execute("SELECT balance FROM users WHERE id=?", (uid,))
    result = cur.fetchone()
    return result[0] if result else 0

def is_banned(uid):
    cur.execute("SELECT banned FROM users WHERE id=?", (uid,))
    result = cur.fetchone()
    return result[0] == 1 if result else False

def ban_user(uid):
    cur.execute("UPDATE users SET banned = 1 WHERE id=?", (uid,))
    conn.commit()

def unban_user(uid):
    cur.execute("UPDATE users SET banned = 0 WHERE id=?", (uid,))
    conn.commit()

def add_balance(uid, amt):
    cur.execute("SELECT id FROM users WHERE id=?", (uid,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (id, username, first_name, balance, purchases, total_deposit, banned) VALUES (?,?,?,?,?,?,?)",
                   (uid, "", "", amt, 0, amt, 0))
        conn.commit()
    else:
        cur.execute("UPDATE users SET balance=balance+?, total_deposit=total_deposit+? WHERE id=?", (amt, amt, uid))
        conn.commit()
    cur.execute("UPDATE global_stats SET total_deposit = total_deposit + ? WHERE id = 1", (amt,))
    conn.commit()

def remove_balance(uid, amt):
    cur.execute("SELECT balance FROM users WHERE id=?", (uid,))
    bal = cur.fetchone()
    if not bal or bal[0] < amt:
        return False
    cur.execute("UPDATE users SET balance=balance-? WHERE id=?", (amt, uid))
    conn.commit()
    return True

def reset_all_balances():
    placeholders = ','.join('?' * len(ADMINS))
    cur.execute(f"UPDATE users SET balance = 0 WHERE id NOT IN ({placeholders})", ADMINS)
    conn.commit()

async def notify_admins(text):
    for a in ADMINS:
        try:
            await bot.send_message(a, text)
        except:
            pass

# ===== CRYPTO =====
def create_invoice(amount):
    headers = {"Crypto-Pay-API-Token": CRYPTO_TOKEN}
    r = requests.post("https://pay.crypt.bot/api/createInvoice",
        headers=headers, json={"asset":"USDT","amount":amount}).json()
    return r

def check_invoice(iid):
    headers = {"Crypto-Pay-API-Token": CRYPTO_TOKEN}
    r = requests.get("https://pay.crypt.bot/api/getInvoices",
        headers=headers).json()
    for i in r.get("result", {}).get("items", []):
        if i["invoice_id"] == iid:
            return i["status"]
    return "none"

# ===== КЛАВИАТУРЫ =====
def main_kb(uid):
    kb = ReplyKeyboardBuilder()
    kb.button(text="Магазин")
    kb.button(text="Профиль")
    kb.button(text="Пополнить")
    kb.button(text="Баланс")
    kb.button(text="Поддержка")
    kb.button(text="Статистика")
    if uid in ADMINS:
        kb.button(text="Админ")
    kb.adjust(2, 2, 2, 1)
    return kb.as_markup(resize_keyboard=True)

def back_kb():
    kb = ReplyKeyboardBuilder()
    kb.button(text="Назад")
    return kb.as_markup(resize_keyboard=True)

# ===== FSM =====
class AddItem(StatesGroup):
    name = State()
    data = State()
    price = State()
    amount = State()

class Deposit(StatesGroup):
    amount = State()

# ===== ОБЫЧНЫЕ КОМАНДЫ =====
@dp.message(F.text == "/start")
async def start(msg: Message, state: FSMContext):
    await state.clear()
    if is_banned(msg.from_user.id):
        await msg.answer("Вы забанены")
        return
    get_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    await msg.answer("Добро пожаловать!", reply_markup=main_kb(msg.from_user.id))

@dp.message(F.text == "Назад")
async def back(msg: Message, state: FSMContext):
    if is_banned(msg.from_user.id):
        await msg.answer("Вы забанены")
        return
    await state.clear()
    await msg.answer("Главное меню", reply_markup=main_kb(msg.from_user.id))

@dp.message(F.text == "Профиль")
async def profile(msg: Message):
    if is_banned(msg.from_user.id):
        await msg.answer("Вы забанены")
        return
    u = get_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    await msg.answer(f"ID: {u[0]}\nИмя: {u[2]}\nБаланс: {u[3]} $\nПокупок: {u[4]}", reply_markup=main_kb(msg.from_user.id))

@dp.message(F.text == "Баланс")
async def bal(msg: Message):
    if is_banned(msg.from_user.id):
        await msg.answer("Вы забанены")
        return
    u = get_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    await msg.answer(f"Баланс: {u[3]} $", reply_markup=main_kb(msg.from_user.id))

@dp.message(F.text == "Поддержка")
async def support(msg: Message):
    if is_banned(msg.from_user.id):
        await msg.answer("Вы забанены")
        return
    await msg.answer("По вопросам - @director_a_huli_net\nПо техническим вопросам - @FirstName_support")

@dp.message(F.text == "Статистика")
async def stats(msg: Message):
    if is_banned(msg.from_user.id):
        await msg.answer("Вы забанены")
        return
    cur.execute("SELECT total_deposit, total_users_manual FROM global_stats WHERE id = 1")
    result = cur.fetchone()
    total_deposit = result[0] if result else 0
    manual_users = result[1] if result else 0
    real_users = cur.execute("SELECT COUNT(*) FROM users WHERE banned = 0").fetchone()[0] or 0
    total_users = real_users + manual_users
    total_buys = cur.execute("SELECT SUM(purchases) FROM users").fetchone()[0] or 0
    links = cur.execute("SELECT text FROM links").fetchall()
    
    text = f"Пользователей: {total_users}\nПополнено: {round(total_deposit,2)} $\nПокупок: {total_buys}"
    if links:
        text += "\n\nПроекты:\n" + "\n".join([l[0] for l in links])
    await msg.answer(text, disable_web_page_preview=True)

# ===== ПОПОЛНЕНИЕ =====
active_invoices = {}

@dp.message(F.text == "Пополнить")
async def dep(msg: Message, state: FSMContext):
    if is_banned(msg.from_user.id):
        await msg.answer("Вы забанены")
        return
    await state.set_state(Deposit.amount)
    
    warning_text = (
        "ВНИМАНИЕ!\n\n"
        "Перед покупкой прочитайте "
        "<a href=\"https://telegra.ph/POLZOVATELSKOE-SOGLASHENIE-04-03-34\">ПОЛЬЗОВАТЕЛЬСКОЕ СОГЛАШЕНИЕ</a>\n\n"
        "Введите сумму:"
    )
    
    await msg.answer(warning_text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=back_kb())

@dp.message(Deposit.amount)
async def dep2(msg: Message, state: FSMContext):
    if is_banned(msg.from_user.id):
        await msg.answer("Вы забанены")
        await state.clear()
        return
    try:
        amt = float(msg.text)
    except:
        await msg.answer("Ошибка", reply_markup=back_kb())
        return

    inv_response = create_invoice(amt)
    if 'result' not in inv_response:
        await msg.answer("Ошибка создания счета")
        return

    inv = inv_response['result']
    invoice_id = inv["invoice_id"]
    
    active_invoices[invoice_id] = (msg.from_user.id, amt)
    
    kb = InlineKeyboardBuilder()
    kb.button(text="Оплатить", url=inv["pay_url"])
    kb.button(text="Проверить", callback_data=f"check:{invoice_id}")
    kb.adjust(1)
    await msg.answer(f"Оплатите {amt}$", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("check:"))
async def check(call: CallbackQuery):
    if is_banned(call.from_user.id):
        await call.answer("Вы забанены", show_alert=True)
        return
    invoice_id = int(call.data.split(":")[1])
    if check_invoice(invoice_id) == "paid":
        user_id, amt = active_invoices.pop(invoice_id, (call.from_user.id, 0))
        add_balance(user_id, amt)
        await call.message.answer("Средства зачислены", reply_markup=main_kb(call.from_user.id))
        await call.message.delete()
    else:
        await call.answer("Еще не оплачено", show_alert=True)

async def check_payments_loop():
    print("Фоновая проверка платежей запущена")
    while True:
        await asyncio.sleep(10)
        if not active_invoices:
            continue
        to_remove = []
        for invoice_id, (user_id, amt) in list(active_invoices.items()):
            try:
                status = check_invoice(invoice_id)
                if status == "paid":
                    add_balance(user_id, amt)
                    to_remove.append(invoice_id)
                    try:
                        await bot.send_message(user_id, f"{amt}$ автоматически зачислены!")
                    except:
                        pass
            except Exception as e:
                print(f"Ошибка проверки {invoice_id}: {e}")
        for inv in to_remove:
            del active_invoices[inv]

# ===== МАГАЗИН =====
@dp.message(F.text == "Магазин")
async def shop(msg: Message):
    if is_banned(msg.from_user.id):
        await msg.answer("Вы забанены")
        return
    kb = InlineKeyboardBuilder()
    kb.button(text="Логи", callback_data="cat:лог:0")
    kb.button(text="Акки", callback_data="cat:акк:0")
    kb.button(text="Мануалы", callback_data="cat:мануал:0")
    kb.button(text="Разное", callback_data="cat:разное:0")
    kb.button(text="Назад", callback_data="back_main")
    kb.adjust(2, 2, 1)
    await msg.answer("Категории:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("cat"))
async def cat(call: CallbackQuery):
    if is_banned(call.from_user.id):
        await call.answer("Вы забанены", show_alert=True)
        return
    _, t, page = call.data.split(":")
    page = int(page)

    items = cur.execute("SELECT * FROM items WHERE type=?", (t,)).fetchall()
    if not items:
        await call.answer("Пусто", show_alert=True)
        return

    per = 10
    start = page * per
    page_items = items[start:start+per]
    if not page_items:
        await call.answer("Товаров нет", show_alert=True)
        return

    text = f"Категория: {t}\n\n"
    
    for i, it in enumerate(page_items, start=start+1):
        amt = "∞" if it[5] == -1 else it[5]
        text += f"{i}. {it[2]} | {amt} шт. | {it[4]} $\n"
    
    kb = InlineKeyboardBuilder()
    
    row_buttons = []
    for i, it in enumerate(page_items, start=start+1):
        row_buttons.append(InlineKeyboardButton(text=f"Купить {i}", callback_data=f"buy:{it[0]}"))
    
    for i in range(0, len(row_buttons), 2):
        if i + 1 < len(row_buttons):
            kb.row(row_buttons[i], row_buttons[i+1])
        else:
            kb.row(row_buttons[i])
    
    total_pages = (len(items) + per - 1) // per
    pagination = []
    if start > 0:
        pagination.append(InlineKeyboardButton(text="Назад", callback_data=f"cat:{t}:{page-1}"))
    pagination.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="ignore"))
    if start + per < len(items):
        pagination.append(InlineKeyboardButton(text="Вперед", callback_data=f"cat:{t}:{page+1}"))
    kb.row(*pagination)
    kb.row(InlineKeyboardButton(text="Главное меню", callback_data="back_main"))

    try:
        await call.message.delete()
    except:
        pass
    
    await call.message.answer(text, reply_markup=kb.as_markup())
    await call.answer()

@dp.callback_query(F.data.startswith("buy"))
async def buy(call: CallbackQuery):
    if is_banned(call.from_user.id):
        await call.answer("Вы забанены", show_alert=True)
        return
    item_id = call.data.split(":")[1]
    item = cur.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    kb = InlineKeyboardBuilder()
    kb.button(text="Да", callback_data=f"yes:{item_id}")
    kb.button(text="Нет", callback_data="cancel")
    await call.message.answer(f"{item[2]} | {item[4]} $\nПодтвердить?", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("yes"))
async def yes(call: CallbackQuery):
    if is_banned(call.from_user.id):
        await call.answer("Вы забанены", show_alert=True)
        return
    item_id = call.data.split(":")[1]
    item = cur.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not remove_balance(call.from_user.id, item[4]):
        await call.answer("Недостаточно средств", show_alert=True)
        return
    await call.message.answer(f"{item[2]}\n\n{item[3]}")
    cur.execute("UPDATE users SET purchases=purchases+1 WHERE id=?", (call.from_user.id,))
    conn.commit()
    if item[5] != -1:
        new = item[5] - 1
        if new <= 0:
            cur.execute("DELETE FROM items WHERE id=?", (item_id,))
            await notify_admins(f"Закончился: {item[2]}")
        else:
            cur.execute("UPDATE items SET amount=? WHERE id=?", (new, item_id))
        conn.commit()
    await notify_admins(f"Купили: {item[2]}")

@dp.callback_query(F.data == "back_main")
async def back_main(call: CallbackQuery):
    if is_banned(call.from_user.id):
        await call.answer("Вы забанены", show_alert=True)
        return
    try:
        await call.message.delete()
    except:
        pass
    await call.message.answer("Главное меню", reply_markup=main_kb(call.from_user.id))

# ===== АДМИН ПАНЕЛЬ =====
admin_modes = {}

@dp.message(F.text == "Админ")
async def admin(msg: Message):
    if msg.from_user.id not in ADMINS:
        return
    
    guide = """
=== АДМИН КОМАНДЫ ===

--- ТОВАРЫ ---
+лог - добавить товар в Логи
-лог - удалить товар из Логов
+мануал - добавить товар в Мануалы
-мануал - удалить товар из Мануалов
+акк - добавить товар в Акки
-акк - удалить товар из Акков
+разное - добавить товар в Разное
-разное - удалить товар из Разного

--- БАЛАНС ПОЛЬЗОВАТЕЛЯ ---
+$ ID сумма - добавить баланс
-$ ID сумма - снять баланс

--- СТАТИСТИКА ---
+$$$ сумма - увеличить общую сумму пополнений
-$$$ сумма - уменьшить общую сумму пополнений
$$$ - показывает реальную статистику без накрутки

--- ПОЛЬЗОВАТЕЛИ ---
+юзер количество - добавить пользователей в статистику
-юзер количество - убавить пользователей из статистики
обнуление - обнулить балансы всех пользователей (с подтверждением)
бан ID - забанить пользователя
разбан ID - разбанить пользователя

--- ПРОВЕРКА ---
чек ID - проверить баланс пользователя
чек всех - список пользователей с балансом

--- ССЫЛКИ ---
+линк текст - добавить ссылку в статистику
-линк - удалить ссылку из статистики

--- РАССЫЛКА ---
/send текст - отправить сообщение всем пользователям
"""
    await msg.answer(guide, reply_markup=main_kb(msg.from_user.id))

# ===== АДМИН: ОБНУЛЕНИЕ =====
@dp.message(lambda m: m.text and m.text.lower() == "обнуление")
async def reset_balances_cmd(msg: Message):
    if msg.from_user.id not in ADMINS:
        return
    
    kb = InlineKeyboardBuilder()
    kb.button(text="ДА, обнулить всё", callback_data="reset_confirm")
    kb.button(text="НЕТ, отмена", callback_data="reset_cancel")
    kb.adjust(1)
    await msg.answer("ВНИМАНИЕ! Вы собираетесь обнулить балансы ВСЕХ пользователей!\n\nПодтвердите действие:", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "reset_confirm")
async def reset_confirm(call: CallbackQuery):
    if call.from_user.id not in ADMINS:
        return
    
    reset_all_balances()
    await call.message.edit_text("Балансы всех пользователей обнулены")
    await call.answer()
    await notify_admins(f"Админ {call.from_user.id} обнулил балансы всех пользователей")

@dp.callback_query(F.data == "reset_cancel")
async def reset_cancel(call: CallbackQuery):
    if call.from_user.id not in ADMINS:
        return
    await call.message.edit_text("Обнуление отменено")
    await call.answer()

# ===== АДМИН: БАН =====
@dp.message(lambda m: m.text and m.text.lower().startswith("бан "))
async def ban_user_cmd(msg: Message):
    if msg.from_user.id not in ADMINS:
        return
    try:
        uid = int(msg.text.split()[1])
        if uid in ADMINS:
            return
        ban_user(uid)
        await msg.answer(f"Пользователь {uid} забанен")
        try:
            await bot.send_message(uid, "Вы были забанены в боте")
        except:
            pass
    except:
        pass

# ===== АДМИН: РАЗБАН =====
@dp.message(lambda m: m.text and m.text.lower().startswith("разбан "))
async def unban_user_cmd(msg: Message):
    if msg.from_user.id not in ADMINS:
        return
    try:
        uid = int(msg.text.split()[1])
        unban_user(uid)
        await msg.answer(f"Пользователь {uid} разбанен")
        try:
            await bot.send_message(uid, "Вы были разбанены в боте")
        except:
            pass
    except:
        pass

# ===== АДМИН: ДОБАВЛЕНИЕ ТОВАРОВ =====
@dp.message(F.text.in_(["+лог", "+мануал", "+акк", "+разное"]))
async def add_start(msg: Message, state: FSMContext):
    if msg.from_user.id not in ADMINS:
        return
    await state.clear()
    item_type = msg.text[1:]
    await state.update_data(item_type=item_type)
    await state.set_state(AddItem.name)
    await msg.answer("Название:", reply_markup=back_kb())

@dp.message(AddItem.name)
async def add_name(msg: Message, state: FSMContext):
    if msg.text == "Назад":
        await state.clear()
        await msg.answer("Отмена", reply_markup=main_kb(msg.from_user.id))
        return
    await state.update_data(item_name=msg.text)
    await state.set_state(AddItem.data)
    await msg.answer("Данные:", reply_markup=back_kb())

@dp.message(AddItem.data)
async def add_data(msg: Message, state: FSMContext):
    if msg.text == "Назад":
        await state.clear()
        await msg.answer("Отмена", reply_markup=main_kb(msg.from_user.id))
        return
    await state.update_data(item_data=msg.text)
    await state.set_state(AddItem.price)
    await msg.answer("Цена:", reply_markup=back_kb())

@dp.message(AddItem.price)
async def add_price(msg: Message, state: FSMContext):
    if msg.text == "Назад":
        await state.clear()
        await msg.answer("Отмена", reply_markup=main_kb(msg.from_user.id))
        return
    try:
        price = float(msg.text)
    except:
        await msg.answer("Число", reply_markup=back_kb())
        return
    await state.update_data(item_price=price)
    await state.set_state(AddItem.amount)
    await msg.answer("Количество (-1 = бесконечно):", reply_markup=back_kb())

@dp.message(AddItem.amount)
async def add_amount(msg: Message, state: FSMContext):
    if msg.text == "Назад":
        await state.clear()
        await msg.answer("Отмена", reply_markup=main_kb(msg.from_user.id))
        return
    try:
        amount = int(msg.text)
    except:
        await msg.answer("Целое число", reply_markup=back_kb())
        return
    
    data = await state.get_data()
    cur.execute(
        "INSERT INTO items (type, name, data, price, amount) VALUES (?, ?, ?, ?, ?)",
        (data["item_type"], data["item_name"], data["item_data"], data["item_price"], amount)
    )
    conn.commit()
    await msg.answer("Товар добавлен", reply_markup=main_kb(msg.from_user.id))
    await state.clear()

# ===== АДМИН: УДАЛЕНИЕ ТОВАРОВ =====
@dp.message(F.text.in_(["-лог", "-мануал", "-акк", "-разное"]))
async def del_items(msg: Message):
    if msg.from_user.id not in ADMINS:
        return
    t = msg.text[1:]
    items = cur.execute("SELECT id, name FROM items WHERE type=?", (t,)).fetchall()
    if not items:
        await msg.answer("Нет товаров")
        return
    kb = InlineKeyboardBuilder()
    for item_id, name in items:
        kb.button(text=name, callback_data=f"delitem:{item_id}")
    kb.button(text="Отмена", callback_data="cancel_del")
    kb.adjust(1)
    await msg.answer(f"Удалить из {t}:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("delitem:"))
async def delete_item(call: CallbackQuery):
    if call.from_user.id not in ADMINS:
        return
    item_id = call.data.split(":")[1]
    cur.execute("DELETE FROM items WHERE id=?", (item_id,))
    conn.commit()
    await call.answer("Удалено")
    await call.message.delete()

@dp.callback_query(F.data == "cancel_del")
async def cancel_del(call: CallbackQuery):
    await call.message.delete()
    
# ===== АДМИН: СТАТИСТИКА =====
@dp.message(lambda m: m.text and m.text.startswith("+$$$"))
async def add_stat(msg: Message):
    if msg.from_user.id not in ADMINS:
        return
    try:
        text = msg.text[4:].strip()
        amount = float(text.split()[0])
        cur.execute("UPDATE global_stats SET total_deposit = total_deposit + ? WHERE id = 1", (amount,))
        conn.commit()
        await msg.answer(f"+{amount}$ к статистике")
    except:
        pass

@dp.message(lambda m: m.text and m.text.startswith("-$$$"))
async def minus_stat(msg: Message):
    if msg.from_user.id not in ADMINS:
        return
    try:
        text = msg.text[4:].strip()
        amount = float(text.split()[0])
        cur.execute("SELECT total_deposit FROM global_stats WHERE id = 1")
        current = cur.fetchone()[0] or 0
        if current >= amount:
            cur.execute("UPDATE global_stats SET total_deposit = total_deposit - ? WHERE id = 1", (amount,))
            conn.commit()
            await msg.answer(f"-{amount}$ из статистики")
        else:
            await msg.answer("Нельзя снять больше чем есть")
    except:
        pass

# ===== АДМИН: БАЛАНС =====
@dp.message(lambda m: m.text and m.text.lower().startswith("+$"))
async def plus_money(msg: Message):
    if msg.from_user.id not in ADMINS:
        return
    try:
        text = re.sub(r'^\+?\$', '', msg.text.strip()).strip()
        parts = text.split()
        if len(parts) >= 2:
            uid = int(parts[0])
            amount = float(parts[1])
            add_balance(uid, amount)
            await msg.answer(f"+{amount}$ пользователю {uid}")
    except:
        pass

@dp.message(lambda m: m.text and m.text.lower().startswith("-$"))
async def minus_money(msg: Message):
    if msg.from_user.id not in ADMINS:
        return
    try:
        text = re.sub(r'^-\$', '', msg.text.strip()).strip()
        parts = text.split()
        if len(parts) >= 2:
            uid = int(parts[0])
            amount = float(parts[1])
            remove_balance(uid, amount)
            await msg.answer(f"-{amount}$ у пользователя {uid}")
    except:
        pass

# ===== АДМИН: РЕАЛЬНАЯ СТАТИСТИКА =====
@dp.message(F.text == "$$$")
async def show_real_stat(msg: Message):
    if msg.from_user.id not in ADMINS:
        return
    
    real_users = cur.execute("SELECT COUNT(*) FROM users WHERE banned = 0").fetchone()[0] or 0
    real_deposit = cur.execute("SELECT SUM(total_deposit) FROM users").fetchone()[0] or 0
    real_buys = cur.execute("SELECT SUM(purchases) FROM users").fetchone()[0] or 0
    
    cur.execute("SELECT total_deposit, total_users_manual FROM global_stats WHERE id = 1")
    result = cur.fetchone()
    fake_deposit = result[0] if result else 0
    fake_users = result[1] if result else 0
    
    text = f"=== РЕАЛЬНАЯ СТАТИСТИКА ===\n\n"
    text += f"Реальных пользователей: {real_users}\n"
    text += f"Реальных пополнений: {round(real_deposit, 2)} $\n"
    text += f"Реальных покупок: {real_buys}\n\n"
    text += f"=== С НАКРУТКОЙ ===\n\n"
    text += f"Всего (с накруткой): {real_users + fake_users}\n"
    text += f"Всего (с накруткой): {round(real_deposit + fake_deposit, 2)} $\n"
    
    await msg.answer(text)

# ===== АДМИН: ПОЛЬЗОВАТЕЛИ (НАКРУТКА) =====
@dp.message(lambda m: m.text and m.text.lower().startswith("+юзер"))
async def add_user_manual(msg: Message):
    if msg.from_user.id not in ADMINS:
        return
    try:
        text = re.sub(r'^\+юзер', '', msg.text.lower().strip()).strip()
        amount = int(text.split()[0])
        cur.execute("UPDATE global_stats SET total_users_manual = total_users_manual + ? WHERE id = 1", (amount,))
        conn.commit()
        await msg.answer(f"+{amount} пользователей")
    except:
        pass

@dp.message(lambda m: m.text and m.text.lower().startswith("-юзер"))
async def minus_user_manual(msg: Message):
    if msg.from_user.id not in ADMINS:
        return
    try:
        text = re.sub(r'^\-юзер', '', msg.text.lower().strip()).strip()
        amount = int(text.split()[0])
        cur.execute("SELECT total_users_manual FROM global_stats WHERE id = 1")
        current = cur.fetchone()[0] or 0
        if current >= amount:
            cur.execute("UPDATE global_stats SET total_users_manual = total_users_manual - ? WHERE id = 1", (amount,))
            conn.commit()
            await msg.answer(f"-{amount} пользователей")
        else:
            await msg.answer("Нельзя снять больше чем есть")
    except:
        pass

# ===== АДМИН: ПРОВЕРКА ВСЕХ =====
@dp.message(lambda m: m.text and m.text.lower() == "чек всех")
async def check_all_users(msg: Message):
    if msg.from_user.id not in ADMINS:
        return
    
    placeholders = ','.join('?' * len(ADMINS))
    users = cur.execute(
        f"SELECT id, username, first_name, balance FROM users WHERE balance > 0 AND banned = 0 AND id NOT IN ({placeholders}) ORDER BY balance DESC",
        ADMINS
    ).fetchall()
    
    if not users:
        await msg.answer("Нет пользователей с балансом")
        return
    
    admin_modes[msg.from_user.id] = {"users": users, "page": 0}
    await send_users_page(msg, msg.from_user.id, 0)

async def send_users_page(source, user_id: int, page: int):
    data = admin_modes.get(user_id, {})
    users = data.get("users", [])
    if not users:
        return
    
    per_page = 10
    start = page * per_page
    end = start + per_page
    page_users = users[start:end]
    total_pages = (len(users) + per_page - 1) // per_page
    
    text = f"Страница {page + 1} из {total_pages}\nВсего: {len(users)}\n\n"
    
    for i, user in enumerate(page_users, start=start + 1):
        uid = user[0]
        name = user[1] or user[2] or str(uid)
        balance = user[3]
        if len(name) > 20:
            name = name[:17] + "..."
        text += f"{i}. {name} — {balance} $\n"
    
    kb = InlineKeyboardBuilder()
    
    row1 = []
    if page > 0:
        row1.append(InlineKeyboardButton(text="Назад", callback_data=f"ul_page:{user_id}:{page - 1}"))
    row1.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="ignore"))
    if page + 1 < total_pages:
        row1.append(InlineKeyboardButton(text="Вперед", callback_data=f"ul_page:{user_id}:{page + 1}"))
    kb.row(*row1)
    kb.row(InlineKeyboardButton(text="Закрыть", callback_data=f"ul_close:{user_id}"))
    
    if hasattr(source, 'message'):
        await source.message.edit_text(text, reply_markup=kb.as_markup())
        await source.answer()
    else:
        await source.answer(text, reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("ul_page:"))
async def userlist_page(call: CallbackQuery):
    parts = call.data.split(":")
    if len(parts) != 3:
        return
    
    _, user_id_str, page_str = parts
    user_id = int(user_id_str)
    page = int(page_str)
    
    if call.from_user.id != user_id:
        return
    
    if user_id in admin_modes:
        admin_modes[user_id]["page"] = page
    
    await send_users_page(call, user_id, page)

@dp.callback_query(F.data.startswith("ul_close:"))
async def userlist_close(call: CallbackQuery):
    parts = call.data.split(":")
    if len(parts) != 2:
        return
    
    user_id = int(parts[1])
    if call.from_user.id == user_id and user_id in admin_modes:
        del admin_modes[user_id]
    await call.message.delete()
    await call.answer()

# ===== АДМИН: ПРОВЕРКА БАЛАНСА =====
@dp.message(lambda m: m.text and m.text.lower().startswith("чек") and m.text.lower() != "чек всех")
async def check_balance(msg: Message):
    if msg.from_user.id not in ADMINS:
        return
    try:
        text = re.sub(r'^чек', '', msg.text.lower().strip()).strip()
        uid = int(text.split()[0])
        balance = get_balance_by_id(uid)
        cur.execute("SELECT id FROM users WHERE id=?", (uid,))
        reg = cur.fetchone() is not None
        status = "зарегистрирован" if reg else "не зарегистрирован"
        await msg.answer(f"ID: {uid}\nБаланс: {balance}$\nСтатус: {status}")
    except:
        pass

# ===== АДМИН: ССЫЛКИ =====
@dp.message(lambda m: m.text and m.text.lower().startswith("+линк"))
async def add_link(msg: Message):
    if msg.from_user.id not in ADMINS:
        return
    text = re.sub(r'^\+линк', '', msg.text.strip()).strip()
    if not text:
        return
    cur.execute("INSERT INTO links(text) VALUES(?)", (text,))
    conn.commit()
    await msg.answer("Ссылка добавлена")

@dp.message(F.text == "-линк")
async def del_link_list(msg: Message):
    if msg.from_user.id not in ADMINS:
        return
    links = cur.execute("SELECT * FROM links").fetchall()
    if not links:
        await msg.answer("Ссылок нет")
        return
    kb = InlineKeyboardBuilder()
    for l in links:
        btn_text = (l[1][:27] + '...') if len(l[1]) > 30 else l[1]
        kb.button(text=btn_text, callback_data=f"dellink:{l[0]}")
    kb.button(text="Готово", callback_data="close_links")
    kb.adjust(1)
    await msg.answer("Выберите ссылку для удаления:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("dellink"))
async def delete_link(call: CallbackQuery):
    if call.from_user.id not in ADMINS:
        return
    link_id = call.data.split(":")[1]
    cur.execute("DELETE FROM links WHERE id=?", (link_id,))
    conn.commit()
    await call.answer("Удалено")
    links = cur.execute("SELECT * FROM links").fetchall()
    if not links:
        await call.message.edit_text("Все ссылки удалены")
        return
    kb = InlineKeyboardBuilder()
    for l in links:
        btn_text = (l[1][:27] + '...') if len(l[1]) > 30 else l[1]
        kb.button(text=btn_text, callback_data=f"dellink:{l[0]}")
    kb.button(text="Готово", callback_data="close_links")
    kb.adjust(1)
    await call.message.edit_text("Выберите ссылку для удаления:", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "close_links")
async def close_links(call: CallbackQuery):
    await call.message.delete()

# ===== АДМИН: РАССЫЛКА =====
@dp.message(lambda m: m.text and m.text.lower().startswith("/send"))
async def send_message(msg: Message):
    if msg.from_user.id not in ADMINS:
        return
    text = re.sub(r'^/send', '', msg.text.strip()).strip()
    if not text:
        return
    
    users = cur.execute("SELECT id FROM users WHERE banned = 0").fetchall()
    if not users:
        await msg.answer("Нет пользователей")
        return
    
    sent = 0
    for user in users:
        try:
            await bot.send_message(user[0], text)
            sent += 1
            await asyncio.sleep(0.05)
        except:
            pass
    
    await msg.answer(f"Отправлено: {sent}")

# ===== КАЛЬКУЛЯТОР =====
def safe_calc(expression: str):
    try:
        expression = expression.replace(' ', '')
        if not all(c in '0123456789+-*/^%().' for c in expression):
            return None, "Недопустимые символы"
        expression = expression.replace('^', '**')
        if '/0' in expression:
            return None, "Деление на ноль"
        result = eval(expression, {"__builtins__": {}}, {})
        if isinstance(result, float):
            if result.is_integer():
                result = int(result)
            else:
                result = round(result, 10)
        return result, None
    except ZeroDivisionError:
        return None, "Деление на ноль"
    except:
        return None, "Ошибка"

@dp.message()
async def auto_calculator(message: Message):
    if is_banned(message.from_user.id):
        await message.answer("Вы забанены")
        return
    text = message.text
    if not text or text.startswith('/'):
        return
    if not re.search(r'[+\-*/^%]', text) or not re.search(r'\d', text):
        return
    expression = re.sub(r'[^0-9+\-*/^%().]', '', text)
    if not expression:
        return
    result, error = safe_calc(expression)
    if error:
        await message.reply(error)
    else:
        await message.reply(f"{result}")

# ===== ЗАПУСК =====
async def handle(request):
    return web.Response(text="Бот работает")

async def start_web():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()

async def main():
    print("Бот запущен")
    asyncio.create_task(check_payments_loop())
    await start_web()
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
