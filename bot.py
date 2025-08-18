# ==============================================================================
#                 VIP Professional Telegram Media Downloader Bot
#                      Re-engineered by: Mohannad the Programmer
#                             Original Author: Ali Mahdi
# ==============================================================================

# --- 1. استيراد المكتبات الأساسية ---
import logging
import os
import re
import asyncio
from datetime import timedelta
from dotenv import load_dotenv
import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaVideo, InputMediaPhoto
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.constants import ParseMode
from telegram.error import TelegramError

# --- 2. الإعدادات الأولية والتهيئة ---

# تحميل متغيرات البيئة من ملف .env (أكثر أمانًا)
load_dotenv()

# استدعاء المتغيرات من البيئة
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

# إعداد نظام تسجيل الأخطاء والنشاطات لمراقبة أداء البوت
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- 3. الثوابت ورسائل البوت ---
# استخدام قاموس لتنظيم الرسائل وتسهيل تعديلها
MESSAGES = {
    "welcome": (
        "أهلاً بك يا {user_mention} في بوت التحميل الاحترافي! 🚀\n\n"
        "أرسل لي أي رابط فيديو أو صورة وسأقوم بتحميلها لك بجودة عالية.\n\n"
        "اختر أحد الخيارات أدناه للمساعدة أو لمعرفة المزيد."
    ),
    "help": (
        "**ℹ️ طريقة الاستخدام:**\n\n"
        "1. انسخ رابط الفيديو أو الصورة (من أي منصة).\n"
        "2. الصق الرابط هنا في المحادثة وأرسله.\n"
        "3. إذا كان الرابط من يوتيوب، ستظهر لك خيارات الجودة.\n"
        "4. انتظر قليلاً واستلم ملفك!\n\n"
        "**المنصات المدعومة:**\n"
        "🎵 **تيك توك**: فيديو وصور (بدون علامة مائية).\n"
        "📸 **إنستغرام**: صور، فيديوهات، و Reels.\n"
        "🎥 **يوتيوب**: فيديو (بجودات متعددة) وصوت فقط.\n"
        "🌐 والعديد من المواقع الأخرى المدعومة بواسطة `yt-dlp`."
    ),
    "developer": (
        "**👨‍💻 مطور البوت:**\n\n"
        "تمت إعادة هندسة وتطوير هذا البوت بواسطة **مهند المبرمج** بناءً على الكود الأساسي للمطور **Ali Mahdi**.\n\n"
        "شكرًا لاستخدامك البوت! ✨"
    ),
    "processing": "⏳ | جاري معالجة الرابط، يرجى الانتظار...",
    "download_success": "✅ | تم التحميل بنجاح! جاري إرسال الملف...",
    "uploading": "📤 | جاري الرفع، قد يستغرق هذا بعض الوقت...",
    "error_general": "❌ | عذراً، لم أتمكن من تحميل الملف. تأكد من أن الرابط صحيح وعام.",
    "error_too_large": "📦 | عذراً، حجم الملف كبير جداً ولا يمكن رفعه على تليجرام.",
    "stats": (
        "📊 **إحصائيات استخدام البوت**\n\n"
        "▫️ **التحميلات الناجحة:** `{successful_downloads}`\n"
        "▫️ **التحميلات الفاشلة:** `{failed_downloads}`"
    ),
    "admin_only": "🔐 | عذراً، هذا الأمر مخصص للمطور فقط."
}

# --- 4. معالجات الأوامر الأساسية (start, help, stats) ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """إرسال رسالة ترحيبية مع لوحة أزرار تفاعلية عند إرسال /start."""
    user = update.effective_user
    keyboard = [
        [InlineKeyboardButton("ℹ️ طريقة الاستخدام", callback_data='core_help')],
        [InlineKeyboardButton("👨‍💻 عن المطور", callback_data='core_developer')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_html(
        MESSAGES["welcome"].format(user_mention=user.mention_html()),
        reply_markup=reply_markup
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """عرض إحصائيات البوت (للمطور فقط)."""
    user_id = str(update.effective_user.id)
    if user_id != ADMIN_CHAT_ID:
        await update.message.reply_text(MESSAGES["admin_only"])
        return

    stats_text = MESSAGES["stats"].format(
        successful_downloads=context.bot_data.get('successful_downloads', 0),
        failed_downloads=context.bot_data.get('failed_downloads', 0)
    )
    await update.message.reply_text(stats_text, parse_mode=ParseMode.MARKDOWN)

# --- 5. معالج الأزرار الموحد (Callback Query Router) ---

async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يوجه استجابات الأزرار إلى الدوال المناسبة."""
    query = update.callback_query
    await query.answer()
    
    # تفكيك بيانات الزر: action:data
    parts = query.data.split(':', 1)
    action = parts[0]
    data = parts[1] if len(parts) > 1 else None

    if action == 'core_help':
        await query.edit_message_text(MESSAGES["help"], parse_mode=ParseMode.MARKDOWN)
    elif action == 'core_developer':
        await query.edit_message_text(MESSAGES["developer"], parse_mode=ParseMode.MARKDOWN)
    elif action == 'quality_select':
        url, format_id = data.split('|', 1)
        await process_download(url, format_id, query.message, context)
    elif action == 'cancel_download':
        await query.edit_message_text("✅ | تم إلغاء العملية.")


# --- 6. منطق تحميل الوسائط (Media Downloading Logic) ---

# متغير لتجنب إرسال تحديثات متتالية بسرعة (Anti-Spam for progress updates)
last_update_time = {}

async def progress_hook(d, message: Update.message, context: ContextTypes.DEFAULT_TYPE):
    """دالة تُستدعى من yt-dlp لتحديث حالة التحميل."""
    chat_id = message.chat_id
    message_id = message.message_id
    
    if d['status'] == 'downloading':
        # الحصول على الوقت الحالي
        now = asyncio.get_event_loop().time()
        
        # التأكد من مرور ثانية على الأقل قبل التحديث لتجنب أخطاء Telegram API
        if (now - last_update_time.get(message_id, 0)) > 2.0:
            percentage = d.get('_percent_str', 'N/A')
            speed = d.get('_speed_str', 'N/A')
            eta = d.get('_eta_str', 'N/A')
            
            # إزالة الألوان ANSI
            percentage = re.sub(r'\x1b\[[0-9;]*m', '', percentage)

            try:
                progress_text = f"📥 | جاري التحميل... `{percentage}`\n"
                progress_text += f"⚙️ | السرعة: `{speed}` | الوقت المتبقي: `{eta}`"
                
                await context.bot.edit_message_text(
                    text=progress_text,
                    chat_id=chat_id,
                    message_id=message_id,
                    parse_mode=ParseMode.MARKDOWN
                )
                last_update_time[message_id] = now
            except TelegramError as e:
                # تجاهل خطأ "Message is not modified"
                if "Message is not modified" not in str(e):
                    logger.warning(f"Failed to edit message with progress: {e}")


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """المعالج الرئيسي للروابط، يقوم بتحليل الرابط وتوجيهه."""
    url = update.message.text.strip()
    processing_msg = await update.message.reply_text(MESSAGES["processing"])

    try:
        ydl_opts = {'quiet': True, 'extract_flat': True, 'force_generic_extractor': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        
        # إذا كان الرابط من يوتيوب أو منصة تدعم صيغ متعددة
        if 'formats' in info and "youtube.com" in url:
            await show_quality_options(url, info, processing_msg, context)
        # إذا كان الرابط من انستغرام
        elif info.get('extractor_key') == 'Instagram':
            await process_instagram(url, processing_msg, context)
        # للروابط الأخرى (مثل تيك توك)، قم بالتحميل مباشرة بأفضل جودة
        else:
            await process_download(url, 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best', processing_msg, context)

    except Exception as e:
        logger.error(f"Error handling link {url}: {e}")
        await processing_msg.edit_text(MESSAGES["error_general"])
        context.bot_data['failed_downloads'] = context.bot_data.get('failed_downloads', 0) + 1


async def show_quality_options(url: str, info: dict, message, context: ContextTypes.DEFAULT_TYPE):
    """عرض أزرار لاختيار جودة التحميل."""
    formats = info.get('formats', [])
    buttons = []
    # فلترة واختيار بعض الجودات المميزة فقط
    supported_resolutions = {360, 480, 720, 1080}
    found_resolutions = set()

    for f in reversed(formats):
        if f.get('vcodec') != 'none' and f.get('acodec') != 'none' and f.get('height') in supported_resolutions:
            res = f['height']
            if res not in found_resolutions:
                # format_id: bestvideo[height<=720]+bestaudio/best[height<=720]
                format_id = f"bestvideo[height<={res}][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4][height<={res}]"
                buttons.append([InlineKeyboardButton(f"🎥 {res}p", callback_data=f"quality_select:{url}|{format_id}")])
                found_resolutions.add(res)
    
    # إضافة خيار تحميل الصوت فقط
    buttons.append([InlineKeyboardButton("🎵 صوت فقط (M4A)", callback_data=f"quality_select:{url}|bestaudio[ext=m4a]/bestaudio")])
    buttons.append([InlineKeyboardButton("❌ إلغاء", callback_data="cancel_download")])

    if not buttons:
        await message.edit_text("لم أجد صيغ تحميل مدعومة لهذا الرابط.")
        return

    reply_markup = InlineKeyboardMarkup(buttons)
    await message.edit_text("🔝 | يرجى اختيار الجودة المطلوبة:", reply_markup=reply_markup)


async def process_instagram(url: str, message, context: ContextTypes.DEFAULT_TYPE):
    """معالجة خاصة لروابط انستغرام (صور، فيديو، كاروسيل)."""
    await message.edit_text("📸 | تم اكتشاف رابط انستغرام، جاري استخراج المحتوى...")
    
    ydl_opts = {
        'quiet': True,
        'outtmpl': f'downloads/{message.message_id}/%(title)s.%(ext)s'
    }
    
    media_paths = []
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # إذا كان المنشور يحتوي على عدة عناصر (كاروسيل)
            if 'entries' in info:
                for entry in info['entries']:
                    media_paths.append(ydl.prepare_filename(entry))
            else: # منشور واحد
                media_paths.append(ydl.prepare_filename(info))
        
        await send_media(media_paths, message, context)
        context.bot_data['successful_downloads'] = context.bot_data.get('successful_downloads', 0) + 1

    except Exception as e:
        logger.error(f"Instagram download failed for {url}: {e}")
        await message.edit_text(MESSAGES["error_general"])
        context.bot_data['failed_downloads'] = context.bot_data.get('failed_downloads', 0) + 1
    finally:
        # تنظيف الملفات
        if os.path.exists(f'downloads/{message.message_id}'):
            for f in media_paths:
                if os.path.exists(f):
                    os.remove(f)
            os.rmdir(f'downloads/{message.message_id}')


async def process_download(url: str, format_id: str, message, context: ContextTypes.DEFAULT_TYPE):
    """الدالة الرئيسية التي تقوم بعملية التحميل الفعلية."""
    file_path = None
    try:
        output_template = f"downloads/{message.message_id}.%(ext)s"
        
        # تعيين دالة تحديث الحالة
        progress_hook_with_args = lambda d: asyncio.create_task(progress_hook(d, message, context))
        
        ydl_opts = {
            'format': format_id,
            'outtmpl': output_template,
            'progress_hooks': [progress_hook_with_args],
            'merge_output_format': 'mp4',
            # تجنب تحميل قوائم التشغيل كاملة
            'noplaylist': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)

        if file_path and os.path.exists(file_path):
            await send_media([file_path], message, context)
            context.bot_data['successful_downloads'] = context.bot_data.get('successful_downloads', 0) + 1
        else:
            raise Exception("File not found after download.")

    except Exception as e:
        logger.error(f"Download failed for {url} with format {format_id}: {e}")
        error_message = MESSAGES["error_general"]
        if "File is larger than 50MB" in str(e):
             error_message = MESSAGES["error_too_large"]
        await message.edit_text(error_message)
        context.bot_data['failed_downloads'] = context.bot_data.get('failed_downloads', 0) + 1
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

async def send_media(file_paths: list, message, context: ContextTypes.DEFAULT_TYPE):
    """إرسال الملفات المحملة (فيديو، صور، أو ألبوم)."""
    await message.edit_text(MESSAGES["uploading"])
    chat_id = message.chat_id
    caption_text = "📥 | تم التحميل بواسطة بوتك المفضل"

    try:
        if len(file_paths) == 1:
            path = file_paths[0]
            if path.endswith(('.mp4', '.mkv', '.webm')):
                with open(path, 'rb') as f:
                    await context.bot.send_video(chat_id, video=f, caption=caption_text, read_timeout=180, write_timeout=180)
            elif path.endswith(('.jpg', '.jpeg', '.png', '.webp')):
                 with open(path, 'rb') as f:
                    await context.bot.send_photo(chat_id, photo=f, caption=caption_text)
            else: # إرسال كملف صوتي أو وثيقة
                with open(path, 'rb') as f:
                    await context.bot.send_document(chat_id, document=f, caption=caption_text)
        elif len(file_paths) > 1:
            media_group = []
            for path in file_paths:
                if path.endswith(('.mp4', '.mkv', '.webm')):
                    media_group.append(InputMediaVideo(open(path, 'rb')))
                elif path.endswith(('.jpg', '.jpeg', '.png', '.webp')):
                    media_group.append(InputMediaPhoto(open(path, 'rb')))
            # إضافة التسمية التوضيحية إلى العنصر الأول فقط
            if media_group:
                media_group[0].caption = caption_text
                await context.bot.send_media_group(chat_id, media=media_group, read_timeout=180, write_timeout=180)

        await message.delete() # حذف رسالة "جاري الرفع" بعد النجاح

    except TelegramError as e:
        if "can't be sent as a video" in str(e) or "wrong file identifier" in str(e):
             await context.bot.send_message(chat_id, " يبدو أن الملف غير صالح، جارٍ إرساله كوثيقة.")
             with open(file_paths[0], 'rb') as doc:
                await context.bot.send_document(chat_id, document=doc, caption=caption_text)
             await message.delete()
        else:
            logger.error(f"Failed to send media: {e}")
            await message.edit_text(MESSAGES["error_too_large"])


# --- 7. الدالة الرئيسية لتشغيل البوت ---

def main() -> None:
    """الدالة الرئيسية لبدء تشغيل البوت وإعداد المعالجات."""
    if not TELEGRAM_BOT_TOKEN or not ADMIN_CHAT_ID:
        logger.critical("خطأ فادح: توكن البوت أو هوية المطور غير موجودة في متغيرات البيئة.")
        logger.critical("يرجى التأكد من وجود ملف .env يحتوي على TELEGRAM_BOT_TOKEN و ADMIN_CHAT_ID")
        return

    # إنشاء مجلد التحميلات إذا لم يكن موجودًا
    if not os.path.exists('downloads'):
        os.makedirs('downloads')

    # إعداد التطبيق
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # تهيئة عدادات الإحصائيات
    application.bot_data['successful_downloads'] = 0
    application.bot_data['failed_downloads'] = 0

    # تسجيل المعالجات
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CallbackQueryHandler(button_router))
    # فلتر للروابط فقط
    url_filter = filters.TEXT & ~filters.COMMAND & (filters.Entity("url") | filters.Entity("text_link"))
    application.add_handler(MessageHandler(url_filter, handle_link))
    
    logger.info("🚀 البوت قيد التشغيل وجاهز لاستقبال الروابط...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
