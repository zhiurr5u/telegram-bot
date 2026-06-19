#!/usr/bin/env python3
"""
ربات آپلودر تلگرام
- ادمین فایل آپلود می‌کنه و لینک می‌گیره
- کاربرا با لینک فایل رو دریافت می‌کنن
- پنل ادمین با آمار، پیام همگانی و مدیریت
"""

import os
import json
import asyncio
from datetime import datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# ─── تنظیمات ────────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "0").split(",") if x.strip().isdigit()]
CHANNEL_ID = os.environ.get("CHANNEL_ID", "")
DB_FILE = "database.json"

# ─── دیتابیس ────────────────────────────────────────────────
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
        db["users"][uid] = {
            "id": user.id,
            "name": user.full_name,
            "username": user.username or "",
            "joined": datetime.now().isoformat(),
            "downloads": 0
        }
        save_db(db)
        return True  # کاربر جدید
    return False

def is_admin(user_id):
    return user_id in ADMIN_IDS

# ─── هندلرها ────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_new = register_user(user)

    # اگه با پارامتر /start file_XXXX اومد → ارسال فایل
    if context.args and context.args[0].startswith("file_"):
        file_code = context.args[0][5:]
        await send_file_to_user(update, context, file_code)
        return

    text = (
        f"👋 سلام {user.first_name}!\n\n"
        "🤖 به ربات اشتراک‌گذاری فایل خوش اومدی.\n\n"
        "📥 برای دریافت فایل، روی لینک مربوطه کلیک کن.\n"
    )

    if is_admin(user.id):
        text += "\n\n🔧 *پنل ادمین* از دستور /admin در دسترسه."

    await update.message.reply_text(text, parse_mode="Markdown")


async def send_file_to_user(update: Update, context: ContextTypes.DEFAULT_TYPE, file_code: str):
    db = load_db()
    user = update.effective_user

    if file_code not in db["files"]:
        await update.message.reply_text("❌ فایل پیدا نشد یا حذف شده.")
        return

    file_info = db["files"][file_code]
    msg_id = file_info["message_id"]
    auto_delete = file_info.get("auto_delete_seconds")

    try:
        # فوروارد از کانال ذخیره‌سازی
        sent_msg = await context.bot.forward_message(
            chat_id=update.effective_chat.id,
            from_chat_id=CHANNEL_ID,
            message_id=msg_id
        )

        # ثبت دانلود
        uid = str(user.id)
        if uid in db["users"]:
            db["users"][uid]["downloads"] += 1
        db["files"][file_code]["downloads"] = db["files"][file_code].get("downloads", 0) + 1
        save_db(db)

        if auto_delete:
            notice = await update.message.reply_text(
                f"✅ فایل ارسال شد!\n"
                f"⏱ این پیام و فایل بعد از *{auto_delete} ثانیه* حذف می‌شن.",
                parse_mode="Markdown"
            )
            context.job_queue.run_once(
                delete_user_message_later,
                when=auto_delete,
                data={"chat_id": update.effective_chat.id, "message_id": sent_msg.message_id}
            )
            context.job_queue.run_once(
                delete_user_message_later,
                when=auto_delete,
                data={"chat_id": update.effective_chat.id, "message_id": notice.message_id}
            )
        else:
            await update.message.reply_text(
                f"✅ فایل با موفقیت ارسال شد!\n"
                f"📁 نام: {file_info.get('name', 'نامشخص')}\n"
                f"📊 تعداد دانلود: {db['files'][file_code]['downloads']}"
            )

    except Exception as e:
        await update.message.reply_text(f"❌ خطا در ارسال فایل: {e}")


async def delete_user_message_later(context: ContextTypes.DEFAULT_TYPE):
    """حذف پیام کاربر بعد از تایمر"""
    job_data = context.job.data
    try:
        await context.bot.delete_message(
            chat_id=job_data["chat_id"],
            message_id=job_data["message_id"]
        )
    except Exception:
        pass  # اگه قبلاً حذف شده بود خطا نده


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت فایل از ادمین و ارسال به کانال ذخیره"""
    user = update.effective_user

    if not is_admin(user.id):
        await update.message.reply_text("⛔️ فقط ادمین‌ها می‌تونن فایل آپلود کنن.")
        return

    msg = update.message
    wait_msg = await msg.reply_text("⏳ در حال پردازش...")

    # تشخیص نوع فایل
    if msg.photo:
        file_id = msg.photo[-1].file_id
        file_name = "photo.jpg"
        file_type = "photo"
    elif msg.video:
        file_id = msg.video.file_id
        file_name = msg.video.file_name or "video.mp4"
        file_type = "video"
    elif msg.document:
        file_id = msg.document.file_id
        file_name = msg.document.file_name or "document"
        file_type = "document"
    elif msg.audio:
        file_id = msg.audio.file_id
        file_name = msg.audio.file_name or "audio.mp3"
        file_type = "audio"
    elif msg.voice:
        file_id = msg.voice.file_id
        file_name = "voice.ogg"
        file_type = "voice"
    else:
        await wait_msg.edit_text("❌ نوع فایل پشتیبانی نمی‌شه.")
        return

    # بررسی تایمر از caption فایل
    # فرمت: عدد ثانیه در کپشن مثلاً "60" یا "timer:60"
    auto_delete_seconds = None
    caption = msg.caption or ""
    if caption.startswith("timer:"):
        try:
            auto_delete_seconds = int(caption.split(":")[1].strip())
        except ValueError:
            pass
    elif caption.strip().isdigit():
        auto_delete_seconds = int(caption.strip())

    try:
        # ارسال به کانال ذخیره‌سازی
        forwarded = await msg.forward(chat_id=CHANNEL_ID)
        storage_msg_id = forwarded.message_id

        # ساخت کد یکتا
        file_code = f"{file_id[-8:]}{storage_msg_id}"

        # ذخیره در دیتابیس
        db = load_db()
        db["files"][file_code] = {
            "code": file_code,
            "name": file_name,
            "type": file_type,
            "message_id": storage_msg_id,
            "uploaded_by": user.id,
            "uploaded_at": datetime.now().isoformat(),
            "downloads": 0,
            "auto_delete_seconds": auto_delete_seconds  # null = بدون تایمر
        }
        save_db(db)

        # ساخت لینک
        bot_username = (await context.bot.get_me()).username
        share_link = f"https://t.me/{bot_username}?start=file_{file_code}"

        timer_text = f"\n⏱ *حذف خودکار:* `{auto_delete_seconds}` ثانیه بعد از دریافت" if auto_delete_seconds else ""

        await wait_msg.edit_text(
            f"✅ *فایل با موفقیت آپلود شد!*\n\n"
            f"📁 نام: `{file_name}`\n"
            f"🔑 کد: `{file_code}`\n"
            f"{timer_text}\n\n"
            f"🔗 *لینک دانلود:*\n`{share_link}`\n\n"
            f"_این لینک رو با کاربرا به اشتراک بذار_\n\n"
            f"💡 برای تایمر، عدد ثانیه رو تو کپشن فایل بنویس (مثلاً `60`)",
            parse_mode="Markdown"
        )

    except Exception as e:
        await wait_msg.edit_text(
            f"❌ خطا در آپلود:\n`{e}`\n\n"
            "⚠️ مطمئن شو ربات ادمین کانال ذخیره‌سازیه.",
            parse_mode="Markdown"
        )


# ─── پنل ادمین ──────────────────────────────────────────────

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ دسترسی ندارید.")
        return

    db = load_db()
    total_users = len(db["users"])
    total_files = len(db["files"])
    total_downloads = sum(f.get("downloads", 0) for f in db["files"].values())

    text = (
        "🔧 *پنل مدیریت*\n\n"
        f"👥 کاربران: `{total_users}`\n"
        f"📁 فایل‌ها: `{total_files}`\n"
        f"📥 دانلودها: `{total_downloads}`\n"
    )

    keyboard = [
        [
            InlineKeyboardButton("👥 لیست کاربران", callback_data="admin_users"),
            InlineKeyboardButton("📁 لیست فایل‌ها", callback_data="admin_files"),
        ],
        [
            InlineKeyboardButton("📢 پیام همگانی", callback_data="admin_broadcast"),
            InlineKeyboardButton("📊 آمار کامل", callback_data="admin_stats"),
        ],
    ]

    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        await query.edit_message_text("⛔️ دسترسی ندارید.")
        return

    data = query.data
    db = load_db()

    if data == "admin_users":
        users = list(db["users"].values())[-10:]  # آخرین ۱۰ کاربر
        text = f"👥 *آخرین کاربران ({len(db['users'])} نفر کل)*\n\n"
        for u in users:
            name = u.get("name", "نامشخص")
            uid = u.get("id")
            dl = u.get("downloads", 0)
            text += f"• {name} | `{uid}` | ⬇️{dl}\n"

        back_btn = [[InlineKeyboardButton("🔙 برگشت", callback_data="admin_back")]]
        await query.edit_message_text(text, parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(back_btn))

    elif data == "admin_files":
        files = list(db["files"].values())[-10:]
        text = f"📁 *آخرین فایل‌ها ({len(db['files'])} فایل کل)*\n\n"
        for f in files:
            text += f"• `{f['name']}` | ⬇️{f.get('downloads',0)} | {f['type']}\n"

        back_btn = [[InlineKeyboardButton("🔙 برگشت", callback_data="admin_back")]]
        await query.edit_message_text(text, parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(back_btn))

    elif data == "admin_stats":
        total_users = len(db["users"])
        total_files = len(db["files"])
        total_downloads = sum(f.get("downloads", 0) for f in db["files"].values())
        top_files = sorted(db["files"].values(), key=lambda x: x.get("downloads", 0), reverse=True)[:5]

        text = (
            "📊 *آمار کامل*\n\n"
            f"👥 کل کاربران: `{total_users}`\n"
            f"📁 کل فایل‌ها: `{total_files}`\n"
            f"📥 کل دانلودها: `{total_downloads}`\n\n"
            "🏆 *پرطرفدارترین فایل‌ها:*\n"
        )
        for f in top_files:
            text += f"• {f['name']} | ⬇️{f.get('downloads', 0)}\n"

        back_btn = [[InlineKeyboardButton("🔙 برگشت", callback_data="admin_back")]]
        await query.edit_message_text(text, parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(back_btn))

    elif data == "admin_broadcast":
        context.user_data["awaiting_broadcast"] = True
        back_btn = [[InlineKeyboardButton("🔙 انصراف", callback_data="admin_back")]]
        await query.edit_message_text(
            "📢 *پیام همگانی*\n\nمتن پیامت رو بنویس:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(back_btn)
        )

    elif data == "admin_back":
        total_users = len(db["users"])
        total_files = len(db["files"])
        total_downloads = sum(f.get("downloads", 0) for f in db["files"].values())

        text = (
            "🔧 *پنل مدیریت*\n\n"
            f"👥 کاربران: `{total_users}`\n"
            f"📁 فایل‌ها: `{total_files}`\n"
            f"📥 دانلودها: `{total_downloads}`\n"
        )
        keyboard = [
            [
                InlineKeyboardButton("👥 لیست کاربران", callback_data="admin_users"),
                InlineKeyboardButton("📁 لیست فایل‌ها", callback_data="admin_files"),
            ],
            [
                InlineKeyboardButton("📢 پیام همگانی", callback_data="admin_broadcast"),
                InlineKeyboardButton("📊 آمار کامل", callback_data="admin_stats"),
            ],
        ]
        await query.edit_message_text(text, parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(keyboard))


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت پیام‌های متنی - شامل پیام همگانی"""
    register_user(update.effective_user)

    if is_admin(update.effective_user.id) and context.user_data.get("awaiting_broadcast"):
        context.user_data["awaiting_broadcast"] = False
        broadcast_text = update.message.text
        db = load_db()
        users = list(db["users"].keys())

        sent, failed = 0, 0
        status_msg = await update.message.reply_text(f"⏳ در حال ارسال به {len(users)} کاربر...")

        for uid in users:
            try:
                await context.bot.send_message(chat_id=int(uid), text=broadcast_text)
                sent += 1
                await asyncio.sleep(0.05)  # جلوگیری از ریت‌لیمیت
            except Exception:
                failed += 1

        await status_msg.edit_text(
            f"✅ پیام همگانی ارسال شد!\n\n"
            f"✔️ موفق: `{sent}`\n"
            f"❌ ناموفق: `{failed}`",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "📎 برای دریافت فایل روی لینک کلیک کن.\n"
            "اگه ادمین هستی فایل/عکس/ویدیو بفرست تا لینکش رو بگیری."
        )


# ─── اجرا ───────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))

    # هندلر فایل‌ها
    app.add_handler(MessageHandler(
        filters.PHOTO | filters.VIDEO | filters.Document.ALL |
        filters.AUDIO | filters.VOICE,
        handle_file
    ))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(admin_callback))

    print("🤖 ربات شروع به کار کرد...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
                
