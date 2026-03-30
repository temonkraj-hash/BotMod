import json
import time
import re
import os
from telegram import Update, ChatPermissions
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters

# ===== ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ =====
TOKEN = os.getenv("TOKEN")
OWNER_ID = os.getenv("OWNER_ID")

if not TOKEN:
    raise ValueError("❌ Переменная окружения TOKEN не задана!")
if not OWNER_ID:
    raise ValueError("❌ Переменная окружения OWNER_ID не задана!")

OWNER_ID = int(OWNER_ID)

DATA_FILE = "data.json"

WHITELIST = {OWNER_ID}

# ===== ЗАГРУЗКА ДАННЫХ =====
def load_data():
    if not os.path.exists(DATA_FILE):
        # Если файла нет — создаём дефолтную структуру
        default_data = {
            "users": {},
            "admins": [],
            "banned_words": [],
            "politics_words": []
        }
        save_data(default_data)
        return default_data

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

data = load_data()

# ===== НОРМАЛИЗАЦИЯ =====
def normalize(text):
    text = text.lower()

    replacements = {
        "1": "и", "i": "и", "!": "и",
        "3": "е", "e": "е",
        "0": "о", "o": "о",
        "@": "а", "a": "а",
        "y": "у",
        "x": "х"
    }

    for k, v in replacements.items():
        text = text.replace(k, v)

    text = re.sub(r'[^а-я0-9 ]', '', text)
    return text

# ===== ПРОВЕРКИ =====
def is_admin(user_id):
    return user_id == OWNER_ID or user_id in data.get("admins", [])

# ===== НАРУШЕНИЯ =====
def add_violation(user_id):
    user_id = str(user_id)

    if user_id not in data["users"]:
        data["users"][user_id] = {"violations": 0}

    data["users"][user_id]["violations"] += 1
    save_data(data)

    return data["users"][user_id]["violations"]

# ===== НАКАЗАНИЕ =====
async def punish(update, user, violations):
    durations = [3600, 21600, 86400]  # 1ч, 6ч, 24ч

    if violations <= 3:
        duration = durations[violations - 1]
        until = int(time.time()) + duration

        await update.effective_chat.restrict_member(
            user.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until
        )

        await update.effective_chat.send_message(
            f"🚫 {user.first_name} получил мут на {duration//3600}ч.\n"
            f"Причина: нарушение правил чата\n"
            f"Нарушений: {violations}/3"
        )
    else:
        await update.effective_chat.ban_member(user.id)
        await update.effective_chat.send_message(
            f"💀 {user.first_name} забанен за систематические нарушения"
        )

# ===== ФИЛЬТР =====
async def filter_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return

    user = message.from_user

    if user.id in WHITELIST:
        return

    raw_text = message.text or ""
    text = normalize(raw_text)

    # КАПС
    if raw_text.isupper() and len(raw_text) > 10:
        await message.delete()
        return

    # ДУБЛИ
    last_key = f"last_{user.id}"
    if last_key in context.chat_data:
        if context.chat_data[last_key] == text:
            await message.delete()
            return
    context.chat_data[last_key] = text

    # ПОЛИТИКА
    for word in data.get("politics_words", []):
        if word in text:
            await message.delete()
            await message.chat.send_message(
                f"{user.first_name}, политика запрещена 🚫"
            )
            return

    # БАНВОРДЫ
    for word in data.get("banned_words", []):
        if word in text:
            await message.delete()
            v = add_violation(user.id)
            await punish(update, user, v)
            return

    # СПАМ
    key = f"spam_{user.id}"
    if key not in context.chat_data:
        context.chat_data[key] = []

    context.chat_data[key].append(time.time())
    context.chat_data[key] = context.chat_data[key][-10:]

    if len(context.chat_data[key]) >= 10:
        if context.chat_data[key][-1] - context.chat_data[key][0] < 5:
            await message.delete()
            v = add_violation(user.id)
            await punish(update, user, v)

# ===== КОМАНДЫ =====

async def banword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text("Используй: /banword слово")
        return

    word = context.args[0].lower()

    if word in data.get("banned_words", []):
        await update.message.reply_text("Уже есть")
        return

    data["banned_words"].append(word)
    save_data(data)

    await update.message.reply_text(f"Добавлено: {word}")

async def unbanword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        return

    word = context.args[0].lower()

    if word in data.get("banned_words", []):
        data["banned_words"].remove(word)
        save_data(data)
        await update.message.reply_text(f"Удалено: {word}")

async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Ответь на сообщение пользователя")
        return

    user = update.message.reply_to_message.from_user
    reason = " ".join(context.args) if context.args else "без причины"

    until = int(time.time()) + 3600

    await update.effective_chat.restrict_member(
        user.id,
        permissions=ChatPermissions(can_send_messages=False),
        until_date=until
    )

    await update.message.reply_text(
        f"{user.first_name} замучен на 1ч\nПричина: {reason}"
    )

async def purge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Используй: /purge количество")
        return

    count = int(context.args[0])

    async for msg in update.effective_chat.get_history(limit=count):
        try:
            await update.effective_chat.delete_message(msg.message_id)
        except:
            pass

# ===== ЗАПУСК =====
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("banword", banword))
    app.add_handler(CommandHandler("unbanword", unbanword))
    app.add_handler(CommandHandler("mute", mute))
    app.add_handler(CommandHandler("purge", purge))

    app.add_handler(MessageHandler(filters.ALL, filter_message))

    print("✅ Бот запущен и работает...")
    app.run_polling()

if name == "main":
    main()