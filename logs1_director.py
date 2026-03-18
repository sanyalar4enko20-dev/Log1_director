import requests
import time
import sqlite3
import json

TOKEN = "8653546812:AAHmXEiDaCx_kuAlWlH9mLAFFjfO3Svdbdc"
CRYPTO_TOKEN = "552232:AAHPmVzsS9UuK3Am3yeiSsEdnY6ryTyIMoi"

URL = f"https://api.telegram.org/bot{TOKEN}/"
CRYPTO_URL = "https://pay.crypt.bot/api/"

ADMINS = [6683316915, 5338814259]

last_update = 0
user_state = {}

conn = sqlite3.connect("shop.db", check_same_thread=False)
cur = conn.cursor()

# ---------- DB ----------
cur.execute("""
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    balance REAL DEFAULT 0,
    purchases INTEGER DEFAULT 0
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS items(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT,
    name TEXT,
    data TEXT,
    price REAL,
    amount INTEGER
)
""")
conn.commit()

# ---------- UTILS ----------
def send(uid, text, kb=None, reply_kb=None):
    data = {"chat_id": uid, "text": text}
    if kb:
        data["reply_markup"] = json.dumps(kb)
    if reply_kb:
        data["reply_markup"] = json.dumps(reply_kb)
    requests.post(URL + "sendMessage", data=data)

def answer(call_id, text):
    requests.post(URL + "answerCallbackQuery", data={
        "callback_query_id": call_id,
        "text": text,
        "show_alert": True
    })

def notify_admins(text):
    for admin in ADMINS:
        send(admin, text)

def safe_float(x):
    try:
        return float(x)
    except:
        return None

def safe_int(x):
    try:
        return int(x)
    except:
        return None

# ---------- USER ----------
def get_user(uid, username, name):
    cur.execute("SELECT * FROM users WHERE id=?", (uid,))
    user = cur.fetchone()

    if not user:
        cur.execute("INSERT INTO users(id,username,first_name) VALUES(?,?,?)",(uid,username,name))
        conn.commit()

    cur.execute("UPDATE users SET username=?, first_name=? WHERE id=?",(username,name,uid))
    conn.commit()

    return cur.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()

def add_balance(uid, amount):
    cur.execute("UPDATE users SET balance=balance+? WHERE id=?", (amount, uid))
    conn.commit()

def remove_balance(uid, amount):
    bal = cur.execute("SELECT balance FROM users WHERE id=?", (uid,)).fetchone()[0]
    if bal >= amount:
        cur.execute("UPDATE users SET balance=balance-? WHERE id=?", (amount, uid))
        conn.commit()
        return True
    return False

# ---------- CRYPTO ----------
def create_invoice(amount):
    headers = {"Crypto-Pay-API-Token": CRYPTO_TOKEN}
    r = requests.post(CRYPTO_URL+"createInvoice", headers=headers, json={
        "asset":"USDT","amount":amount
    }).json()
    return r["result"]

def check_invoice(iid):
    headers = {"Crypto-Pay-API-Token": CRYPTO_TOKEN}
    r = requests.get(CRYPTO_URL+"getInvoices", headers=headers).json()
    for i in r["result"]["items"]:
        if i["invoice_id"] == iid:
            return i["status"]
    return "none"

# ---------- KEYBOARDS ----------
def main_kb():
    return {
        "keyboard":[
            ["🛒 Магазин","💰 Баланс"],
            ["➕ Пополнить","👤 Профиль"]
        ],
        "resize_keyboard":True
    }

def shop_kb():
    return {
        "inline_keyboard":[
            [{"text":"📂 Логи","callback_data":"cat:log"}],
            [{"text":"👤 Аккаунты","callback_data":"cat:acc"}],
            [{"text":"📘 Мануалы","callback_data":"cat:manual"}],
            [{"text":"💻 Софты","callback_data":"soft"}],
            [{"text":"📦 Разное","callback_data":"cat:other"}],
            [{"text":"⬅️ Назад","callback_data":"back_main"}]
        ]
    }

# ---------- MSG ----------
def handle_msg(msg):
    uid = msg["from"]["id"]
    text = msg.get("text","")
    user = get_user(uid, msg["from"].get("username"), msg["from"].get("first_name"))

    if text == "/start":
        send(uid,"Добро пожаловать",reply_kb=main_kb())

    elif text == "🛒 Магазин":
        send(uid,"Выбери:",kb=shop_kb())

    elif text == "💰 Баланс":
        send(uid,f"{user[3]}$")

    elif text == "👤 Профиль":
        uname = f"@{user[1]}" if user[1] else "нет"
        send(uid,
            f"👤 Профиль\n\nИмя: {user[2]}\nЮзер: {uname}\nID: {uid}\n\n"
            f"💰 {user[3]}$\n🛒 {user[4]}"
        )

    elif text == "➕ Пополнить":
        user_state[uid]={"step":"dep"}
        send(uid,"Сумма:")

    elif uid in user_state and user_state[uid].get("step")=="dep":
        amt = safe_float(text)
        if amt is None:
            send(uid,"❌ число")
            return

        inv = create_invoice(amt)
        user_state[uid]={"inv":inv["invoice_id"],"amt":amt}

        send(uid,"Оплати",kb={
            "inline_keyboard":[
                [{"text":"Оплатить","url":inv["pay_url"]}],
                [{"text":"Проверить","callback_data":"check"}]
            ]
        })

    # ---------- ADD ----------
    elif uid in ADMINS and text in ["+лог","+мануал","+акк","+разное"]:
        user_state[uid]={"step":"name","type":text}
        send(uid,"Название:")

    elif uid in ADMINS and text in ["-лог","-мануал","-акк","-разное"]:
        mapping={"-лог":"+лог","-мануал":"+мануал","-акк":"+акк","-разное":"+разное"}
        t=mapping[text]

        items=cur.execute("SELECT * FROM items WHERE type=?", (t,)).fetchall()
        if not items:
            send(uid,"❌ Пусто")
            return

        kb={"inline_keyboard":[]}
        txt="Удалить:\n"
        for i,it in enumerate(items,1):
            txt+=f"#{i} {it[2]}\n"
            kb["inline_keyboard"].append([{"text":f"Удалить #{i}","callback_data":f"del:{it[0]}"}])

        send(uid,txt,kb=kb)

    elif uid in user_state and "type" in user_state[uid]:
        st=user_state[uid]

        if st["step"]=="name":
            st["name"]=text
            st["step"]="data"
            send(uid,"Данные:")

        elif st["step"]=="data":
            st["data"]=text
            st["step"]="price"
            send(uid,"Цена:")

        elif st["step"]=="price":
            val=safe_float(text)
            if val is None:
                send(uid,"❌ число")
                return
            st["price"]=val
            st["step"]="amount"
            send(uid,"Количество (-1=∞):")

        elif st["step"]=="amount":
            amt=-1 if text=="-1" else safe_int(text)
            if amt is None:
                send(uid,"❌ число")
                return

            cur.execute("INSERT INTO items(type,name,data,price,amount) VALUES(?,?,?,?,?)",
                        (st["type"],st["name"],st["data"],st["price"],amt))
            conn.commit()

            send(uid,"✅ добавлено")
            del user_state[uid]

    else:
        send(uid,"❌ Команда не найдена")

# ---------- CALLBACK ----------
def handle_call(call):
    uid=call["from"]["id"]
    data=call["data"]

    if data=="back_main":
        send(uid,"Меню",reply_kb=main_kb())
        return

    if data=="soft":
        answer(call["id"],"Скоро")
        return

    if data.startswith("cat:"):
        mapping={"log":"+лог","acc":"+акк","manual":"+мануал","other":"+разное"}
        items=cur.execute("SELECT * FROM items WHERE type=?", (mapping[data.split(":")[1]],)).fetchall()

        if not items:
            answer(call["id"],"❌ Пусто")
            return

        txt=""
        kb={"inline_keyboard":[]}

        for i,it in enumerate(items,1):
            amt="∞" if it[5]==-1 else f"{it[5]}шт."
            txt+=f"#{i} {it[2]} | {amt} | {it[4]}$\n"

            kb["inline_keyboard"].append([{"text":f"Купить #{i}","callback_data":f"buy:{it[0]}"}])

        kb["inline_keyboard"].append([{"text":"⬅️ Назад","callback_data":"shop"}])

        send(uid,txt,kb=kb)

    elif data=="shop":
        send(uid,"Категории:",kb=shop_kb())

    elif data.startswith("buy:"):
        item_id=data.split(":")[1]
        item=cur.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()

        if not remove_balance(uid,item[4]):
            answer(call["id"],"❌ Нет денег")
            return

        send(uid,item[3])

        cur.execute("UPDATE users SET purchases=purchases+1 WHERE id=?", (uid,))

        if item[5]!=-1:
            new=item[5]-1
            if new<=0:
                cur.execute("DELETE FROM items WHERE id=?", (item_id,))
                notify_admins(f"❗ Закончился: {item[2]}")
            else:
                cur.execute("UPDATE items SET amount=? WHERE id=?", (new,item_id))

        conn.commit()

    elif data.startswith("del:"):
        if uid not in ADMINS:
            return

        item_id=data.split(":")[1]
        cur.execute("DELETE FROM items WHERE id=?", (item_id,))
        conn.commit()
        answer(call["id"],"Удалено")

    elif data=="check":
        st=user_state.get(uid)
        if not st: return

        if check_invoice(st["inv"])=="paid":
            add_balance(uid,st["amt"])
            send(uid,"✅ зачислено")
            del user_state[uid]
        else:
            send(uid,"❌ не оплачено")

# ---------- LOOP ----------
def main():
    global last_update
    print("Бот запущен")

    while True:
        ups=requests.get(URL+"getUpdates",params={"offset":last_update+1}).json()["result"]

        for u in ups:
            last_update=u["update_id"]

            if "message" in u:
                handle_msg(u["message"])
            elif "callback_query" in u:
                handle_call(u["callback_query"])

        time.sleep(1)

if __name__=="__main__":
    main()