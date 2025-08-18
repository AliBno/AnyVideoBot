# ==============================================================================
#                 Final Professional Telegram Video Downloader Bot
#                              Developed by: Ali Mahdi
# ==============================================================================

# --- 1. Importing Libraries ---
import logging
import os
from dotenv import load_dotenv
import requests
import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# --- 2. Initial Setup ---

# Load environment variables from the .env file
# This is the secure way to handle your bot token
load_dotenv()

# Get the bot token from environment variables
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# Set up logging to monitor the bot's activity and catch errors
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# --- 3. Core Bot Commands and UI ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message with an interactive keyboard when /start is issued."""
    user = update.effective_user
    
    keyboard = [
        [InlineKeyboardButton("ℹ️ طريقة الاستخدام", callback_data='help')],
        [InlineKeyboardButton("👨‍💻 عن المطور", callback_data='developer')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    welcome_message = (
        f"أهلاً بك يا {user.mention_html()} في بوت تحميل الفيديوهات! 🤖\n\n"
        "أرسل لي أي رابط فيديو وسأقوم بتحميله لك فوراً.\n\n"
        "اختر أحد الخيارات أدناه للمساعدة."
    )
    await update.message.reply_html(welcome_message, reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles button presses from the inline keyboard."""
    query = update.callback_query
    await query.answer()

    if query.data == 'help':
        await help_command(query)
    elif query.data == 'developer':
        await developer_command(query)

async def help_command(query_or_update) -> None:
    """Displays the help message."""
    help_text = (
        "**ℹ️ طريقة الاستخدام:**\n\n"
        "1. انسخ رابط الفيديو الذي تريد تحميله.\n"
        "2. الصق الرابط هنا في المحادثة وأرسله.\n"
        "3. انتظر قليلاً بينما أقوم بتحميل الفيديو.\n\n"
        "**المنصات المدعومة:**\n"
        "🎵 تيك توك (بدون علامة مائية)\n"
        "📸 إنستغرام (Reels, Videos)\n"
        "🎥 يوتيوب (والعديد من المنصات الأخرى...)"
    )
    if hasattr(query_or_update, 'edit_message_text'):
        await query_or_update.edit_message_text(text=help_text, parse_mode='Markdown')
    else:
        await query_or_update.message.reply_text(text=help_text, parse_mode='Markdown')

async def developer_command(query_or_update) -> None:
    """Displays developer information."""
    dev_text = (
        "**👨‍💻 مطور البوت:**\n\n"
        "تم تطوير هذا البوت بواسطة:\n"
        "**Ali Mahdi**\n\n"
        "شكراً لاستخدامك البوت!"
    )
    if hasattr(query_or_update, 'edit_message_text'):
        await query_or_update.edit_message_text(text=dev_text, parse_mode='Markdown')
    else:
        await query_or_update.message.reply_text(text=dev_text, parse_mode='Markdown')


# --- 4. Video Downloading Logic ---

async def download_tiktok_no_watermark(url: str, message_id: int) -> str | None:
    """Attempts to download a TikTok video without a watermark."""
    logger.info(f"Attempting watermark-free download for TikTok: {url}")
    try:
        api_url = f"https://www.tikwm.com/api/?url={url}"
        response = requests.get(api_url, headers={'User-Agent': 'Mozilla/5.0'})
        response.raise_for_status()
        data = response.json().get("data", {})
        download_link = data.get("play")
        if not download_link: return None
        
        video_response = requests.get(download_link, stream=True)
        video_response.raise_for_status()
        file_path = f"tiktok_{message_id}.mp4"
        with open(file_path, 'wb') as f:
            for chunk in video_response.iter_content(chunk_size=8192): f.write(chunk)
        return file_path
    except Exception as e:
        logger.error(f"TikTok API download failed: {e}")
        return None

async def download_with_yt_dlp(url: str, message_id: int) -> str | None:
    """Generic video downloader using yt-dlp, serves as a fallback."""
    logger.info(f"Using yt-dlp as fallback for: {url}")
    try:
        output_filename = f"video_{message_id}.%(ext)s"
        ydl_opts = {'format': 'b[ext=mp4]/best[ext=mp4]/best', 'outtmpl': output_filename, 'quiet': True, 'merge_output_format': 'mp4'}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return ydl.prepare_filename(info)
    except Exception as e:
        logger.error(f"yt-dlp download failed: {e}")
        return None

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The main handler for processing video links."""
    if not update.message or not update.message.text: return
    
    url = update.message.text
    chat_id = update.effective_chat.id
    message_id = update.message.message_id
    
    processing_message = await context.bot.send_message(chat_id=chat_id, text="⏳ | جاري معالجة الرابط...")
    
    file_path = None
    if "tiktok.com" in url:
        file_path = await download_tiktok_no_watermark(url, message_id)
    if not file_path:
        file_path = await download_with_yt_dlp(url, message_id)
        
    if file_path and os.path.exists(file_path):
        await context.bot.edit_message_text(text="✅ | تم التحميل بنجاح! جاري إرسال الفيديو...", chat_id=chat_id, message_id=processing_message.message_id)
        try:
            with open(file_path, 'rb') as video_file:
                await context.bot.send_video(chat_id=chat_id, video=video_file, caption="Developed by Ali Mahdi", read_timeout=120, write_timeout=120)
        except Exception as e:
            logger.error(f"Failed to send video: {e}")
            await context.bot.send_message(chat_id=chat_id, text="حدث خطأ أثناء إرسال الفيديو. قد يكون حجمه كبيراً جداً.")
        finally:
            os.remove(file_path) # Clean up the downloaded file
    else:
         await context.bot.edit_message_text(text="❌ | عذراً، لم أتمكن من تحميل الفيديو. تأكد من أن الرابط صحيح وعام.", chat_id=chat_id, message_id=processing_message.message_id)

# --- 5. Main Function to Run the Bot ---

def main() -> None:
    """Starts the bot and sets up handlers."""
    if not TELEGRAM_BOT_TOKEN:
        print("خطأ فادح: لم يتم العثور على توكن البوت في متغيرات البيئة.")
        print("يرجى التأكد من وجود ملف .env يحتوي على TELEGRAM_BOT_TOKEN")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & (filters.Entity("url") | filters.Entity("text_link")), handle_link))
    
    print("🚀 البوت قيد التشغيل...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
