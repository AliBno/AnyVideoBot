# ==============================================================================
#            🔥 VIP Professional Telegram Media Downloader Bot 🔥
#                      Developed by: Ali Mahdi
# ==============================================================================

import logging
import os
from dotenv import load_dotenv
import requests
import yt_dlp
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, CallbackQueryHandler
)

# --- إعداد البيئة ---
load_dotenv()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# --- اللوجات ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- قاعدة بيانات مصغرة للإحصائيات ---
user_stats = {}  # {user_id: count}


# --- أوامر البداية ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    keyboard = [
        [InlineKeyboardButton("ℹ️ طريقة الاستخدام", callback_data="help")],
        [InlineKeyboardButton("📊 إحصائياتي", callback_data="stats")],
        [InlineKeyboardButton("👨‍💻 عن المطور", callback_data="developer")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    welcome = (
        f"👋 أهلاً {user.mention_html()}!\n\n"
        "📥 أرسل أي رابط فيديو أو صورة (TikTok/Instagram/YouTube...) "
        "وسأقوم بتحميله لك فوراً بدون علامة مائية.\n\n"
        "✨ البوت سريع ويدعم جودة عالية."
    )
    await update.message.reply_html(welcome, reply_markup=reply_markup)


# --- معالج الأزرار ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "help":
        text = (
            "📌 **طريقة الاستخدام:**\n\n"
            "1️⃣ انسخ رابط الفيديو/الصورة.\n"
            "2️⃣ الصقه هنا في المحادثة.\n"
            "3️⃣ انتظر قليلاً وسأرسله لك.\n\n"
            "**المنصات المدعومة:**\n"
            "🎵 TikTok (بدون علامة مائية)\n"
            "📸 Instagram (صور + Reels)\n"
            "🎥 YouTube والمزيد..."
        )
        await query.edit_message_text(text, parse_mode="Markdown")

    elif query.data == "stats":
        user_id = query.from_user.id
        count = user_stats.get(user_id, 0)
        text = f"📊 لقد قمت بتحميل **{count} ملف** باستخدام هذا البوت."
        await query.edit_message_text(text, parse_mode="Markdown")

    elif query.data == "developer":
        text = (
            "👨‍💻 **المطور:** Ali Mahdi\n\n"
            "🚀 بوت VIP احترافي لتحميل الفيديوهات والصور."
        )
        await query.edit_message_text(text, parse_mode="Markdown")


# --- التحميل من TikTok بدون علامة مائية ---
async def download_tiktok(url: str, message_id: int) -> str | None:
    try:
        api_url = f"https://www.tikwm.com/api/?url={url}"
        response = requests.get(api_url, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        data = response.json().get("data", {})
        link = data.get("play")
        if not link:
            return None

        file_path = f"tiktok_{message_id}.mp4"
        video = requests.get(link, stream=True)
        with open(file_path, "wb") as f:
            for chunk in video.iter_content(1024 * 1024):
                f.write(chunk)
        return file_path
    except Exception as e:
        logger.error(f"TikTok download failed: {e}")
        return None


# --- التحميل العام بالـ yt-dlp ---
async def download_generic(url: str, message_id: int, quality: str = "best") -> str | None:
    try:
        output = f"media_{message_id}.%(ext)s"
        ydl_opts = {
            "format": "b[ext=mp4]/best[ext=mp4]/best" if quality == "best" else "worst",
            "outtmpl": output,
            "quiet": True,
            "merge_output_format": "mp4",
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return ydl.prepare_filename(info)
    except Exception as e:
        logger.error(f"yt-dlp failed: {e}")
        return None


# --- معالجة الروابط ---
async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    url = update.message.text
    chat_id = update.effective_chat.id
    msg_id = update.message.message_id

    processing = await update.message.reply_text("⏳ جاري تحليل الرابط...")

    file_path = None
    if "tiktok.com" in url:
        file_path = await download_tiktok(url, msg_id)
    if not file_path:
        file_path = await download_generic(url, msg_id)

    if file_path and os.path.exists(file_path):
        await processing.edit_text("✅ تم التحميل! جاري الإرسال...")

        try:
            if file_path.endswith((".jpg", ".png", ".jpeg", ".webp")):
                with open(file_path, "rb") as img:
                    await context.bot.send_photo(chat_id=chat_id, photo=img, caption="📸 صورة جاهزة ✅")
            else:
                with open(file_path, "rb") as vid:
                    await context.bot.send_video(chat_id=chat_id, video=vid, caption="🎬 تم التحميل بنجاح ✅")
        except Exception as e:
            logger.error(f"Send failed: {e}")
            await context.bot.send_message(chat_id, "❌ حدث خطأ أثناء الإرسال (قد يكون الملف كبير).")
        finally:
            os.remove(file_path)

        # تحديث إحصائيات المستخدم
        user_id = update.effective_user.id
        user_stats[user_id] = user_stats.get(user_id, 0) + 1

    else:
        await processing.edit_text("❌ فشل التحميل. تأكد من الرابط.")


# --- تشغيل البوت ---
def main():
    if not TELEGRAM_BOT_TOKEN:
        print("❌ لم يتم العثور على التوكن.")
        return

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))

    print("🚀 البوت يعمل الآن...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
