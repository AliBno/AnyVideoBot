# ==============================================================================
#      🔥 VIP Professional Telegram Media Downloader Bot 🔥
#                 Developed by: Ali Mahdi
#        (Completely Refactored for Stability & Performance by Gemini)
# ==============================================================================

import logging
import os
import re
import shutil
import sqlite3
import tempfile
import zipfile
from typing import List, Dict, Optional, Tuple, Any
import asyncio
import httpx
from bs4 import BeautifulSoup
import io
from PIL import Image

from dotenv import load_dotenv
import yt_dlp

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    InputMediaPhoto, InputMediaVideo
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, CallbackQueryHandler
)
from telegram.constants import ParseMode

# ==============================================================================
# 0. CONFIGURATION & LOGGING
# ==============================================================================

load_dotenv()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("VIPDownloaderBot")

DB_PATH = "bot_data.sqlite3"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
IG_DOMAINS = ("instagram.com", "www.instagram.com")
TIKTOK_DOMAINS = ("tiktok.com", "www.tiktok.com")

# ==============================================================================
# 1. DATABASE UTILITIES
# ==============================================================================

def db_init():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS user_stats (user_id INTEGER PRIMARY KEY, count INTEGER NOT NULL DEFAULT 0)")
        conn.commit()

def db_inc_count(user_id: int, delta: int):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO user_stats(user_id, count) VALUES(?, ?) ON CONFLICT(user_id) DO UPDATE SET count = count + ?", (user_id, delta, delta))
        conn.commit()

# ==============================================================================
# 2. MEDIA PROCESSING SERVICES
# ==============================================================================

async def download_media_content(url: str, is_photo: bool) -> Optional[bytes]:
    """Robustly downloads content from a URL into bytes and validates if it's a photo."""
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            headers = {'User-Agent': USER_AGENT, 'Referer': url}
            response = await client.get(url, timeout=60, headers=headers)
            response.raise_for_status()
            content = response.content
        
        if is_photo:
            try:
                with Image.open(io.BytesIO(content)) as img:
                    img.verify()
            except Exception as validation_error:
                logger.error(f"Validation failed for image from {url}: {validation_error}")
                return None
        return content
    except Exception as e:
        logger.error(f"Failed to download content from {url}: {e}")
        return None

# --- Instagram Service ---
async def _fetch_insta_from_api(url: str) -> Optional[Tuple[List[Dict], Dict]]:
    """Primary method: Tries to fetch Instagram media using a third-party API."""
    try:
        api_url = "https://igdownloader.app/api/ajaxSearch"
        payload = {'q': url, 'type': 'post'}
        headers = {'User-Agent': USER_AGENT, 'Content-Type': 'application/x-www-form-urlencoded', 'Origin': 'https://igdownloader.app', 'Referer': 'https://igdownloader.app/'}
        async with httpx.AsyncClient() as client:
            r = await client.post(api_url, data=payload, headers=headers, timeout=30)
            r.raise_for_status(); data = r.json()
        if data.get("status") != "ok" or "data" not in data: return None
        
        soup = BeautifulSoup(data["data"], "html.parser")
        items: List[Dict] = []
        title_element = soup.find("p", class_="title")
        meta = {"title": title_element.text if title_element else "Instagram Post", "owner": "Instagram"}
        
        for widget in soup.find_all("div", class_="download-items"):
            link = widget.find("a", class_="abutton")
            thumb = widget.find("img")
            if link and thumb and link.get("href"):
                is_video = "video" in thumb.get("alt", "").lower()
                items.append({"type": "video" if is_video else "photo", "url": link["href"]})
        return items, meta
    except Exception as e:
        logger.error(f"Instagram API failed: {e}"); return None

def _fetch_insta_from_ytdlp(url: str) -> Optional[Tuple[List[Dict], Dict]]:
    """Fallback method: Tries to fetch Instagram media using yt-dlp."""
    try:
        opts = {"quiet": True, "noprogress": True, "ignoreerrors": True}
        cookie_file = "cookies.txt"
        if os.path.exists(cookie_file):
            logger.info("Using cookies.txt for yt-dlp fallback.")
            opts["cookiefile"] = cookie_file
        
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info: return None
            
            items: List[Dict] = []
            entries = info.get("entries", [info])
            for entry in entries:
                if not entry: continue
                media_url = entry.get("url")
                if media_url:
                    items.append({"type": "video" if entry.get("vcodec") != "none" else "photo", "url": media_url})
            
            meta = {"title": info.get("title", "Instagram Post"), "owner": (info.get("uploader") or "Instagram").lstrip("@")}
            return items, meta
    except Exception as e:
        logger.error(f"Instagram yt-dlp fallback failed: {e}"); return None

# --- Generic Service ---
def fetch_generic_media(url: str, quality: str) -> Optional[str]:
    """Downloads any generic video (YouTube, etc.) to a local file."""
    try:
        tmpdir = tempfile.mkdtemp(prefix="generic_dl_")
        outtmpl = os.path.join(tmpdir, f"media_%(id)s.%(ext)s")
        
        opts = {
            "outtmpl": outtmpl,
            "format": "b[ext=mp4]/bestvideo*+bestaudio/best" if quality == "best" else "worst",
            "merge_output_format": "mp4",
            "quiet": True, "noprogress": True
        }
        
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return ydl.prepare_filename(info)
    except Exception as e:
        logger.error(f"Generic yt-dlp download failed for {url}: {e}")
        return None

# ==============================================================================
# 3. TELEGRAM BOT HANDLERS
# ==============================================================================

# --- UI and Commands ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (f"👋 أهلاً {user.mention_html()}!\n\n"
            "أنا بوت تحميل احترافي. أرسل لي أي رابط من انستغرام، تيك توك، يوتيوب، وغيرها وسأقوم بالباقي.")
    await update.message.reply_html(text)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = ("📌 **طريقة الاستخدام:**\n"
            "1. انسخ رابط أي فيديو أو صورة.\n"
            "2. الصق الرابط هنا وأرسله.\n"
            "3. انتظر قليلاً بينما أقوم بالتنزيل والرفع لك.\n\n"
            "✨ البوت يدعم الألبومات من انستغرام ويرسلها كمجموعة وسائط.")
    await update.message.reply_markdown(text)

# --- Main Link Handler (The Router) ---
async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    url_match = re.search(r"(https?://\S+)", update.message.text)
    if not url_match:
        await update.message.reply_text("لم يتم العثور على رابط صالح في رسالتك.")
        return

    url = url_match.group(1)
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    processing_msg = await update.message.reply_text("⏳ جاري تحليل الرابط...")
    
    handler_success = False
    
    try:
        if any(d in url for d in IG_DOMAINS):
            handler_success = await handle_instagram_link(url, update, processing_msg)
        elif any(d in url for d in TIKTOK_DOMAINS):
            handler_success = await handle_generic_link(url, update, processing_msg, platform="TikTok")
        else:
            handler_success = await handle_generic_link(url, update, processing_msg, platform="Generic")

        if handler_success:
            db_inc_count(user_id, 1) # Increment count per successful link handled

    except Exception as e:
        logger.error(f"An unexpected error occurred in handle_link for {url}: {e}", exc_info=True)
        await processing_msg.edit_text("❌ حدث خطأ فادح وغير متوقع أثناء معالجة طلبك.")

# --- Specific Link Handling Logic ---

async def handle_instagram_link(url: str, update: Update, processing_msg) -> bool:
    await processing_msg.edit_text("⏳ [انستغرام] محاولة الطريقة السريعة...")
    result = await _fetch_insta_from_api(url)
    
    if not result:
        await processing_msg.edit_text("⏳ [انستغرام] الطريقة السريعة فشلت. المحاولة بالطريقة البديلة...")
        result = _fetch_insta_from_ytdlp(url)

    if not result or not result[0]:
        await processing_msg.edit_text("❌ [انستغرام] فشلت كل المحاولات لاستخراج المحتوى. قد يكون المنشور خاصاً.")
        return False
        
    items, meta = result
    if len(items) > 10: items = items[:10] # Enforce 10 items limit for albums

    await processing_msg.edit_text(f"✅ تم العثور على {len(items)} عنصر. جاري التنزيل والرفع...")
    
    media_group: List[Any] = []
    caption = f"👤 **From:** @{meta.get('owner', 'Instagram')}\n📝 {meta.get('title', '')[:500]}"
    is_first = True

    for i, item in enumerate(items):
        await processing_msg.edit_text(f"📥 جاري تنزيل العنصر {i+1}/{len(items)}...")
        content = await download_media_content(item['url'], item['type'] == 'photo')
        
        if not content:
            logger.warning(f"Skipping item {i+1} due to download/validation failure.")
            continue
        
        current_caption = caption if is_first else None
        if item['type'] == 'photo':
            media_group.append(InputMediaPhoto(media=content, caption=current_caption, parse_mode=ParseMode.MARKDOWN))
        else:
            media_group.append(InputMediaVideo(media=content, caption=current_caption, parse_mode=ParseMode.MARKDOWN))
        is_first = False

    if not media_group:
        await processing_msg.edit_text("❌ فشل تنزيل كل العناصر. قد تكون الروابط محمية.")
        return False

    await processing_msg.edit_text(f"📤 جاري رفع {len(media_group)} عنصر...")
    await update.message.reply_media_group(media=media_group)
    await processing_msg.delete()
    return True


async def handle_generic_link(url: str, update: Update, processing_msg, platform: str) -> bool:
    await processing_msg.edit_text(f"⏳ [{platform}] جاري التنزيل...")
    
    # For generic links, yt-dlp downloads to a file, which is more reliable for merged formats.
    local_path = fetch_generic_media(url, quality="best")

    if not local_path or not os.path.exists(local_path):
        await processing_msg.edit_text(f"❌ [{platform}] فشل التنزيل. تأكد من الرابط.")
        return False

    await processing_msg.edit_text(f"📤 [{platform}] جاري الرفع...")
    caption_map = {"TikTok": "🎬 via @YourBotName", "Generic": "🎬 Downloaded by @YourBotName"}
    
    try:
        with open(local_path, "rb") as media_file:
            if local_path.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                await update.message.reply_photo(photo=media_file, caption=caption_map.get(platform, ""))
            else:
                await update.message.reply_video(video=media_file, caption=caption_map.get(platform, ""))
        await processing_msg.delete()
        return True
    finally:
        # Clean up the temporary directory and file
        shutil.rmtree(os.path.dirname(local_path), ignore_errors=True)

# ==============================================================================
# 4. MAIN BOT SETUP
# ==============================================================================

async def post_init_tasks(application: Application):
    """Tasks to run on bot startup, like clearing webhooks."""
    print("ℹ️ Checking for existing webhook...")
    if (await application.bot.get_webhook_info()).url:
        print("Webhook found, deleting...")
        await application.bot.delete_webhook()
        print("✅ Webhook deleted successfully.")
    else:
        print("👍 No webhook found, starting polling.")

def main():
    """Starts the bot."""
    if not TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN not found in environment variables. Please check your .env file.")
        return

    print("Initializing database...")
    db_init()
    
    print("Building application...")
    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init_tasks)
        .build()
    )

    # Register handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    
    print("🚀 Bot is now running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
