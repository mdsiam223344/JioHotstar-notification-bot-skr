import json
import logging
import os
import threading
import time
from pathlib import Path

import requests
import telebot

# Configure these in Render > Environment:
# BOT_TOKEN = Telegram bot token from @BotFather
# ADMIN_ID = your numeric Telegram user ID
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = os.getenv("ADMIN_ID", "").strip()
CHECK_INTERVAL = max(60, int(os.getenv("CHECK_INTERVAL", "300")))
DATA_DIR = Path(os.getenv("DATA_DIR", "/var/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

USERS_FILE = DATA_DIR / "users.json"
LAST_FILE = DATA_DIR / "last.json"

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("hotstar-bot")

if not BOT_TOKEN:
    raise RuntimeError("Missing BOT_TOKEN environment variable.")
if not ADMIN_ID.isdigit():
    raise RuntimeError("ADMIN_ID must be your numeric Telegram user ID.")

ADMIN_ID = int(ADMIN_ID)
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
data_lock = threading.Lock()


def load_json(path, default):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


users = set(str(x) for x in load_json(USERS_FILE, []))
last_ids = set(str(x) for x in load_json(LAST_FILE, []))


def save_json(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    tmp.replace(path)


def save_users():
    with data_lock:
        save_json(USERS_FILE, sorted(users))


def save_last():
    with data_lock:
        save_json(LAST_FILE, sorted(last_ids))


def check_hotstar():
    """Best-effort check of public Hotstar endpoints; endpoint/schema may change."""
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    }
    urls = [
        "https://www.hotstar.com/api/o/v1/tray/find?offset=0&size=20",
        "https://www.jiohotstar.com/api/o/v1/tray/find?offset=0&size=20",
    ]
    found = []
    seen_this_check = set()

    for url in urls:
        try:
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code != 200:
                log.warning("Hotstar endpoint returned HTTP %s", response.status_code)
                continue
            payload = response.json()
            items = payload.get("body", {}).get("results", {}).get("items", [])
            for tray in items:
                assets = tray.get("assets", {}).get("items", []) or tray.get("items", [])
                for item in assets[:10]:
                    item_id = str(item.get("id") or item.get("contentId") or item.get("title") or "")
                    title = item.get("title") or item.get("contentTitle") or item.get("name") or "New on JioHotstar"
                    if item_id and item_id not in last_ids and item_id not in seen_this_check:
                        found.append((item_id, title))
                        seen_this_check.add(item_id)
            if found:
                break
        except (requests.RequestException, ValueError, TypeError, AttributeError) as exc:
            log.warning("Hotstar check failed for endpoint: %s", exc)
        except Exception:
            log.exception("Unexpected error while checking Hotstar")
    return found


def send_to_subscribers(text):
    sent = 0
    for user_id in list(users):
        try:
            bot.send_message(int(user_id), text, disable_web_page_preview=True)
            sent += 1
            time.sleep(0.05)
        except Exception as exc:
            log.warning("Could not message subscriber %s: %s", user_id, exc)
    return sent


def notify_loop():
    global last_ids
    while True:
        try:
            items = check_hotstar()
            for item_id, title in items:
                if item_id in last_ids:
                    continue
                last_ids.add(item_id)
                # Keep the history bounded.
                if len(last_ids) > 1000:
                    last_ids = set(list(last_ids)[-800:])
                save_last()
                message = (
                    "🔔 <b>New content found on JioHotstar</b>\n\n"
                    f"<b>{telebot.util.escape(title)}</b>\n\n"
                    '<a href="https://www.jiohotstar.com">Open JioHotstar</a>'
                )
                send_to_subscribers(message)
        except Exception:
            log.exception("Notification loop failed")
        time.sleep(CHECK_INTERVAL)


@bot.message_handler(commands=["start"])
def start(message):
    users.add(str(message.chat.id))
    save_users()
    bot.reply_to(
        message,
        "Hello ✨\n✅ You are subscribed to JioHotstar notifications.\n\n"
        f"🔔 I check about every {CHECK_INTERVAL // 60} minute(s).\n"
        "/check — Check now\n"
        "/stop — Unsubscribe\n"
        "/zip 110001 — India PIN lookup",
    )


@bot.message_handler(commands=["stop"])
def stop(message):
    users.discard(str(message.chat.id))
    save_users()
    bot.reply_to(message, "❌ Unsubscribed. Send /start to subscribe again.")


@bot.message_handler(commands=["check"])
def check(message):
    bot.reply_to(message, "🔍 Checking JioHotstar...")
    items = check_hotstar()
    if not items:
        bot.send_message(message.chat.id, "No new updates detected. The source API may not expose new items.")
        return
    for item_id, title in items[:5]:
        bot.send_message(
            message.chat.id,
            f"📺 <b>{telebot.util.escape(title)}</b>\n"
            '<a href="https://www.jiohotstar.com">Open JioHotstar</a>',
            disable_web_page_preview=True,
        )


@bot.message_handler(commands=["zip", "pincode"])
def zip_lookup(message):
    parts = (message.text or "").split(maxsplit=1)
    code = parts[1].strip() if len(parts) > 1 else ""
    if not code:
        bot.reply_to(message, "Usage: /zip 110001")
        return
    bot.reply_to(message, f"🔍 Searching {telebot.util.escape(code)}...")
    try:
        response = requests.get(f"https://api.postalpincode.in/pincode/{code}", timeout=10)
        response.raise_for_status()
        payload = response.json()
        if payload and payload[0].get("Status") == "Success":
            office = payload[0]["PostOffice"][0]
            bot.send_message(
                message.chat.id,
                f"📮 <b>PIN: {telebot.util.escape(str(code))}</b>\n\n"
                f"<b>{telebot.util.escape(office['Name'])}</b>\n"
                f"District: {telebot.util.escape(office['District'])}\n"
                f"State: {telebot.util.escape(office['State'])}\n"
                f"Country: {telebot.util.escape(office['Country'])}",
            )
            return
    except Exception as exc:
        log.warning("PIN lookup failed: %s", exc)
    bot.send_message(message.chat.id, "❌ PIN not found. This lookup currently supports India PIN codes.")


@bot.message_handler(commands=["users"])
def count_users(message):
    if message.chat.id != ADMIN_ID:
        return
    bot.reply_to(message, f"👥 Subscribers: {len(users)}")


@bot.message_handler(commands=["broadcast"])
def broadcast(message):
    if message.chat.id != ADMIN_ID:
        return
    broadcast_text = (message.text or "").partition(" ")[2].strip()
    if not broadcast_text:
        bot.reply_to(message, "Usage: /broadcast Your message")
        return
    count = send_to_subscribers(broadcast_text)
    bot.reply_to(message, f"✅ Sent to {count} subscribers.")


def main():
    # Polling bots should run as a Render Background Worker, not a Web Service.
    threading.Thread(target=notify_loop, daemon=True, name="hotstar-notifier").start()
    log.info("Hotstar Telegram bot starting")
    bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=30)


if __name__ == "__main__":
    main()
