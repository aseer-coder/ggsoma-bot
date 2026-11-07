# -*- coding: utf-8 -*-

import os
import time
import uuid
import threading
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
from flask import Flask

load_dotenv()

# ============ الإعدادات (تُسحب بأمان من Environment Variables في Koyeb) ============
BOT_TOKEN = os.getenv("BOT_TOKEN")
GG_API_KEY = os.getenv("GG_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "299836161"))

PROFIT_PERCENT = float(os.getenv("PROFIT_PERCENT", "0.20"))
PROFIT_FIXED = float(os.getenv("PROFIT_FIXED", "0"))

if not BOT_TOKEN or not GG_API_KEY:
    raise ValueError("❌ خطأ: يرجى إضافة BOT_TOKEN و GG_API_KEY في إعدادات Environment Variables!")

PAYMENT_INFO = """
💳 الدفع فقط عبر SuperQi - سوبر كي

🏦 SuperQi
🔢 رقم الحساب: 4592665147
📱 الرقم المرتبط بالحساب: 07806141636
👤 الاسم: Aseer

شلون تحول؟ عندك طريقتين، الاثنين توصل لنفس الحساب:

1️⃣ تحويل على رقم الحساب:
افتح تطبيق SuperQi > تحويل > الى رقم حساب > اكتب رقم الحساب الي فوق والمبلغ

2️⃣ تحويل على الرقم:
افتح تطبيق SuperQi > تحويل > على الرقم / الى رقم هاتف > اكتب الرقم المرتبط الي فوق والمبلغ

⚠️ مهم:
- حول المبلغ بالضبط مثل ما مكتوب
- بعد التحويل خذ سكرين للوصل الي بيه رقم العملية والمبلغ
- دز صورة الوصل هنا بالبوت
"""

GG_BASE = "https://ggsoma.store/api/partner/v1"
HEADERS = {"Authorization": f"Bearer {GG_API_KEY}", "Content-Type": "application/json"}

bot = telebot.TeleBot(BOT_TOKEN)

_cache = {"providers": None, "providers_time": 0, "products": {}, "products_time": {}}
pending_orders = {}
user_state = {}

# ============ دوال GGSoma API ============

def gg_get(path, params=None):
    print(f"GG GET {path} params={params}")
    try:
        r = requests.get(f"{GG_BASE}{path}", headers=HEADERS, params=params, timeout=20)
        return r.json()
    except Exception as e:
        return {"ok": False, "error": {"code": "NETWORK", "message": str(e)}}

def gg_post_order(slug, qty, external_id):
    try:
        payload = {"productSlug": slug, "quantity": qty, "externalOrderId": external_id}
        r = requests.post(f"{GG_BASE}/orders", headers=HEADERS, json=payload, timeout=30)
        return r.json()
    except Exception as e:
        return {"ok": False, "error": {"code": "NETWORK", "message": str(e)}}

def get_providers():
    if _cache["providers"] and time.time() - _cache["providers_time"] < 120:
        return _cache["providers"]
    data = gg_get("/catalog/providers")
    if data.get("ok") or "data" in data:
        _cache["providers"] = data.get("data", [])
        _cache["providers_time"] = time.time()
        return _cache["providers"]
    return []

def get_products(provider_key=None):
    key = provider_key or "all"
    if key in _cache["products"] and time.time() - _cache["products_time"].get(key, 0) < 120:
        return _cache["products"][key]
    params = {"provider": provider_key} if provider_key else None
    data = gg_get("/catalog/products", params=params)
    prods = []
    if isinstance(data, list):
        prods = data
    elif isinstance(data, dict):
        if isinstance(data.get("data"), list):
            prods = data["data"]
        elif isinstance(data.get("products"), list):
            prods = data["products"]
        elif isinstance(data.get("data"), dict) and isinstance(data["data"].get("products"), list):
            prods = data["data"]["products"]
    _cache["products"][key] = prods
    _cache["products_time"][key] = time.time()
    return prods

def get_product(slug):
    data = gg_get(f"/catalog/products/{slug}")
    if isinstance(data, dict):
        if "data" in data:
            return data["data"]
        if "slug" in data or "id" in data:
            return data
    return None

def sell_price(your_price_str):
    try:
        cost = float(your_price_str)
    except:
        cost = 0
    price = cost * (1 + PROFIT_PERCENT) + PROFIT_FIXED
    return round(price, 2), cost

def format_product(prod):
    name = prod.get("name", "")
    slug = prod.get("slug", "")
    your_price = prod.get("yourPrice") or prod.get("pricing", {}).get("yourUnitPrice", "0")
    sell, cost = sell_price(your_price)
    stock = prod.get("stock", {})
    in_stock = stock.get("inStock", True)
    count = stock.get("count", "?")
    duration = prod.get("durationDays", "")
    warranty = prod.get("warranty", {})
    delivery = prod.get("deliveryType", "")
    desc = prod.get("description", "") or ""
    inst = prod.get("instructions", "") or ""

    txt = f"🛍️ <b>{name}</b>\n\n"
    if desc:
        txt += f"{desc}\n\n"
    txt += f"💰 <b>السعر: {sell}$</b>\n"
    if duration:
        txt += f"⏳ المدة: {duration} يوم\n"
    if warranty.get("enabled"):
        txt += f"🛡️ ضمان: {warranty.get('days', '')} يوم\n"
    txt += f"📦 التوصيل: {delivery}\n"
    stock_txt = "متوفر" if in_stock else "نفذ"
    stock_icon = "✅" if in_stock else "❌"
    txt += f"📦 المخزون: {stock_icon} {stock_txt} ({count})\n"
    if inst:
        txt += f"\n📝 تعليمات: {inst}\n"
    txt += f"\n<code>{slug}</code>"
    return txt, sell, cost, in_stock

# ============ لوحة المفاتيح ============

def main_menu():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🛍️ عرض المنتجات", callback_data="menu_providers"))
    kb.add(InlineKeyboardButton("💰 رصيدي بالـ GGSoma (للأدمن)", callback_data="admin_balance"))
    kb.add(InlineKeyboardButton("❓ شلون اطلب؟", callback_data="how_to"))
    return kb

def providers_kb():
    kb = InlineKeyboardMarkup()
    provs = get_providers()
    if provs:
        for p in provs:
            emoji = ""
            if isinstance(p.get("emoji"), dict):
                emoji = p["emoji"].get("display", "") or p["emoji"].get("normal", "")
            name = p.get("name", p.get("key", ""))
            key = p.get("key", "")
            kb.add(InlineKeyboardButton(f"{emoji} {name}".strip(), callback_data=f"prov_{key}"))
    else:
        prods = get_products(None)
        for p in prods[:30]:
            your_price = p.get("yourPrice") or p.get("pricing", {}).get("yourUnitPrice", "0") if isinstance(p.get("pricing", {}), dict) else "0"
            try:
                sell, _ = sell_price(your_price)
            except:
                sell = your_price
            kb.add(InlineKeyboardButton(f"{p.get('name','')} - {sell}$", callback_data=f"prod_{p.get('slug','')}"))
    kb.add(InlineKeyboardButton("⬅️ الرئيسية", callback_data="menu_home"))
    return kb

# ============ الأوامر والرسائل ============

@bot.message_handler(commands=['start'])
def start(msg):
    bot.send_message(msg.chat.id,
        "هلا بيك بمتجري 😍\n\n"
        "هنا تبيع منتجات أصلية - توصيل فوري\n"
        "اختار القسم وشوف المنتجات، وادفع بماستر الرافدين او كي كارد.\n\n"
        "اضغط عرض المنتجات 👇",
        reply_markup=main_menu(), parse_mode="HTML")

@bot.message_handler(commands=['balance'])
def balance_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        bot.reply_to(msg, "هذا الامر للأدمن فقط.")
        return
    data = gg_get("/balance")
    if "balance" in data:
        bot.reply_to(msg, f"💰 رصيد GGSoma: {data['balance']} {data.get('currency','USD')}")
    else:
        bot.reply_to(msg, f"❌ خطأ: {data}")

@bot.message_handler(commands=['test'])
def test_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    bot.reply_to(msg, "اكتب: /testorder slug المنتج\nمثال: /testorder gemini-pro-monthly")

@bot.message_handler(commands=['testorder'])
def testorder_cmd(msg):
    if msg.from_user.id != ADMIN_ID:
        return
    parts = msg.text.split()
    if len(parts) < 2:
        bot.reply_to(msg, "اكتب السلگ: /testorder gemini-pro-monthly")
        return
    slug = parts[1].strip()
    ext = f"test-{msg.from_user.id}-{int(time.time())}"
    bot.reply_to(msg, f"⏳ جاري الطلب {slug} ...")
    res = gg_post_order(slug, 1, ext)
    bot.send_message(msg.chat.id, f"النتيجة:\n<code>{str(res)[:3000]}</code>", parse_mode="HTML")

@bot.message_handler(content_types=['photo'])
def photo_handler(msg):
    uid = msg.from_user.id
    st = user_state.get(uid)
    if not st or st.get("step") != "wait_receipt":
        bot.reply_to(msg, "اذا تريد تطلب، اختار منتج اولاً من /start")
        return
    slug = st["slug"]; qty = st["qty"]; sell_total = st["sell_total"]
    ext = f"bot-{uid}-{int(time.time())}-{uuid.uuid4().hex[:6]}"
    pending_orders[ext] = {"user_id": uid, "slug": slug, "qty": qty, "sell_total": sell_total, "username": msg.from_user.username}

    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton("✅ قبول وتنفيذ الطلب", callback_data=f"approve_{ext}"),
        InlineKeyboardButton("❌ رفض", callback_data=f"reject_{ext}")
    )
    bot.send_message(ADMIN_ID,
        f"🧾 طلب جديد بانتظار الموافقة\n\n"
        f"👤 الزبون: @{msg.from_user.username} (ID: {uid})\n"
        f"🛍️ المنتج: {slug}\n"
        f"🔢 الكمية: {qty}\n"
        f"💰 المبلغ: {sell_total}$\n"
        f"🆔 الطلب: {ext}\n\n"
        f"صورة الوصل تحت 👇",
        reply_markup=kb)
    bot.forward_message(ADMIN_ID, msg.chat.id, msg.message_id)
    bot.reply_to(msg, "✅ وصلني الوصل، انتظر موافقة الادمن، اول ما يوافق راح يوصلك المنتج مباشرة هنا.")
    user_state[uid] = {"step": "done"}

@bot.message_handler(func=lambda m: True)
def any_text(msg):
    uid = msg.from_user.id
    st = user_state.get(uid)
    if st and st.get("step") == "wait_qty":
        try:
            qty = int(msg.text.strip())
            if qty < 1 or qty > 50:
                bot.reply_to(msg, "الكمية لازم بين 1 و 50")
                return
            st["qty"] = qty
            st["step"] = "wait_receipt"
            prod = get_product(st["slug"])
            _, sell, _, _ = format_product(prod) if prod else (None, 0, 0, False)
            total = round(sell * qty, 2)
            st["sell_total"] = total
            bot.reply_to(msg, f"تمام، الكمية: {qty}\nالمبلغ الكلي: {total}$\n\n{PAYMENT_INFO}", parse_mode="HTML")
        except:
            bot.reply_to(msg, "اكتب رقم فقط، مثلا 2")
        return
    bot.reply_to(msg, "اضغط /start واختار منتج 👇")

@bot.callback_query_handler(func=lambda c: True)
def callbacks(call):
    data = call.data
    uid = call.from_user.id
    chat_id = call.message.chat.id

    if data == "menu_home":
        bot.edit_message_text("هلا بيك بمتجري 😍\nاختار 👇", chat_id, call.message.message_id, reply_markup=main_menu())
        return

    if data == "menu_providers":
        bot.edit_message_text("اختار القسم 👇\nاذا ما طلعت اقسام، يعني المنتجات راح تطلع مباشرة تحت", chat_id, call.message.message_id, reply_markup=providers_kb())
        return

    if data == "how_to":
        bot.edit_message_text(
            "❓ شلون تطلب؟\n\n"
            "1. اختار المنتج\n"
            "2. اضغط شراء واختار الكمية\n"
            "3. حول الفلوس على سوبر كي\n"
            "4. دز صورة الوصل هنا\n"
            "5. الادمن يوافق ويوصلك الكود / الرابط فوراً",
            chat_id, call.message.message_id,
            reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ رجوع", callback_data="menu_home")))
        return

    if data == "admin_balance":
        if uid != ADMIN_ID:
            bot.answer_callback_query(call.id, "للأدمن فقط", show_alert=True)
            return
        d = gg_get("/balance")
        bot.answer_callback_query(call.id, f"رصيدك: {d.get('balance','?')} USD")

    if data.startswith("prov_"):
        key = data.replace("prov_", "", 1)
        prods = get_products(key)
        if not prods:
            bot.answer_callback_query(call.id, "ماكو منتجات بهذا القسم حالياً", show_alert=True)
            return
        kb = InlineKeyboardMarkup()
        for p in prods[:30]:
            your_price = p.get("yourPrice") or p.get("pricing", {}).get("yourUnitPrice", "0")
            sell, _ = sell_price(your_price)
            kb.add(InlineKeyboardButton(f"{p.get('name','')} - {sell}$", callback_data=f"prod_{p.get('slug','')}"))
        kb.add(InlineKeyboardButton("⬅️ الاقسام", callback_data="menu_providers"))
        bot.edit_message_text(f"منتجات {key} 👇", chat_id, call.message.message_id, reply_markup=kb)
        return

    if data.startswith("prod_"):
        slug = data.replace("prod_", "", 1)
        prod = get_product(slug)
        if not prod:
            bot.answer_callback_query(call.id, "المنتج ما موجود", show_alert=True)
            return
        txt, sell, cost, in_stock = format_product(prod)
        kb = InlineKeyboardMarkup()
        if in_stock:
            kb.add(InlineKeyboardButton(f"✅ شراء - {sell}$", callback_data=f"buy_{slug}"))
        kb.add(InlineKeyboardButton("⬅️ رجوع", callback_data="menu_providers"))
        bot.edit_message_text(txt, chat_id, call.message.message_id, reply_markup=kb, parse_mode="HTML")
        return

    if data.startswith("buy_"):
        slug = data.replace("buy_", "", 1)
        prod = get_product(slug)
        if not prod:
            return
        _, sell, _, in_stock = format_product(prod)
        if not in_stock:
            bot.answer_callback_query(call.id, "نفذ المخزون", show_alert=True)
            return
        user_state[uid] = {"step": "wait_qty", "slug": slug, "sell_unit": sell}
        kb = InlineKeyboardMarkup()
        kb.add(
            InlineKeyboardButton("1", callback_data=f"qty_{slug}_1"),
            InlineKeyboardButton("2", callback_data=f"qty_{slug}_2"),
            InlineKeyboardButton("3", callback_data=f"qty_{slug}_3"),
            InlineKeyboardButton("5", callback_data=f"qty_{slug}_5"),
        )
        bot.edit_message_text(f"شكد تريد من {prod.get('name')}؟\nسعر الواحد: {sell}$\nاختار كمية او اكتب رقم بالشات 👇",
            chat_id, call.message.message_id, reply_markup=kb)
        return

    if data.startswith("qty_"):
        _, slug, qty_str = data.split("_", 2)
        qty = int(qty_str)
        prod = get_product(slug)
        _, sell, _, _ = format_product(prod) if prod else (None, 0, 0, False)
        total = round(sell * qty, 2)
        user_state[uid] = {"step": "wait_receipt", "slug": slug, "qty": qty, "sell_total": total}
        bot.edit_message_text(f"✅ اخترت: {prod.get('name')}\n🔢 الكمية: {qty}\n💰 المبلغ الكلي: {total}$\n\n{PAYMENT_INFO}",
            chat_id, call.message.message_id, parse_mode="HTML")
        return

    if data.startswith("approve_"):
        if uid != ADMIN_ID:
            bot.answer_callback_query(call.id, "للأدمن فقط", show_alert=True)
            return
        ext = data.replace("approve_", "", 1)
        order = pending_orders.get(ext)
        if not order:
            bot.answer_callback_query(call.id, "الطلب منتهي", show_alert=True)
            return
        bot.edit_message_text(f"⏳ جاري التنفيذ {order['slug']} ...", chat_id, call.message.message_id)
        res = gg_post_order(order["slug"], order["qty"], ext)
        if not res.get("ok"):
            err = res.get("error", {})
            bot.send_message(chat_id, f"❌ فشل الطلب: {err.get('code')} - {err.get('message')}")
            bot.send_message(order["user_id"], "❌ صار مشكلة بتنفيذ طلبك، راسل الادمن.")
            return
        delivery = res.get("delivery", {}) or {}
        lines = res.get("lines", []) or []
        dtype = res.get("deliveryType", "")
        order_code = res.get("orderCode", "")
        msg_txt = f"🎉 تم طلبك بنجاح!\n\n🆔 كود الطلب: {order_code}\n🛍️ المنتج: {order['slug']}\n🔢 الكمية: {order['qty']}\n\n📦 التوصيل:\n"
        if dtype == "LINK" and delivery.get("link"):
            msg_txt += f"🔗 الرابط: {delivery['link']}\n"
        elif dtype == "COUPON" and delivery.get("code"):
            msg_txt += f"🎟️ الكود: <code>{delivery['code']}</code>\n"
        elif dtype == "READY_ACCOUNT" and delivery.get("content"):
            msg_txt += f"👤 الحساب:\n<code>{delivery['content']}</code>\n"
        else:
            if lines:
                for ln in lines:
                    code_val = ln.get("code") or ln.get("link") or ln.get("content") or str(ln)
                    msg_txt += f"• <code>{code_val}</code>\n"
            elif delivery:
                msg_txt += f"<code>{delivery}</code>\n"
        if delivery.get("instructions"):
            msg_txt += f"\n📝 {delivery['instructions']}"
        msg_txt += "\n\nشكراً لشرائك من متجرنا ❤️"
        bot.send_message(order["user_id"], msg_txt, parse_mode="HTML")
        bot.send_message(chat_id, f"✅ تم التسليم للزبون @{order.get('username')} - {order_code}")
        del pending_orders[ext]
        return

    if data.startswith("reject_"):
        if uid != ADMIN_ID:
            return
        ext = data.replace("reject_", "", 1)
        order = pending_orders.pop(ext, None)
        if order:
            bot.send_message(order["user_id"], "❌ تم رفض طلبك، الوصل غير صحيح او غير واضح. راسل الادمن.")
            bot.edit_message_text("❌ تم الرفض", chat_id, call.message.message_id)
        return

# ============ سيرفر الويب الخفيف لـ Koyeb Health Check ============
app = Flask(__name__)

@app.route('/')
def health_check():
    return "GGSoma Bot is Alive!", 200

def run_flask():
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    # تشغيل سيرفر الويب في الخلفية لكي ينجح فحص Koyeb
    threading.Thread(target=run_flask, daemon=True).start()
    print("البوت اشتغل... اضغط /start")
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=30)
        except Exception as e:
            print(f"Polling error, retrying: {e}")
            time.sleep(5)
