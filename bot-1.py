#!/usr/bin/env python3
import os, json, asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from telegram.error import TelegramError

# ═══════════════════════════════════════════
#   تنظیمات پایه - از Variables روی Railway می‌خونه
# ═══════════════════════════════════════════
BOT_TOKEN  = os.environ.get("BOT_TOKEN", "")
ADMIN_IDS  = [int(x) for x in os.environ.get("ADMIN_IDS", "0").split(",") if x.strip().lstrip("-").isdigit()]
CHANNEL_ID = os.environ.get("CHANNEL_ID", "")  # کانال ذخیره‌سازی فایل‌ها
DB_FILE    = "database.json"

# ═══════════════════════════════════════════
#   متن‌های پیش‌فرض ربات (از طریق پنل قابل تغییرن)
# ═══════════════════════════════════════════
DEFAULT_TEXTS = {
    "start": "👋 سلام {name}!\n\n🤖 به ربات اشتراک‌گذاری فایل خوش اومدی.\n📥 برای دریافت فایل، روی لینک مربوطه کلیک کن.",
    "start_admin_suffix": "\n\n🔧 پنل ادمین: /admin",
    "file_caption": "📁 {name}",
    "file_sent_extra": "",
    "join_required": "⛔️ برای دریافت فایل، اول باید تو کانال/گروه‌های زیر عضو بشی:\n\n{channels}\n\nبعد روی «✅ عضو شدم» بزن.",
    "join_check_btn": "✅ عضو شدم",
    "join_still_missing": "❌ هنوز تو همه‌ی موارد عضو نشدی. لطفاً عضو شو و دوباره امتحان کن.",
    "task_required": "🔗 برای دریافت فایل، اول باید رو لینک زیر بزنی:\n\n{link}\n\nبعد روی «✅ انجام دادم» بزن.",
    "task_btn": "✅ انجام دادم",
    "file_not_found": "❌ فایل پیدا نشد یا حذف شده.",
    "banned": "⛔️ شما توسط ادمین مسدود شده‌اید.",
    "not_admin": "⛔️ فقط ادمین‌ها می‌تونن فایل آپلود کنن.",
    "no_access": "⛔️ دسترسی ندارید.",
    "processing": "⏳ در حال پردازش...",
    "unsupported": "❌ نوع فایل پشتیبانی نمی‌شه.",
    "default_reply": "📎 برای دریافت فایل روی لینک کلیک کن.",
}

# ═══════════════════════════════════════════
#   دیتابیس ساده JSON
# ═══════════════════════════════════════════
def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "users": {},
        "files": {},
        "banned": [],
        "texts": {},
        "join_channels": [],   # [{"id":"@x","title":"x"}]
        "required_task": None, # {"link": "...", "label": "..."}
        "admins_extra": [],
    }

def save_db(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def get_text(key, **kwargs):
    db = load_db()
    text = db.get("texts", {}).get(key, DEFAULT_TEXTS.get(key, ""))
    try:
        return text.format(**kwargs)
    except Exception:
        return text

def all_admin_ids():
    db = load_db()
    return set(ADMIN_IDS) | set(db.get("admins_extra", []))

def is_admin(user_id):
    return user_id in all_admin_ids()

def register_user(user):
    db = load_db()
    uid = str(user.id)
    if uid not in db["users"]:
        db["users"][uid] = {
            "id": user.id, "name": user.full_name,
            "username": user.username or "",
            "joined": datetime.now().isoformat(),
            "downloads": 0
        }
        save_db(db)
    return db

def is_banned(user_id):
    db = load_db()
    return user_id in db.get("banned", [])

# ═══════════════════════════════════════════
#   عضویت اجباری
# ═══════════════════════════════════════════
async def check_join(bot, user_id):
    """برمی‌گردونه: (همه عضوه؟, لیست کانال‌هایی که عضو نیست)"""
    db = load_db()
    channels = db.get("join_channels", [])
    if not channels:
        return True, []
    missing = []
    for ch in channels:
        try:
            member = await bot.get_chat_member(chat_id=ch["id"], user_id=user_id)
            if member.status in ("left", "kicked"):
                missing.append(ch)
        except TelegramError:
            missing.append(ch)
    return len(missing) == 0, missing

def join_keyboard(channels, file_code=None):
    rows = []
    for ch in channels:
        url = ch["id"]
        if str(url).startswith("@"):
            url = f"https://t.me/{url[1:]}"
        rows.append([InlineKeyboardButton(f"📢 {ch['title']}", url=url)])
    cb = f"checkjoin_{file_code}" if file_code else "checkjoin_"
    rows.append([InlineKeyboardButton(get_text("join_check_btn"), callback_data=cb)])
    return InlineKeyboardMarkup(rows)

def task_keyboard(link, file_code=None):
    cb = f"checktask_{file_code}" if file_code else "checktask_"
    rows = [
        [InlineKeyboardButton("🔗 رفتن به لینک", url=link)],
        [InlineKeyboardButton(get_text("task_btn"), callback_data=cb)],
    ]
    return InlineKeyboardMarkup(rows)

# ═══════════════════════════════════════════
#   لایک/دیسلایک
# ═══════════════════════════════════════════
def file_reaction_keyboard(file_code, likes=0, dislikes=0):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(f"👍 {likes}", callback_data=f"like_{file_code}"),
        InlineKeyboardButton(f"👎 {dislikes}", callback_data=f"dislike_{file_code}"),
    ]])

async def handle_reaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    action, code = q.data.split("_", 1)
    db = load_db()
    if code not in db["files"]:
        await q.answer("فایل پیدا نشد", show_alert=True); return
    f = db["files"][code]
    f.setdefault("liked_by", []); f.setdefault("disliked_by", [])
    uid = q.from_user.id
    if action == "like":
        if uid in f["liked_by"]:
            f["liked_by"].remove(uid)
        else:
            f["liked_by"].append(uid)
            if uid in f["disliked_by"]: f["disliked_by"].remove(uid)
    else:
        if uid in f["disliked_by"]:
            f["disliked_by"].remove(uid)
        else:
            f["disliked_by"].append(uid)
            if uid in f["liked_by"]: f["liked_by"].remove(uid)
    save_db(db)
    try:
        await q.edit_message_reply_markup(
            reply_markup=file_reaction_keyboard(code, len(f["liked_by"]), len(f["disliked_by"]))
        )
    except TelegramError:
        pass
    await q.answer("✅ ثبت شد")

# ═══════════════════════════════════════════
#   ارسال فایل به کاربر (کپی، نه فوروارد)
# ═══════════════════════════════════════════
async def deliver_file(update_or_query, context, file_code, chat_id):
    db = load_db()
    if file_code not in db["files"]:
        target = update_or_query.message if hasattr(update_or_query, "message") else update_or_query
        await context.bot.send_message(chat_id=chat_id, text=get_text("file_not_found"))
        return
    info = db["files"][file_code]
    caption = info.get("custom_caption") or get_text("file_caption", name=info.get("name", ""))
    kb = file_reaction_keyboard(file_code, len(info.get("liked_by", [])), len(info.get("disliked_by", [])))
    try:
        sent = await context.bot.copy_message(
            chat_id=chat_id,
            from_chat_id=CHANNEL_ID,
            message_id=info["message_id"],
            caption=caption,
            reply_markup=kb,
        )
        db = load_db()
        db["files"][file_code]["downloads"] = db["files"][file_code].get("downloads", 0) + 1
        save_db(db)
        extra = get_text("file_sent_extra")
        if extra:
            await context.bot.send_message(chat_id=chat_id, text=extra)
        return sent
    except TelegramError as e:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ خطا در ارسال فایل: {e}")

# ═══════════════════════════════════════════
#   جریان دریافت فایل: بن؟ → عضویت؟ → وظیفه؟ → ارسال
# ═══════════════════════════════════════════
async def try_deliver_with_gates(update: Update, context: ContextTypes.DEFAULT_TYPE, file_code):
    user = update.effective_user
    chat_id = update.effective_chat.id

    if is_banned(user.id):
        await context.bot.send_message(chat_id=chat_id, text=get_text("banned"))
        return

    ok, missing = await check_join(context.bot, user.id)
    if not ok:
        context.user_data["pending_file"] = file_code
        await context.bot.send_message(
            chat_id=chat_id,
            text=get_text("join_required", channels="\n".join(f"• {c['title']}" for c in missing)),
            reply_markup=join_keyboard(missing, file_code),
        )
        return

    db = load_db()
    task = db.get("required_task")
    if task and str(user.id) not in task.get("done_by", []):
        context.user_data["pending_file"] = file_code
        await context.bot.send_message(
            chat_id=chat_id,
            text=get_text("task_required", link=task["link"]),
            reply_markup=task_keyboard(task["link"], file_code),
        )
        return

    await deliver_file(update, context, file_code, chat_id)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user)

    if is_banned(user.id):
        await update.message.reply_text(get_text("banned"))
        return

    if context.args and context.args[0].startswith("file_"):
        file_code = context.args[0][5:]
        await try_deliver_with_gates(update, context, file_code)
        return

    text = get_text("start", name=user.first_name)
    if is_admin(user.id):
        text += get_text("start_admin_suffix")
    await update.message.reply_text(text)

async def callback_check_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    file_code = q.data.split("_", 1)[1]
    ok, missing = await check_join(context.bot, q.from_user.id)
    if not ok:
        await q.answer(get_text("join_still_missing"), show_alert=True)
        return
    await q.answer("✅")
    try:
        await q.message.delete()
    except TelegramError:
        pass
    if file_code:
        await try_deliver_with_gates(update, context, file_code)

async def callback_check_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    file_code = q.data.split("_", 1)[1]
    db = load_db()
    task = db.get("required_task")
    if task:
        task.setdefault("done_by", [])
        uid = str(q.from_user.id)
        if uid not in task["done_by"]:
            task["done_by"].append(uid)
        save_db(db)
    await q.answer("✅")
    try:
        await q.message.delete()
    except TelegramError:
        pass
    if file_code:
        await try_deliver_with_gates(update, context, file_code)

# ═══════════════════════════════════════════
#   آپلود فایل توسط ادمین
# ═══════════════════════════════════════════
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text(get_text("not_admin"))
        return
    msg = update.message
    wait = await msg.reply_text(get_text("processing"))

    if msg.photo:
        file_id, file_name, file_type = msg.photo[-1].file_id, "photo.jpg", "photo"
    elif msg.video:
        file_id, file_name, file_type = msg.video.file_id, msg.video.file_name or "video.mp4", "video"
    elif msg.document:
        file_id, file_name, file_type = msg.document.file_id, msg.document.file_name or "file", "document"
    elif msg.audio:
        file_id, file_name, file_type = msg.audio.file_id, msg.audio.file_name or "audio.mp3", "audio"
    elif msg.voice:
        file_id, file_name, file_type = msg.voice.file_id, "voice.ogg", "voice"
    else:
        await wait.edit_text(get_text("unsupported")); return

    custom_caption = msg.caption if msg.caption else None

    try:
        fwd = await msg.forward(chat_id=CHANNEL_ID)
        code = f"{file_id[-8:]}{fwd.message_id}"
        db = load_db()
        db["files"][code] = {
            "code": code, "name": file_name, "type": file_type,
            "message_id": fwd.message_id, "uploaded_by": user.id,
            "uploaded_at": datetime.now().isoformat(),
            "downloads": 0, "liked_by": [], "disliked_by": [],
            "custom_caption": custom_caption,
        }
        save_db(db)
        me = (await context.bot.get_me()).username
        link = f"https://t.me/{me}?start=file_{code}"
        await wait.edit_text(
            f"✅ آپلود شد!\n📁 {file_name}\n🔑 کد: `{code}`\n\n🔗 لینک:\n`{link}`\n\n"
            f"💡 برای تغییر کپشن این فایل از پنل ادمین استفاده کن.",
            parse_mode=ParseMode.MARKDOWN
        )
    except TelegramError as e:
        await wait.edit_text(f"❌ خطا: {e}\n⚠️ ربات باید ادمین کانال ذخیره باشه.")

# ═══════════════════════════════════════════
#   پنل ادمین - منوی اصلی
# ═══════════════════════════════════════════
def main_admin_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📁 مدیریت فایل‌ها", callback_data="m_files"),
         InlineKeyboardButton("👥 مدیریت کاربران", callback_data="m_users")],
        [InlineKeyboardButton("🔒 عضویت اجباری", callback_data="m_join"),
         InlineKeyboardButton("🔗 وظیفه اجباری", callback_data="m_task")],
        [InlineKeyboardButton("📢 پیام همگانی", callback_data="m_broadcast"),
         InlineKeyboardButton("✉️ پیام به کاربر خاص", callback_data="m_dm")],
        [InlineKeyboardButton("✏️ تغییر متن‌های ربات", callback_data="m_texts"),
         InlineKeyboardButton("👑 ادمین‌ها", callback_data="m_admins")],
        [InlineKeyboardButton("📊 آمار", callback_data="m_stats")],
    ])

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(get_text("no_access")); return
    await update.message.reply_text("🔧 پنل مدیریت ربات", reply_markup=main_admin_menu())

async def show_main_menu(q):
    await q.edit_message_text("🔧 پنل مدیریت ربات", reply_markup=main_admin_menu())

def back_kb(target="m_back"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data=target)]])

# ─── زیرمنوها ───
def files_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 لیست فایل‌ها", callback_data="f_list")],
        [InlineKeyboardButton("🔙 برگشت", callback_data="m_back")],
    ])

def users_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 لیست کاربران", callback_data="u_list")],
        [InlineKeyboardButton("🚫 بن کردن کاربر", callback_data="u_ban")],
        [InlineKeyboardButton("✅ آنبن کردن کاربر", callback_data="u_unban")],
        [InlineKeyboardButton("📋 لیست مسدودها", callback_data="u_banlist")],
        [InlineKeyboardButton("🔙 برگشت", callback_data="m_back")],
    ])

def join_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزودن کانال/گروه", callback_data="j_add")],
        [InlineKeyboardButton("📋 لیست فعلی", callback_data="j_list")],
        [InlineKeyboardButton("🗑 حذف یکی", callback_data="j_remove")],
        [InlineKeyboardButton("🔙 برگشت", callback_data="m_back")],
    ])

def task_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ تنظیم/تغییر لینک وظیفه", callback_data="t_set")],
        [InlineKeyboardButton("🗑 حذف وظیفه اجباری", callback_data="t_remove")],
        [InlineKeyboardButton("🔙 برگشت", callback_data="m_back")],
    ])

def texts_menu():
    keys = [
        ("start", "متن استارت"),
        ("file_caption", "کپشن پیش‌فرض فایل"),
        ("file_sent_extra", "پیام بعد از ارسال فایل"),
        ("join_required", "متن عضویت اجباری"),
        ("task_required", "متن وظیفه اجباری"),
    ]
    rows = [[InlineKeyboardButton(label, callback_data=f"tx_{key}")] for key, label in keys]
    rows.append([InlineKeyboardButton("🔙 برگشت", callback_data="m_back")])
    return InlineKeyboardMarkup(rows)

def admins_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزودن ادمین", callback_data="a_add")],
        [InlineKeyboardButton("📋 لیست ادمین‌ها", callback_data="a_list")],
        [InlineKeyboardButton("🔙 برگشت", callback_data="m_back")],
    ])

# ═══════════════════════════════════════════
#   روتر کلیک‌های پنل ادمین
# ═══════════════════════════════════════════
async def admin_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer(get_text("no_access"), show_alert=True); return
    await q.answer()
    data = q.data
    db = load_db()

    if data == "m_back":
        context.user_data.pop("awaiting", None)
        await show_main_menu(q); return

    if data == "m_files":
        await q.edit_message_text("📁 مدیریت فایل‌ها", reply_markup=files_menu()); return

    if data == "f_list":
        files = list(db["files"].values())[-20:]
        if not files:
            text = "هیچ فایلی ثبت نشده."
        else:
            text = "📋 فایل‌ها (۲۰ تای آخر):\n\n"
            for f in files:
                text += f"• {f['name']} | کد: `{f['code']}` | ⬇️{f.get('downloads',0)} | 👍{len(f.get('liked_by',[]))} 👎{len(f.get('disliked_by',[]))}\n"
            text += "\nبرای حذف یا تغییر کپشن یه فایل، کد رو با دستور بفرست:\n`/delfile کد`\n`/caption کد متن جدید`"
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=back_kb("m_files")); return

    if data == "m_users":
        await q.edit_message_text("👥 مدیریت کاربران", reply_markup=users_menu()); return

    if data == "u_list":
        users = list(db["users"].values())[-20:]
        text = f"👥 کاربران ({len(db['users'])} نفر، ۲۰ تای آخر):\n\n"
        text += "\n".join(f"• {u['name']} | `{u['id']}` | ⬇️{u.get('downloads',0)}" for u in users)
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=back_kb("m_users")); return

    if data == "u_banlist":
        banned = db.get("banned", [])
        text = "🚫 کاربران مسدود:\n\n" + ("\n".join(f"• `{b}`" for b in banned) if banned else "خالیه.")
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=back_kb("m_users")); return

    if data == "u_ban":
        context.user_data["awaiting"] = "ban"
        await q.edit_message_text("🚫 آیدی عددی کاربری که می‌خوای بن کنی رو بفرست:", reply_markup=back_kb("m_users")); return

    if data == "u_unban":
        context.user_data["awaiting"] = "unban"
        await q.edit_message_text("✅ آیدی عددی کاربری که می‌خوای آنبن کنی رو بفرست:", reply_markup=back_kb("m_users")); return

    if data == "m_join":
        await q.edit_message_text("🔒 عضویت اجباری", reply_markup=join_menu()); return

    if data == "j_add":
        context.user_data["awaiting"] = "join_add"
        await q.edit_message_text(
            "➕ آیدی کانال/گروه رو بفرست (مثلاً @mychannel) - ربات باید ادمین اونجا باشه.\n"
            "بعدش اسم نمایشی رو هم می‌پرسم.",
            reply_markup=back_kb("m_join")
        ); return

    if data == "j_list":
        channels = db.get("join_channels", [])
        text = "📋 کانال‌های عضویت اجباری:\n\n" + ("\n".join(f"• {c['title']} ({c['id']})" for c in channels) if channels else "خالیه.")
        await q.edit_message_text(text, reply_markup=back_kb("m_join")); return

    if data == "j_remove":
        channels = db.get("join_channels", [])
        if not channels:
            await q.edit_message_text("لیست خالیه.", reply_markup=back_kb("m_join")); return
        rows = [[InlineKeyboardButton(f"🗑 {c['title']}", callback_data=f"jrm_{i}")] for i, c in enumerate(channels)]
        rows.append([InlineKeyboardButton("🔙 برگشت", callback_data="m_join")])
        await q.edit_message_text("کدوم رو حذف کنم؟", reply_markup=InlineKeyboardMarkup(rows)); return

    if data.startswith("jrm_"):
        idx = int(data.split("_")[1])
        channels = db.get("join_channels", [])
        if 0 <= idx < len(channels):
            removed = channels.pop(idx)
            db["join_channels"] = channels
            save_db(db)
            await q.edit_message_text(f"✅ {removed['title']} حذف شد.", reply_markup=back_kb("m_join"))
        return

    if data == "m_task":
        task = db.get("required_task")
        status = f"فعلی: {task['link']}" if task else "فعلاً تنظیم نشده."
        await q.edit_message_text(f"🔗 وظیفه اجباری\n\n{status}", reply_markup=task_menu()); return

    if data == "t_set":
        context.user_data["awaiting"] = "task_set"
        await q.edit_message_text("🔗 لینکی که کاربر باید روش کلیک کنه رو بفرست:", reply_markup=back_kb("m_task")); return

    if data == "t_remove":
        db["required_task"] = None
        save_db(db)
        await q.edit_message_text("✅ وظیفه اجباری حذف شد.", reply_markup=back_kb("m_task")); return

    if data == "m_broadcast":
        context.user_data["awaiting"] = "broadcast"
        await q.edit_message_text("📢 پیامی که می‌خوای برای همه ارسال بشه رو بفرست:", reply_markup=back_kb("m_back")); return

    if data == "m_dm":
        context.user_data["awaiting"] = "dm_id"
        await q.edit_message_text("✉️ آیدی عددی کاربر مقصد رو بفرست:", reply_markup=back_kb("m_back")); return

    if data == "m_texts":
        await q.edit_message_text("✏️ کدوم متن رو می‌خوای تغییر بدی؟", reply_markup=texts_menu()); return

    if data.startswith("tx_"):
        key = data[3:]
        context.user_data["awaiting"] = f"text_{key}"
        current = get_text(key)
        await q.edit_message_text(
            f"متن فعلی:\n\n{current}\n\n— متن جدید رو بفرست (می‌تونی از {{name}} برای متن start و {{channels}}/{{link}} در بقیه استفاده کنی):",
            reply_markup=back_kb("m_texts")
        ); return

    if data == "m_admins":
        await q.edit_message_text("👑 مدیریت ادمین‌ها", reply_markup=admins_menu()); return

    if data == "a_add":
        context.user_data["awaiting"] = "admin_add"
        await q.edit_message_text("➕ آیدی عددی ادمین جدید رو بفرست:", reply_markup=back_kb("m_admins")); return

    if data == "a_list":
        ids = all_admin_ids()
        text = "👑 ادمین‌های فعلی:\n\n" + "\n".join(f"• `{i}`" for i in ids)
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=back_kb("m_admins")); return

    if data == "m_stats":
        text = (
            f"📊 آمار کلی\n\n"
            f"👥 کاربران: {len(db['users'])}\n"
            f"🚫 مسدودها: {len(db.get('banned',[]))}\n"
            f"📁 فایل‌ها: {len(db['files'])}\n"
            f"📥 دانلودها: {sum(f.get('downloads',0) for f in db['files'].values())}\n"
            f"👍 لایک‌ها: {sum(len(f.get('liked_by',[])) for f in db['files'].values())}\n"
            f"👎 دیسلایک‌ها: {sum(len(f.get('disliked_by',[])) for f in db['files'].values())}"
        )
        await q.edit_message_text(text, reply_markup=back_kb("m_back")); return

# ═══════════════════════════════════════════
#   پردازش پیام‌های متنی (ورودی‌های پنل ادمین)
# ═══════════════════════════════════════════
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user)
    awaiting = context.user_data.get("awaiting")

    if not is_admin(user.id) or not awaiting:
        if is_banned(user.id):
            await update.message.reply_text(get_text("banned")); return
        await update.message.reply_text(get_text("default_reply"))
        return

    text = update.message.text.strip()
    db = load_db()

    if awaiting == "ban":
        if text.lstrip("-").isdigit():
            uid = int(text)
            if uid not in db["banned"]:
                db["banned"].append(uid)
                save_db(db)
            await update.message.reply_text(f"🚫 کاربر {uid} بن شد.", reply_markup=main_admin_menu())
        else:
            await update.message.reply_text("❌ آیدی نامعتبره. عدد بفرست.")
        context.user_data.pop("awaiting", None); return

    if awaiting == "unban":
        if text.lstrip("-").isdigit():
            uid = int(text)
            if uid in db["banned"]:
                db["banned"].remove(uid)
                save_db(db)
                await update.message.reply_text(f"✅ کاربر {uid} آنبن شد.", reply_markup=main_admin_menu())
            else:
                await update.message.reply_text("این کاربر تو لیست بن نبود.", reply_markup=main_admin_menu())
        else:
            await update.message.reply_text("❌ آیدی نامعتبره. عدد بفرست.")
        context.user_data.pop("awaiting", None); return

    if awaiting == "join_add":
        context.user_data["join_add_id"] = text
        context.user_data["awaiting"] = "join_add_title"
        await update.message.reply_text("اسم نمایشی این کانال/گروه رو بفرست:")
        return

    if awaiting == "join_add_title":
        ch_id = context.user_data.pop("join_add_id", text)
        db.setdefault("join_channels", []).append({"id": ch_id, "title": text})
        save_db(db)
        await update.message.reply_text(f"✅ اضافه شد: {text}", reply_markup=main_admin_menu())
        context.user_data.pop("awaiting", None); return

    if awaiting == "task_set":
        db["required_task"] = {"link": text, "done_by": []}
        save_db(db)
        await update.message.reply_text("✅ وظیفه اجباری تنظیم شد.", reply_markup=main_admin_menu())
        context.user_data.pop("awaiting", None); return

    if awaiting == "broadcast":
        users = list(db["users"].keys())
        sent = failed = 0
        status = await update.message.reply_text(f"⏳ ارسال به {len(users)} کاربر...")
        for uid in users:
            try:
                await context.bot.send_message(chat_id=int(uid), text=text)
                sent += 1
                await asyncio.sleep(0.05)
            except Exception:
                failed += 1
        await status.edit_text(f"✅ پیام همگانی ارسال شد!\n✔️ موفق: {sent}\n❌ ناموفق: {failed}", reply_markup=main_admin_menu())
        context.user_data.pop("awaiting", None); return

    if awaiting == "dm_id":
        if text.lstrip("-").isdigit():
            context.user_data["dm_target"] = int(text)
            context.user_data["awaiting"] = "dm_text"
            await update.message.reply_text("متن پیام رو بفرست:")
        else:
            await update.message.reply_text("❌ آیدی نامعتبره.")
        return

    if awaiting == "dm_text":
        target = context.user_data.pop("dm_target", None)
        context.user_data.pop("awaiting", None)
        if target:
            try:
                await context.bot.send_message(chat_id=target, text=text)
                await update.message.reply_text("✅ پیام ارسال شد.", reply_markup=main_admin_menu())
            except Exception as e:
                await update.message.reply_text(f"❌ خطا: {e}", reply_markup=main_admin_menu())
        return

    if awaiting and awaiting.startswith("text_"):
        key = awaiting[5:]
        db.setdefault("texts", {})[key] = text
        save_db(db)
        await update.message.reply_text("✅ متن آپدیت شد.", reply_markup=main_admin_menu())
        context.user_data.pop("awaiting", None); return

    if awaiting == "admin_add":
        if text.lstrip("-").isdigit():
            uid = int(text)
            db.setdefault("admins_extra", [])
            if uid not in db["admins_extra"]:
                db["admins_extra"].append(uid)
                save_db(db)
            await update.message.reply_text(f"✅ {uid} به لیست ادمین‌ها اضافه شد.", reply_markup=main_admin_menu())
        else:
            await update.message.reply_text("❌ آیدی نامعتبره.")
        context.user_data.pop("awaiting", None); return

# ═══════════════════════════════════════════
#   دستورات سریع: حذف فایل / تغییر کپشن
# ═══════════════════════════════════════════
async def delfile_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(get_text("no_access")); return
    if not context.args:
        await update.message.reply_text("استفاده: /delfile کد_فایل"); return
    code = context.args[0]
    db = load_db()
    if code in db["files"]:
        del db["files"][code]
        save_db(db)
        await update.message.reply_text("✅ فایل حذف شد.")
    else:
        await update.message.reply_text("❌ همچین کدی پیدا نشد.")

async def caption_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(get_text("no_access")); return
    if len(context.args) < 2:
        await update.message.reply_text("استفاده: /caption کد_فایل متن جدید"); return
    code = context.args[0]
    new_caption = " ".join(context.args[1:])
    db = load_db()
    if code in db["files"]:
        db["files"][code]["custom_caption"] = new_caption
        save_db(db)
        await update.message.reply_text("✅ کپشن آپدیت شد.")
    else:
        await update.message.reply_text("❌ همچین کدی پیدا نشد.")

# ═══════════════════════════════════════════
#   روتر کلی کالبک‌ها
# ═══════════════════════════════════════════
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.data.startswith("like_") or q.data.startswith("dislike_"):
        await handle_reaction(update, context)
    elif q.data.startswith("checkjoin_"):
        await callback_check_join(update, context)
    elif q.data.startswith("checktask_"):
        await callback_check_task(update, context)
    else:
        await admin_router(update, context)

# ═══════════════════════════════════════════
#   اجرا
# ═══════════════════════════════════════════
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("delfile", delfile_cmd))
    app.add_handler(CommandHandler("caption", caption_cmd))
    app.add_handler(MessageHandler(
        filters.PHOTO | filters.VIDEO | filters.Document.ALL | filters.AUDIO | filters.VOICE,
        handle_file
    ))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(callback_router))
    print("🤖 ربات شروع به کار کرد...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()




