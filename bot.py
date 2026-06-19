#!/usr/bin/env python3
import os, json, asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "0").split(",") if x.strip().isdigit()]
CHANNEL_ID = os.environ.get("CHANNEL_ID", "")
DB_FILE = "database.json"

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"users": {}, "files": {}}

def save_db(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def register_user(user):
    db = load_db()
    uid = str(user.id)
    if uid not in db["users"]:
        db["users"][uid] = {"id": user.id, "name": user.full_name, "username": user.username or "", "joined": datetime.now().isoformat(), "downloads": 0}
        save_db(db)
        return True
    return False

def is_admin(user_id):
    return user_id in ADMIN_IDS

async def delete_later(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    try:
        await context.bot.delete_message(chat_id=job_data["chat_id"], message_id=job_data["message_id"])
    except Exception:
        pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user)
    if context.args and context.args[0].startswith("file_"):
        file_code = context.args[0][5:]
        await send_file(update, context, file_code)
        return
    text = f"👋 سلام {user.first_name}!\n\n🤖 به ربات اشتراک‌گذاری فایل خوش اومدی.\n📥 برای دریافت فایل، روی لینک مربوطه کلیک کن."
    if is_admin(user.id):
        text += "\n\n🔧 پنل ادمین: /admin"
    await update.message.reply_text(text)

async def send_file(update: Update, context: ContextTypes.DEFAULT_TYPE, file_code: str):
    db = load_db()
    user = update.effective_user
    if file_code not in db["files"]:
        await update.message.reply_text("❌ فایل پیدا نشد یا حذف شده.")
        return
    file_info = db["files"][file_code]
    auto_delete = file_info.get("auto_delete_seconds")
    try:
        sent_msg = await context.bot.forward_message(chat_id=update.effective_chat.id, from_chat_id=CHANNEL_ID, message_id=file_info["message_id"])
        uid = str(user.id)
        db = load_db()
        if uid in db["users"]:
            db["users"][uid]["downloads"] += 1
        db["files"][file_code]["downloads"] = db["files"][file_code].get("downloads", 0) + 1
        save_db(db)
        if auto_delete:
            notice = await update.message.reply_text(f"✅ فایل ارسال شد!\n⏱ بعد از {auto_delete} ثانیه حذف می‌شه.", parse_mode="Markdown")
            context.job_queue.run_once(delete_later, when=auto_delete, data={"chat_id": update.effective_chat.id, "message_id": sent_msg.message_id})
            context.job_queue.run_once(delete_later, when=auto_delete, data={"chat_id": update.effective_chat.id, "message_id": notice.message_id})
        else:
            await update.message.reply_text(f"✅ فایل ارسال شد!\n📁 {file_info.get('name', 'نامشخص')}")
    except Exception as e:
        await update.message.reply_text(f"❌ خطا: {e}")

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⛔️ فقط ادمین‌ها می‌تونن فایل آپلود کنن.")
        return
    msg = update.message
    wait_msg = await msg.reply_text("⏳ در حال پردازش...")
    if msg.photo:
        file_id = msg.photo[-1].file_id; file_name = "photo.jpg"; file_type = "photo"
    elif msg.video:
        file_id = msg.video.file_id; file_name = msg.video.file_name or "video.mp4"; file_type = "video"
    elif msg.document:
        file_id = msg.document.file_id; file_name = msg.document.file_name or "document"; file_type = "document"
    elif msg.audio:
        file_id = msg.audio.file_id; file_name = msg.audio.file_name or "audio.mp3"; file_type = "audio"
    elif msg.voice:
        file_id = msg.voice.file_id; file_name = "voice.ogg"; file_type = "voice"
    else:
        await wait_msg.edit_text("❌ نوع فایل پشتیبانی نمی‌شه."); return
    auto_delete_seconds = None
    caption = msg.caption or ""
    if caption.startswith("timer:"):
        try: auto_delete_seconds = int(caption.split(":")[1].strip())
        except: pass
    elif caption.strip().isdigit():
        auto_delete_seconds = int(caption.strip())
    try:
        forwarded = await msg.forward(chat_id=CHANNEL_ID)
        file_code = f"{file_id[-8:]}{forwarded.message_id}"
        db = load_db()
        db["files"][file_code] = {"code": file_code, "name": file_name, "type": file_type, "message_id": forwarded.message_id, "uploaded_by": user.id, "uploaded_at": datetime.now().isoformat(), "downloads": 0, "auto_delete_seconds": auto_delete_seconds}
        save_db(db)
        bot_username = (await context.bot.get_me()).username
        share_link = f"https://t.me/{bot_username}?start=file_{file_code}"
        timer_text = f"\n⏱ حذف خودکار: {auto_delete_seconds} ثانیه" if auto_delete_seconds else ""
        await wait_msg.edit_text(f"✅ آپلود شد!\n📁 {file_name}{timer_text}\n\n🔗 لینک:\n`{share_link}`", parse_mode="Markdown")
    except Exception as e:
        await wait_msg.edit_text(f"❌ خطا: {e}\n⚠️ ربات باید ادمین کانال باشه.")

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ دسترسی ندارید."); return
    db = load_db()
    text = f"🔧 پنل مدیریت\n\n👥 کاربران: {len(db['users'])}\n📁 فایل‌ها: {len(db['files'])}\n📥 دانلودها: {sum(f.get('downloads',0) for f in db['files'].values())}"
    keyboard = [[InlineKeyboardButton("👥 کاربران", callback_data="admin_users"), InlineKeyboardButton("📁 فایل‌ها", callback_data="admin_files")], [InlineKeyboardButton("📢 پیام همگانی", callback_data="admin_broadcast"), InlineKeyboardButton("📊 آمار", callback_data="admin_stats")]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text("⛔️ دسترسی ندارید."); return
    db = load_db()
    back = [[InlineKeyboardButton("🔙 برگشت", callback_data="admin_back")]]
    if query.data == "admin_users":
        users = list(db["users"].values())[-10:]
        text = f"👥 کاربران ({len(db['users'])} نفر)\n\n" + "\n".join(f"• {u['name']} | {u['id']} | ⬇️{u.get('downloads',0)}" for u in users)
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(back))
    elif query.data == "admin_files":
        files = list(db["files"].values())[-10:]
        text = f"📁 فایل‌ها ({len(db['files'])} فایل)\n\n" + "\n".join(f"• {f['name']} | ⬇️{f.get('downloads',0)}" for f in files)
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(back))
    elif query.data == "admin_stats":
        top = sorted(db["files"].values(), key=lambda x: x.get("downloads",0), reverse=True)[:5]
        text = f"📊 آمار\n\n👥 {len(db['users'])} کاربر\n📁 {len(db['files'])} فایل\n📥 {sum(f.get('downloads',0) for f in db['files'].values())} دانلود\n\n🏆 پرطرفدار:\n" + "\n".join(f"• {f['name']} | ⬇️{f.get('downloads',0)}" for f in top)
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(back))
    elif query.data == "admin_broadcast":
        context.user_data["awaiting_broadcast"] = True
        await query.edit_message_text("📢 پیامت رو بنویس:", reply_markup=InlineKeyboardMarkup(back))
    elif query.data == "admin_back":
        db = load_db()
        text = f"🔧 پنل مدیریت\n\n👥 کاربران: {len(db['users'])}\n📁 فایل‌ها: {len(db['files'])}\n📥 دانلودها: {sum(f.get('downloads',0) for f in db['files'].values())}"
        keyboard = [[InlineKeyboardButton("👥 کاربران", callback_data="admin_users"), InlineKeyboardButton("📁 فایل‌ها", callback_data="admin_files")], [InlineKeyboardButton("📢 پیام همگانی", callback_data="admin_broadcast"), InlineKeyboardButton("📊 آمار", callback_data="admin_stats")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user)
    if is_admin(update.effective_user.id) and context.user_data.get("awaiting_broadcast"):
        context.user_data["awaiting_broadcast"] = False
        db = load_db()
        users = list(db["users"].keys())
        sent = failed = 0
        status = await update.message.reply_text(f"⏳ ارسال به {len(users)} کاربر...")
        for uid in users:
            try:
                await context.bot.send_message(chat_id=int(uid), text=update.message.text)
                sent += 1
                await asyncio.sleep(0.05)
            except:
                failed += 1
        await status.edit_text(f"✅ پیام همگانی ارسال شد!\n✔️ موفق: {sent}\n❌ ناموفق: {failed}")
    else:
        await update.message.reply_text("📎 برای دریافت فایل روی لینک کلیک کن.")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL | filters.AUDIO | filters.VOICE, handle_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(admin_callback))
    print("🤖 ربات شروع به کار کرد...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
                    
