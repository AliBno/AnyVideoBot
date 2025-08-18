# ==============================================================================
#                 Elite Telegram Media Downloader Bot - Version 2.0
#                         Lead Software Engineer: Ali Mahdi
# ==============================================================================

# --- 1. Importing Libraries ---
import logging
import os
import re
import asyncio
from dotenv import load_dotenv
import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, CallbackQueryHandler, JobQueue
)

# --- 2. Initial Setup ---
load_dotenv()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# In-memory storage for simple stats
download_stats = {"images": 0, "videos": 0}

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- 3. Helper Functions ---
def clean_url(url: str) -> str:
    """Cleans tracking parameters from URLs for better processing."""
    return re.sub(r'\?(fbclid|utm_source|utm_medium|utm_campaign|utm_term|utm_content|is_from_webapp|sender_device)=.*', '', url)

# --- 4. Core Bot UI and Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    keyboard = [
        [InlineKeyboardButton("📘 طريقة الاستخدام", callback_data='help'), InlineKeyboardButton("💡 عن المطور", callback_data='developer')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_html(
        f"أهلاً بك يا {user.mention_html()} في بوت التحميل المطور! 🚀\n\n"
        "أنا جاهز لتحميل الفيديوهات، الريلز، والصور من مختلف المنصات بسرعة وكفاءة.\n\n"
        "فقط أرسل لي الرابط!",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if query.data == 'help':
        await help_command(query)
    elif query.data == 'developer':
        await developer_command(query)

async def help_command(query_or_update):
    help_text = (
        "📘 **طريقة الاستخدام بسيطة جداً:**\n\n"
        "1. **انسخ الرابط** لأي فيديو، ريل، أو منشور (حتى لو به عدة صور) من منصات مثل تيك توك أو إنستغرام.\n"
        "2. **ألصق الرابط** هنا في المحادثة.\n"
        "3. **انتظر قليلاً!** سأقوم بمعالجة طلبك وإرسال جميع الوسائط إليك.\n\n"
        "💡 **نصيحة:** البوت يستخدم نظام طابور، لذا سيتم معالجة طلبك حتى لو كان هناك ضغط."
    )
    if hasattr(query_or_update, 'edit_message_text'):
        await query_or_update.edit_message_text(text=help_text, parse_mode='Markdown')
    else:
        await query_or_update.message.reply_text(text=help_text, parse_mode='Markdown')

async def developer_command(query_or_update):
    stats_text = (
        f"📊 **إحصائيات البوت:**\n"
        f"  - الصور المحملة: {download_stats['images']}\n"
        f"  - الفيديوهات المحملة: {download_stats['videos']}"
    )
    dev_text = (
        "💡 **عن المطور:**\n\n"
        "تم تصميم وهندسة هذا البوت بواسطة:\n"
        "**Ali Mahdi**\n\n"
        "تم بناء هذه النسخة المطورة مع التركيز على الأداء، السرعة، وتجربة المستخدم.\n\n"
        f"{stats_text}"
    )
    if hasattr(query_or_update, 'edit_message_text'):
        await query_or_update.edit_message_text(text=dev_text, parse_mode='Markdown')
    else:
        await query_or_update.message.reply_text(text=dev_text, parse_mode='Markdown')

# --- 5. Download Logic & Job Queue ---

async def queue_download_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Adds a download request to the job queue."""
    url = clean_url(update.message.text)
    chat_id = update.effective_chat.id
    message_id = update.message.message_id
    
    context.job_queue.run_once(
        process_download_job, 
        when=0, 
        data={'chat_id': chat_id, 'url': url, 'reply_to_message_id': message_id}
    )
    
    await update.message.reply_text("✅ تم استلام طلبك وجدولته في طابور التحميل!")

def ytdlp_downloader(url: str, temp_dir: str) -> dict:
    """Synchronous function to run yt-dlp."""
    ydl_opts = {
        'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
        'format': 'b[ext=mp4]/best[ext=mp4]/best',
        'quiet': True,
        'merge_output_format': 'mp4',
        'noplaylist': True,
        'extract_flat': True, # To get metadata of all items in a post
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)

async def process_download_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Processes a single download job from the queue."""
    job_data = context.job.data
    chat_id = job_data['chat_id']
    url = job_data['url']
    
    status_message = await context.bot.send_message(chat_id, "⏳ جارٍ تحليل الرابط...")

    temp_dir = f"temp_{chat_id}_{job_data['reply_to_message_id']}"
    os.makedirs(temp_dir, exist_ok=True)

    try:
        # Run the blocking yt-dlp command in a separate thread
        meta = await asyncio.to_thread(ytdlp_downloader, url, temp_dir)
        
        entries = meta.get('entries', [meta])
        total_items = len(entries)
        await status_message.edit_text(f"🔍 تم العثور على {total_items} عنصر. جارٍ التحميل...")

        for i, entry in enumerate(entries, 1):
            item_url = entry.get('url')
            is_video = entry.get('is_live') is False or entry.get('duration') or 'video' in entry.get('format', '')
            filename_template = os.path.join(temp_dir, f"item_{i}.%(ext)s")
            
            ydl_opts_download = {
                'outtmpl': filename_template,
                'format': 'b[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best' if is_video else 'best',
                'quiet': True,
            }

            with yt_dlp.YoutubeDL(ydl_opts_download) as ydl:
                ydl.download([item_url])
            
            downloaded_file = [f for f in os.listdir(temp_dir) if f.startswith(f"item_{i}")][0]
            file_path = os.path.join(temp_dir, downloaded_file)

            await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_DOCUMENT)
            await status_message.edit_text(f"🚀 جارٍ رفع العنصر ({i}/{total_items})...")
            
            caption = f"🔗 المصدر: {entry.get('uploader', 'N/A')}"
            
            if is_video:
                with open(file_path, 'rb') as f:
                    await context.bot.send_video(chat_id, f, caption=caption)
                download_stats['videos'] += 1
            else:
                with open(file_path, 'rb') as f:
                    await context.bot.send_photo(chat_id, f, caption=caption)
                download_stats['images'] += 1

            os.remove(file_path)

        await status_message.edit_text("✅ اكتمل تحميل جميع العناصر بنجاح!")
    except Exception as e:
        logger.error(f"Error processing {url}: {e}")
        await status_message.edit_text("❌ عذراً، حدث خطأ أثناء معالجة هذا الرابط. قد يكون المحتوى خاصاً أو غير مدعوم.")
    finally:
        if os.path.exists(temp_dir):
            for f in os.listdir(temp_dir): os.remove(os.path.join(temp_dir, f))
            os.rmdir(temp_dir)

# --- 6. Main Function to Run the Bot ---
def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        logger.critical("خطأ: لم يتم العثور على توكن البوت!")
        return
        
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & (filters.Entity("url") | filters.Entity("text_link")), queue_download_task))
    
    logger.info("🚀 البوت المطور قيد التشغيل...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
