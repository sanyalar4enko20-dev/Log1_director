import asyncio
import sqlite3
import requests
import hashlib
import os
import re
import logging
import socket

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

# ===== ПРОВЕРКА ПОДПИСКИ =====
CHANNEL_ID = "-1003875497744"

class SubscriptionMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any]
    ) -> Any:
        
        if event.from_user.id in ADMINS:
            return await handler(event, data)
        
        try:
            member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=event.from_user.id)
            if member.status in ['member', 'administrator', 'creator']:
                return await handler(event, data)
        except:
            return await handler(event, data)
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 Подписаться", url="https://t.me/perehodnik_split_a_huli_net")],
            [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_sub")]
        ])
        
        await event.answer(
            "🚫 Доступ к боту только для подписчиков канала!\n\n"
            "Подпишитесь и нажмите кнопку проверки:",
            reply_markup=keyboard
        )
        return

dp.message.middleware(SubscriptionMiddleware())
print("✅ Проверка подписки активирована")

@dp.callback_query(F.data == "check_sub")
async def check_subscription(call: CallbackQuery):
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=call.from_user.id)
        if member.status in ['member', 'administrator', 'creator']:
            await call.message.edit_text("✅ Подписка подтверждена! Нажмите /start")
        else:
            await call.answer("❌ Вы не подписаны!", show_alert=True)
    except Exception as e:
        await call.answer(f"❌ Ошибка: {str(e)[:50]}", show_alert=True)

# ===== БАЗА ДАННЫХ =====
conn = sqlite3.connect("shop.db")
cur = conn.cursor()

cur.execute("""CREATE TABLE IF NOT EXISTS users(
id INTEGER PRIMARY KEY,
username TEXT,
first_name TEXT,
balance REAL DEFAULT 0,
purchases INTEGER DEFAULT 0,
total_deposit REAL DEFAULT 0,
registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")

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
        cur.execute("INSERT INTO users (id, username, first_name, balance, purchases, total_deposit) VALUES (?, ?, ?, ?, ?, ?)",
                   (admin_id, "admin", "Admin", 0, 0, 0))
        conn.commit()

cur.execute("SELECT id FROM global_stats WHERE id = 1")
if not cur.fetchone():
    cur.execute("INSERT INTO global_stats (id, total_deposit, total_users_manual) VALUES (1, 0, 0)")
    conn.commit()

print("✅ База данных готова")

# ===== ОСНОВНЫЕ ФУНКЦИИ =====
def get_user(uid, username, name):
    cur.execute("SELECT * FROM users WHERE id=?", (uid,))
    u = cur.fetchone()
    
    if not u:
        cur.execute("""INSERT INTO users 
                      (id, username, first_name, balance, purchases, total_deposit) 
                      VALUES (?,?,?,?,?,?)""",
                   (uid, username, name, 0, 0, 0))
        conn.commit()
    else:
        cur.execute("UPDATE users SET username=?, first_name=? WHERE id=?", (username, name, uid))
        conn.commit()
    
    return cur.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()

def get_balance_by_id(uid):
    cur.execute("SELECT balance FROM users WHERE id=?", (uid,))
    result = cur.fetchone()
    return result[0] if result else 0

def add_balance(uid, amt):
    cur.execute("SELECT id FROM users WHERE id=?", (uid,))
    if not cur.fetchone():
        cur.execute("""INSERT INTO users 
                      (id, username, first_name, balance, purchases, total_deposit) 
                      VALUES (?,?,?,?,?,?)""",
                   (uid, "", "", amt, 0, amt))
        conn.commit()
    else:
        cur.execute("UPDATE users SET balance=balance+?, total_deposit=total_deposit+? WHERE id=?", (amt, amt, uid))
        conn.commit()
    
    cur.execute("UPDATE global_stats SET total_deposit = total_deposit + ? WHERE id = 1", (amt,))
    conn.commit()

def remove_balance(uid, amt):
    cur.execute("SELECT id FROM users WHERE id=?", (uid,))
    if not cur.fetchone():
        cur.execute("""INSERT INTO users 
                      (id, username, first_name, balance, purchases, total_deposit) 
                      VALUES (?,?,?,?,?,?)""",
                   (uid, "", "", 0, 0, 0))
        conn.commit()
    
    cur.execute("UPDATE users SET balance=balance-? WHERE id=?", (amt, uid))
    conn.commit()
    return True

async def notify_admins(text):
    for a in ADMINS:
        try:
            await bot.send_message(a, text)
        except:
            pass

# ===== CRYPTO PAY =====
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
    kb.button(text="🛒 Магазин")
    kb.button(text="👤 Профиль")
    kb.button(text="💳 Пополнить")
    kb.button(text="💰 Баланс")
    kb.button(text="📞 Поддержка")
    kb.button(text="📊 Статистика")
    if uid in ADMINS:
        kb.button(text="⚙️ Админ")
    kb.adjust(2, 2, 1, 1, 1)
    return kb.as_markup(resize_keyboard=True)

def back_kb():
    kb = ReplyKeyboardBuilder()
    kb.button(text="⬅️ Назад")
    return kb.as_markup(resize_keyboard=True)

# ===== FSM СОСТОЯНИЯ =====
class AddItem(StatesGroup):
    name = State()
    data = State()
    price = State()
    amount = State()

class Deposit(StatesGroup):
    amount = State()

class AdminBalance(StatesGroup):
    uid = State()
    amount = State()

class AdminStatsDeposit(StatesGroup):
    amount = State()

class AdminUsers(StatesGroup):
    amount = State()

class AdminCheck(StatesGroup):
    pass

class AdminSend(StatesGroup):
    text = State()

admin_modes = {}

# ===== СТАРТ =====
@dp.message(F.text == "/start")
async def start(msg: Message, state: FSMContext):
    await state.clear()
    get_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    await msg.answer(
        "Добро пожаловать!\n\n"
        "Выберите опцию в меню:",
        reply_markup=main_kb(msg.from_user.id)
    )

@dp.message(F.text == "⬅️ Назад")
async def back(msg: Message, state: FSMContext):
    await state.clear()
    if msg.from_user.id in admin_modes:
        del admin_modes[msg.from_user.id]
    await msg.answer("Главное меню", reply_markup=main_kb(msg.from_user.id))

# ===== ПРОФИЛЬ =====
@dp.message(F.text == "👤 Профиль")
async def profile(msg: Message):
    u = get_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    await msg.answer(
        f"Профиль\n\n"
        f"ID: {u[0]}\n"
        f"Имя: {u[2]}\n"
        f"Баланс: {u[3]} $\n"
        f"Покупок: {u[4]}",
        reply_markup=main_kb(msg.from_user.id)
    )

# ===== БАЛАНС =====
@dp.message(F.text == "💰 Баланс")
async def bal(msg: Message):
    u = get_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    await msg.answer(f"Баланс: {u[3]} $", reply_markup=main_kb(msg.from_user.id))

# ===== ПОДДЕРЖКА =====
@dp.message(F.text == "📞 Поддержка")
async def support(msg: Message):
    await msg.answer("Связь: @director_a_huli_net")

# ===== СТАТИСТИКА =====
@dp.message(F.text == "📊 Статистика")
async def stats(msg: Message):
    cur.execute("SELECT total_deposit, total_users_manual FROM global_stats WHERE id = 1")
    result = cur.fetchone()
    total_deposit = result[0] if result else 0
    manual_users = result[1] if result else 0
    real_users = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0] or 0
    total_users = real_users + manual_users
    total_buys = cur.execute("SELECT SUM(purchases) FROM users").fetchone()[0] or 0
    links = cur.execute("SELECT text FROM links").fetchall()
    links_text = "\n".join(l[0] for l in links)
    
    text = f"Статистика\n\nПользователей: {total_users}\nПополнено: {round(total_deposit,2)} $\nПокупок: {total_buys}\n"
    if links_text:
        text += "\nРепутация / проекты:\n" + links_text
    await msg.answer(text, disable_web_page_preview=True)

# ===== ПОПОЛНЕНИЕ =====
@dp.message(F.text == "💳 Пополнить")
async def dep(msg: Message, state: FSMContext):
    await state.set_state(Deposit.amount)
    await msg.answer("Введите сумму в долларах:", reply_markup=back_kb())

@dp.message(Deposit.amount)
async def dep2(msg: Message, state: FSMContext):
    try:
        amt = float(msg.text)
    except:
        await msg.answer("Ошибка: введите число", reply_markup=back_kb())
        return

    inv_response = create_invoice(amt)
    if 'result' not in inv_response:
        await msg.answer("Ошибка создания счета. Попробуйте позже.")
        return

    inv = inv_response['result']
    await state.update_data(inv=inv["invoice_id"], amt=amt)
    kb = InlineKeyboardBuilder()
    kb.button(text="Оплатить", url=inv["pay_url"])
    kb.button(text="Проверить", callback_data="check")
    await msg.answer(f"Оплатите {amt}$", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "check")
async def check(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if 'inv' not in data:
        await call.answer("Платеж не найден. Начните заново.", show_alert=True)
        await state.clear()
        return
    if check_invoice(data["inv"]) == "paid":
        add_balance(call.from_user.id, data["amt"])
        await call.message.answer("Средства зачислены", reply_markup=main_kb(call.from_user.id))
        await state.clear()
    else:
        await call.answer("Еще не оплачено", show_alert=True)

# ===== МАГАЗИН =====
@dp.message(F.text == "🛒 Магазин")
async def shop(msg: Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="📂 Логи", callback_data="cat:лог:0")
    kb.button(text="👤 Акки", callback_data="cat:акк:0")
    kb.button(text="📘 Мануалы", callback_data="cat:мануал:0")
    kb.button(text="📦 Разное", callback_data="cat:разное:0")
    kb.button(text="⬅️ Назад", callback_data="back_main")
    kb.adjust(2, 2, 1)
    await msg.answer("Категории:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("cat"))
async def cat(call: CallbackQuery):
    _, t, page = call.data.split(":")
    page = int(page)

    items = cur.execute("SELECT * FROM items WHERE type=?", (t,)).fetchall()
    if not items:
        await call.answer("В этой категории пусто", show_alert=True)
        return

    per = 10
    start = page * per
    page_items = items[start:start+per]
    if not page_items:
        await call.answer("Тут больше нет товаров", show_alert=True)
        return

    kb = InlineKeyboardBuilder()
    text = f"Категория: {t}\n\n"
    
    for i, it in enumerate(page_items, start=start+1):
        amt = "∞" if it[5] == -1 else it[5]
        text += f"{i}. {it[2]} | {amt} шт. | {it[4]} $\n"
    
    buy_buttons = []
    for i, it in enumerate(page_items, start=start+1):
        buy_buttons.append(InlineKeyboardButton(text=f"Купить {i}", callback_data=f"buy:{it[0]}"))
    
    for i in range(0, len(buy_buttons), 2):
        if i + 1 < len(buy_buttons):
            kb.row(buy_buttons[i], buy_buttons[i+1])
        else:
            kb.row(buy_buttons[i])
    
    total_pages = (len(items) + per - 1) // per
    pagination_buttons = []
    
    if start > 0:
        pagination_buttons.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"cat:{t}:{page-1}"))
    pagination_buttons.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="ignore"))
    if start + per < len(items):
        pagination_buttons.append(InlineKeyboardButton(text="Вперед ▶️", callback_data=f"cat:{t}:{page+1}"))
    
    kb.row(*pagination_buttons)
    kb.row(InlineKeyboardButton(text="Главное меню", callback_data="back_main"))

    try:
        await call.message.delete()
    except:
        pass
    
    await call.message.answer(text, reply_markup=kb.as_markup())
    await call.answer()

@dp.callback_query(F.data.startswith("buy"))
async def buy(call: CallbackQuery):
    item_id = call.data.split(":")[1]
    item = cur.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    kb = InlineKeyboardBuilder()
    kb.button(text="Да", callback_data=f"yes:{item_id}")
    kb.button(text="Нет", callback_data="cancel")
    await call.message.answer(f"{item[2]} | {item[4]} $\nПодтвердить покупку?", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("yes"))
async def yes(call: CallbackQuery):
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
            await notify_admins(f"Закончился товар: {item[2]}")
        else:
            cur.execute("UPDATE items SET amount=? WHERE id=?", (new, item_id))
        conn.commit()
    await notify_admins(f"Купили: {item[2]}")

@dp.callback_query(F.data == "back_main")
async def back_main(call: CallbackQuery):
    await call.message.answer("Главное меню", reply_markup=main_kb(call.from_user.id))

# ===== АДМИН ПАНЕЛЬ =====
@dp.message(F.text == "⚙️ Админ")
async def admin(msg: Message):
    if msg.from_user.id not in ADMINS:
        return
    kb = ReplyKeyboardBuilder()
    kb.button(text="+лог")
    kb.button(text="-лог")
    kb.button(text="+мануал")
    kb.button(text="-мануал")
    kb.button(text="+акк")
    kb.button(text="-акк")
    kb.button(text="+разное")
    kb.button(text="-разное")
    kb.button(text="+$")
    kb.button(text="-$")
    kb.button(text="+$$$")
    kb.button(text="-$$$")
    kb.button(text="$$$")
    kb.button(text="+юзер")
    kb.button(text="-юзер")
    kb.button(text="чек")
    kb.button(text="/send")
    kb.button(text="⬅️ Назад")
    kb.adjust(2)
    await msg.answer("Админ панель", reply_markup=kb.as_markup(resize_keyboard=True))

# ===== АДМИН: ДОБАВЛЕНИЕ ТОВАРОВ =====
@dp.message(F.text.in_(["+лог", "+мануал", "+акк", "+разное"]))
async def add_start(msg: Message, state: FSMContext):
    if msg.from_user.id not in ADMINS:
        return
    await state.clear()
    item_type = msg.text[1:]
    await state.update_data(item_type=item_type)
    await state.set_state(AddItem.name)
    await msg.answer("Введите название:", reply_markup=back_kb())

@dp.message(AddItem.name)
async def add_name(msg: Message, state: FSMContext):
    if msg.text == "⬅️ Назад":
        await state.clear()
        await msg.answer("Отмена", reply_markup=main_kb(msg.from_user.id))
        return
    await state.update_data(item_name=msg.text)
    await state.set_state(AddItem.data)
    await msg.answer("Введите содержимое:", reply_markup=back_kb())

@dp.message(AddItem.data)
async def add_data(msg: Message, state: FSMContext):
    if msg.text == "⬅️ Назад":
        await state.clear()
        await msg.answer("Отмена", reply_markup=main_kb(msg.from_user.id))
        return
    await state.update_data(item_data=msg.text)
    await state.set_state(AddItem.price)
    await msg.answer("Введите цену:", reply_markup=back_kb())

@dp.message(AddItem.price)
async def add_price(msg: Message, state: FSMContext):
    if msg.text == "⬅️ Назад":
        await state.clear()
        await msg.answer("Отмена", reply_markup=main_kb(msg.from_user.id))
        return
    try:
        price = float(msg.text)
    except:
        await msg.answer("Введите число", reply_markup=back_kb())
        return
    await state.update_data(item_price=price)
    await state.set_state(AddItem.amount)
    await msg.answer("Введите количество (-1 = бесконечно):", reply_markup=back_kb())

@dp.message(AddItem.amount)
async def add_amount(msg: Message, state: FSMContext):
    if msg.text == "⬅️ Назад":
        await state.clear()
        await msg.answer("Отмена", reply_markup=main_kb(msg.from_user.id))
        return
    try:
        amount = int(msg.text)
    except:
        await msg.answer("Введите целое число", reply_markup=back_kb())
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
        await msg.answer("В этой категории нет товаров")
        return
    kb = InlineKeyboardBuilder()
    for item_id, name in items:
        kb.button(text=name, callback_data=f"delitem:{item_id}")
    kb.button(text="Отмена", callback_data="cancel_del")
    kb.adjust(1)
    await msg.answer(f"Выберите товар для удаления из категории {t}:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("delitem:"))
async def delete_item(call: CallbackQuery):
    if call.from_user.id not in ADMINS:
        return
    item_id = call.data.split(":")[1]
    cur.execute("DELETE FROM items WHERE id=?", (item_id,))
    conn.commit()
    await call.answer("Товар удален")
    await call.message.delete()

@dp.callback_query(F.data == "cancel_del")
async def cancel_del(call: CallbackQuery):
    await call.message.delete()
    await call.message.answer("Удаление отменено")

# ===== АДМИН: УПРАВЛЕНИЕ БАЛАНСОМ =====
@dp.message(lambda m: m.text and m.text.lower() == "+$")
async def plus_money_start(msg: Message, state: FSMContext):
    if msg.from_user.id not in ADMINS:
        return
    admin_modes[msg.from_user.id] = {"mode": "plus_balance"}
    await msg.answer("Режим добавления баланса\n\nВведите ID и сумму (ID сумма) или напишите 'назад' для выхода:", reply_markup=back_kb())

@dp.message(lambda m: m.text and m.text.lower() == "-$")
async def minus_money_start(msg: Message, state: FSMContext):
    if msg.from_user.id not in ADMINS:
        return
    admin_modes[msg.from_user.id] = {"mode": "minus_balance"}
    await msg.answer("Режим снятия баланса\n\nВведите ID и сумму (ID сумма) или напишите 'назад' для выхода:", reply_markup=back_kb())

@dp.message(lambda m: m.text and m.text.lower().startswith("+$ "))
async def plus_money_direct(msg: Message):
    if msg.from_user.id not in ADMINS:
        return
    try:
        parts = msg.text.split()
        if len(parts) == 3:
            uid = int(parts[1])
            amount = float(parts[2])
            add_balance(uid, amount)
            await msg.answer(f"+{amount}$ пользователю {uid}")
    except:
        await msg.answer("Формат: +$ ID сумма")

@dp.message(lambda m: m.text and m.text.lower().startswith("-$ "))
async def minus_money_direct(msg: Message):
    if msg.from_user.id not in ADMINS:
        return
    try:
        parts = msg.text.split()
        if len(parts) == 3:
            uid = int(parts[1])
            amount = float(parts[2])
            remove_balance(uid, amount)
            await msg.answer(f"-{amount}$ у пользователя {uid}")
    except:
        await msg.answer("Формат: -$ ID сумма")

# ===== АДМИН: ИЗМЕНЕНИЕ СТАТИСТИКИ =====
@dp.message(lambda m: m.text and m.text.lower() == "+$$$")
async def add_stat_deposit_start(msg: Message, state: FSMContext):
    if msg.from_user.id not in ADMINS:
        return
    admin_modes[msg.from_user.id] = {"mode": "plus_stat"}
    await msg.answer("Режим увеличения статистики\n\nВведите сумму:", reply_markup=back_kb())

@dp.message(lambda m: m.text and m.text.lower() == "-$$$")
async def minus_stat_deposit_start(msg: Message, state: FSMContext):
    if msg.from_user.id not in ADMINS:
        return
    admin_modes[msg.from_user.id] = {"mode": "minus_stat"}
    await msg.answer("Режим уменьшения статистики\n\nВведите сумму:", reply_markup=back_kb())

@dp.message(lambda m: m.text and m.text.lower().startswith("+$$$ "))
async def add_stat_deposit_direct(msg: Message):
    if msg.from_user.id not in ADMINS:
        return
    try:
        parts = msg.text.split()
        if len(parts) == 2:
            amount = float(parts[1])
            cur.execute("UPDATE global_stats SET total_deposit = total_deposit + ? WHERE id = 1", (amount,))
            conn.commit()
            cur.execute("SELECT total_deposit FROM global_stats WHERE id = 1")
            new_total = cur.fetchone()[0] or 0
            await msg.answer(f"Общая сумма пополнений: {new_total}$ (+{amount}$)")
    except:
        await msg.answer("Формат: +$$$ сумма")

@dp.message(lambda m: m.text and m.text.lower().startswith("-$$$ "))
async def minus_stat_deposit_direct(msg: Message):
    if msg.from_user.id not in ADMINS:
        return
    try:
        parts = msg.text.split()
        if len(parts) == 2:
            amount = float(parts[1])
            cur.execute("SELECT total_deposit FROM global_stats WHERE id = 1")
            current = cur.fetchone()[0] or 0
            if current < amount:
                await msg.answer(f"Нельзя снять больше чем есть. Всего: {current}$")
                return
            cur.execute("UPDATE global_stats SET total_deposit = total_deposit - ? WHERE id = 1", (amount,))
            conn.commit()
            await msg.answer(f"Общая сумма пополнений: {current - amount}$ (-{amount}$)")
    except:
        await msg.answer("Формат: -$$$ сумма")

# ===== АДМИН: ИЗМЕНЕНИЕ КОЛИЧЕСТВА ПОЛЬЗОВАТЕЛЕЙ =====
@dp.message(lambda m: m.text and m.text.lower() == "+юзер")
async def add_manual_users_start(msg: Message, state: FSMContext):
    if msg.from_user.id not in ADMINS:
        return
    admin_modes[msg.from_user.id] = {"mode": "plus_users"}
    await msg.answer("Режим увеличения пользователей\n\nВведите количество:", reply_markup=back_kb())

@dp.message(lambda m: m.text and m.text.lower() == "-юзер")
async def minus_manual_users_start(msg: Message, state: FSMContext):
    if msg.from_user.id not in ADMINS:
        return
    admin_modes[msg.from_user.id] = {"mode": "minus_users"}
    await msg.answer("Режим уменьшения пользователей\n\nВведите количество:", reply_markup=back_kb())

@dp.message(lambda m: m.text and m.text.lower().startswith("+юзер "))
async def add_manual_users_direct(msg: Message):
    if msg.from_user.id not in ADMINS:
        return
    try:
        parts = msg.text.split()
        if len(parts) == 2:
            amount = int(parts[1])
            cur.execute("UPDATE global_stats SET total_users_manual = total_users_manual + ? WHERE id = 1", (amount,))
            conn.commit()
            cur.execute("SELECT total_users_manual FROM global_stats WHERE id = 1")
            new_total = cur.fetchone()[0] or 0
            await msg.answer(f"Ручных пользователей: {new_total} (+{amount})")
    except:
        await msg.answer("Формат: +юзер количество")

@dp.message(lambda m: m.text and m.text.lower().startswith("-юзер "))
async def minus_manual_users_direct(msg: Message):
    if msg.from_user.id not in ADMINS:
        return
    try:
        parts = msg.text.split()
        if len(parts) == 2:
            amount = int(parts[1])
            cur.execute("SELECT total_users_manual FROM global_stats WHERE id = 1")
            current = cur.fetchone()[0] or 0
            if current < amount:
                await msg.answer(f"Нельзя снять больше чем есть. Ручных: {current}")
                return
            cur.execute("UPDATE global_stats SET total_users_manual = total_users_manual - ? WHERE id = 1", (amount,))
            conn.commit()
            await msg.answer(f"Ручных пользователей: {current - amount} (-{amount})")
    except:
        await msg.answer("Формат: -юзер количество")

# ===== АДМИН: ПРОВЕРКА БАЛАНСА =====
@dp.message(lambda m: m.text and m.text.lower() == "чек")
async def check_balance_start(msg: Message, state: FSMContext):
    if msg.from_user.id not in ADMINS:
        return
    admin_modes[msg.from_user.id] = {"mode": "check"}
    await msg.answer("Режим проверки баланса\n\nВведите ID", reply_markup=back_kb())

@dp.message(lambda m: m.text and m.text.lower().startswith("чек "))
async def check_balance_direct(msg: Message):
    if msg.from_user.id not in ADMINS:
        return
    try:
        parts = msg.text.split()
        if len(parts) == 2:
            uid = int(parts[1])
            balance = get_balance_by_id(uid)
            cur.execute("SELECT id FROM users WHERE id=?", (uid,))
            is_registered = cur.fetchone() is not None
            status = "зарегистрирован" if is_registered else "не зарегистрирован"
            await msg.answer(f"ID: {uid}\nБаланс: {balance}$\nСтатус: {status}")
    except ValueError:
        await msg.answer("Введите числовой ID")
    except Exception as e:
        await msg.answer(f"Ошибка: {e}")

@dp.message(lambda m: m.text and m.text.lower() == "$$$")
async def show_stat_deposit(msg: Message):
    if msg.from_user.id not in ADMINS:
        return
    cur.execute("SELECT total_deposit FROM global_stats WHERE id = 1")
    total = cur.fetchone()[0] or 0
    await msg.answer(f"Общая сумма пополнений: {total}$")

# ===== ОБРАБОТЧИК РЕЖИМОВ =====
@dp.message()
async def handle_admin_modes(message: Message):
    uid = message.from_user.id
    
    if uid not in admin_modes:
        return
    
    text = message.text.strip()
    
    if text.lower() == "назад" or text.lower() == "⬅️ назад":
        del admin_modes[uid]
        await message.answer("Действие отменено", reply_markup=main_kb(uid))
        return
    
    mode = admin_modes[uid]["mode"]
    
    try:
        if mode == "check":
            try:
                user_id = int(text)
                balance = get_balance_by_id(user_id)
                cur.execute("SELECT id FROM users WHERE id=?", (user_id,))
                is_registered = cur.fetchone() is not None
                status = "зарегистрирован" if is_registered else "не зарегистрирован"
                await message.answer(f"ID: {user_id}\nБаланс: {balance}$\nСтатус: {status}")
            except ValueError:
                await message.answer("Введите числовой ID")
        
        elif mode == "plus_balance":
            parts = text.split()
            if len(parts) == 2:
                user_id = int(parts[0])
                amount = float(parts[1])
                add_balance(user_id, amount)
                await message.answer(f"+{amount}$ пользователю {user_id}")
            else:
                await message.answer("Формат: ID сумма")
        
        elif mode == "minus_balance":
            parts = text.split()
            if len(parts) == 2:
                user_id = int(parts[0])
                amount = float(parts[1])
                remove_balance(user_id, amount)
                await message.answer(f"-{amount}$ у пользователя {user_id}")
            else:
                await message.answer("Формат: ID сумма")
        
        elif mode == "plus_stat":
            amount = float(text)
            cur.execute("UPDATE global_stats SET total_deposit = total_deposit + ? WHERE id = 1", (amount,))
            conn.commit()
            cur.execute("SELECT total_deposit FROM global_stats WHERE id = 1")
            new_total = cur.fetchone()[0] or 0
            await message.answer(f"Общая сумма пополнений: {new_total}$ (+{amount}$)")
        
        elif mode == "minus_stat":
            amount = float(text)
            cur.execute("SELECT total_deposit FROM global_stats WHERE id = 1")
            current = cur.fetchone()[0] or 0
            if current < amount:
                await message.answer(f"Нельзя снять больше чем есть. Всего: {current}$")
            else:
                cur.execute("UPDATE global_stats SET total_deposit = total_deposit - ? WHERE id = 1", (amount,))
                conn.commit()
                await message.answer(f"Общая сумма пополнений: {current - amount}$ (-{amount}$)")
        
        elif mode == "plus_users":
            amount = int(text)
            cur.execute("UPDATE global_stats SET total_users_manual = total_users_manual + ? WHERE id = 1", (amount,))
            conn.commit()
            cur.execute("SELECT total_users_manual FROM global_stats WHERE id = 1")
            new_total = cur.fetchone()[0] or 0
            await message.answer(f"Ручных пользователей: {new_total} (+{amount})")
        
        elif mode == "minus_users":
            amount = int(text)
            cur.execute("SELECT total_users_manual FROM global_stats WHERE id = 1")
            current = cur.fetchone()[0] or 0
            if current < amount:
                await message.answer(f"Нельзя снять больше чем есть. Ручных: {current}")
            else:
                cur.execute("UPDATE global_stats SET total_users_manual = total_users_manual - ? WHERE id = 1", (amount,))
                conn.commit()
                await message.answer(f"Ручных пользователей: {current - amount} (-{amount})")
    
    except ValueError:
        await message.answer("Введите корректное число")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")

# ===== АДМИН: РАССЫЛКА =====
@dp.message(F.text == "/send")
async def send_start(msg: Message, state: FSMContext):
    if msg.from_user.id not in ADMINS:
        return
    await state.set_state(AdminSend.text)
    await msg.answer("Введите текст рассылки:", reply_markup=back_kb())

@dp.message(AdminSend.text)
async def send_text(msg: Message, state: FSMContext):
    if msg.text == "⬅️ Назад":
        await state.clear()
        await msg.answer("Отмена", reply_markup=main_kb(msg.from_user.id))
        return
    users = cur.execute("SELECT id FROM users").fetchall()
    sent = 0
    for user_id in users:
        try:
            await bot.send_message(user_id[0], msg.text)
            sent += 1
        except:
            pass
    await msg.answer(f"Рассылка отправлена {sent} пользователям")
    await state.clear()

# ===== УПРАВЛЕНИЕ ССЫЛКАМИ =====
@dp.message(F.text.startswith("+линк"))
async def add_link(msg: Message):
    if msg.from_user.id not in ADMINS:
        return
    text = msg.text.replace("+линк", "").strip()
    if not text:
        await msg.answer("Формат: +линк текст")
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
    await call.answer("Ссылка удалена", show_alert=False)
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

# ===== КАЛЬКУЛЯТОР =====
def safe_calc(expression: str):
    try:
        expression = expression.replace(' ', '')
        allowed = set('0123456789+-*/^%().')
        if not all(c in allowed for c in expression):
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
    except SyntaxError:
        return None, "Ошибка синтаксиса"
    except Exception as e:
        return None, f"Ошибка: {str(e)}"

@dp.message()
async def auto_calculator(message: Message):
    if message.from_user.id in admin_modes:
        return
    
    text = message.text
    if not text or text.startswith('/'):
        return
    if not re.search(r'[+\-*/^%]', text) or not re.search(r'\d', text):
        return
    if len(text) > 100:
        return
    expression = re.sub(r'[^0-9+\-*/^%().]', '', text)
    if not expression or not re.search(r'[+\-*/^%()]', expression):
        return
    result, error = safe_calc(expression)
    if error:
        await message.reply(error)
    else:
        await message.reply(f"{result}")

# ===== УНИВЕРСАЛЬНЫЙ ЗАПУСК =====
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

IS_REPLIT = bool(os.environ.get('REPL_ID') or os.environ.get('REPL_OWNER') or os.environ.get('REPLIT_DB_URL'))
IS_LOCAL = not IS_REPLIT

socket.setdefaulttimeout(60)

async def run_local_polling():
    retry_count = 0
    max_retries = 5
    
    while True:
        try:
            if retry_count > 0:
                logger.info(f"Попытка переподключения {retry_count}/{max_retries}")
            
            try:
                await bot.delete_webhook(request_timeout=30)
                logger.info("Вебхук удален")
            except Exception as e:
                logger.warning(f"Ошибка удаления вебхука: {e}")
            
            logger.info("Запуск polling...")
            await dp.start_polling(
                bot,
                skip_updates=True,
                allowed_updates=["message", "callback_query"],
                request_timeout=60
            )
            
            logger.warning("Polling остановился")
            retry_count += 1
            
            if retry_count >= max_retries:
                logger.error("Достигнут лимит переподключений")
                break
                
            await asyncio.sleep(5)
            
        except asyncio.TimeoutError:
            logger.warning("Таймаут подключения")
            retry_count += 1
            await asyncio.sleep(5)
            
        except Exception as e:
            logger.error(f"Ошибка в polling: {e}")
            retry_count += 1
            await asyncio.sleep(5)

async def run_replit_webhook():
    try:
        from aiohttp import web
        
        app = web.Application()
        
        async def handle_webhook(request):
            try:
                update_data = await request.json()
                update = Update.model_validate(update_data, context={"bot": bot})
                await dp.feed_update(bot, update)
                return web.Response(status=200)
            except Exception as e:
                logger.error(f"Ошибка в вебхуке: {e}")
                return web.Response(status=500)
        
        async def health_check(request):
            return web.Response(text="Бот работает")
        
        app.router.add_post("/webhook", handle_webhook)
        app.router.add_get("/", health_check)
        
        runner = web.AppRunner(app)
        await runner.setup()
        
        port = int(os.environ.get("PORT", 8080))
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        logger.info(f"Веб-сервер запущен на порту {port}")
        
        repl_slug = os.environ.get('REPL_SLUG', 'bot')
        repl_owner = os.environ.get('REPL_OWNER', 'replit')
        webhook_url = f"https://{repl_slug}.{repl_owner}.repl.co/webhook"
        
        for attempt in range(5):
            try:
                await bot.delete_webhook()
                await bot.set_webhook(
                    url=webhook_url,
                    max_connections=100,
                    allowed_updates=["message", "callback_query"]
                )
                logger.info(f"Вебхук установлен: {webhook_url}")
                break
            except Exception as e:
                logger.warning(f"Ошибка установки вебхука (попытка {attempt+1}): {e}")
                await asyncio.sleep(3)
        
        logger.info("Бот готов")
        
        while True:
            await asyncio.sleep(3600)
            
    except Exception as e:
        logger.error(f"Ошибка в вебхук режиме: {e}")
        raise

async def main():
    logger.info("Запуск...")
    
    if IS_REPLIT:
        logger.info("Режим: Replit (вебхук)")
        await run_replit_webhook()
    else:
        logger.info("Режим: локальный (polling)")
        await run_local_polling()

async def graceful_shutdown():
    logger.info("Завершение работы...")
    try:
        await bot.session.close()
    except:
        pass
    logger.info("Бот остановлен")

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки")
    finally:
        loop.run_until_complete(graceful_shutdown())
        loop.close()
