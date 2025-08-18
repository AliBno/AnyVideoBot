# ==============================================================================
#      🔥 VIP Professional Telegram Media Downloader Bot 🔥
#                 Developed by: Ali Mahdi
#   (Final Intelligent Validation Version by Gemini - The Most Robust Yet)
# ==============================================================================

import logging
import os
import re
import shutil
import sqlite3
import tempfile
import zipfile
from typing import List, Dict, Optional, Tuple
import asyncio
import httpx
from bs4 import BeautifulSoup
import io
from PIL import Image  # <-- Required for the new Image Validation

from dotenv import load_dotenv
import requests
import yt_dlp

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    InputMediaPhoto, InputMediaVideo
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, CallbackQueryHandler
)

# ======================= 0) Environment & Logging =============================

load_dotenv()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("VIPDownloader")

# ============================ 1) Persistence (SQLite) =========================
# ... (This section is complete and correct, no changes needed)
DB_PATH = os.path.join(os.getcwd(), "bot_data.sqlite3")
def db_init():
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS user_stats (user_id INTEGER PRIMARY KEY, count INTEGER NOT NULL DEFAULT 0)""")
    conn.commit(); conn.close()
def db_get_count(user_id: int) -> int:
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute("SELECT count FROM user_stats WHERE user_id=?", (user_id,)); row = cur.fetchone()
    conn.close(); return row[0] if row else 0
def db_inc_count(user_id: int, delta: int):
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute("INSERT INTO user_stats(user_id, count) VALUES(?, ?) ON CONFLICT(user_id) DO UPDATE SET count = count + ?", (user_id, delta, delta))
    conn.commit(); conn.close()

# ============================ 2) In-Memory Prefs ==============================
# ... (This section is complete and correct, no changes needed)
user_quality: Dict[int, str] = {}
user_album_limit: Dict[int, bool] = {}
sessions: Dict[str, Dict] = {}
def make_session_id(chat_id: int, message_id: int) -> str:
    return f"{chat_id}:{message_id}"

# =============================== 3) UI Helpers ================================
# ... (This section is complete and correct, no changes needed)
def main_menu_kb(user_id: int) -> InlineKeyboardMarkup:
    q = user_quality.get(user_id, "best"); limit10 = user_album_limit.get(user_id, False)
    kb = [[InlineKeyboardButton("ℹ️ طريقة الاستخدام", callback_data="help")], [InlineKeyboardButton("📊 إحصائياتي", callback_data="stats")], [InlineKeyboardButton(f"🛠️ الجودة: {'عالية' if q=='best' else 'خفيفة'}", callback_data="toggle_quality"), InlineKeyboardButton(f"🖼️ الألبوم: {'أول 10' if limit10 else 'الكل'}", callback_data="toggle_album_limit")], [InlineKeyboardButton("👨‍💻 عن المطور", callback_data="developer")]]
    return InlineKeyboardMarkup(kb)
def album_kb(session_id: str, post_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("📦 تنزيل الألبوم كـ ZIP", callback_data=f"zip|{session_id}")], [InlineKeyboardButton("👤 فتح المنشور الأصلي", url=post_url)]])

# ============================ 4) TikTok (No WM) ===============================
# ... (This section is complete and correct, no changes needed)
async def download_tiktok_no_wm(url: str, workfile: str) -> Optional[str]:
    try:
        api = f"https://www.tikwm.com/api/?url={url}"; r = requests.get(api, headers={"User-Agent": "Mozilla/5.0"}, timeout=20); r.raise_for_status()
        data = (r.json() or {}).get("data") or {}; dlink = data.get("play")
        if not dlink: return None
        with requests.get(dlink, stream=True, timeout=60) as v:
            v.raise_for_status()
            with open(workfile, "wb") as f:
                for chunk in v.iter_content(1024 * 1024):
                    if chunk: f.write(chunk)
        return workfile
    except Exception as e:
        logger.warning(f"TikTok no-wm failed: {e}"); return None

# =========================== 5) yt-dlp Utilities ==============================
# ... (This section is complete and correct, no changes needed)
IG_DOMAINS = ("instagram.com", "www.instagram.com")
def base_ydl_opts(download: bool = False, outtmpl: Optional[str] = None) -> dict:
    opts = {"quiet": True, "noprogress": True, "ignoreerrors": True, "retries": 3, "concurrent_fragment_downloads": 4, "nocheckcertificate": True, "cachedir": False, "http_headers": {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36", "Accept-Language": "en-US,en;q=0.9,ar;q=0.8"}}
    cookie_file = "cookies.txt"
    if os.path.exists(cookie_file): logger.info(f"Using cookies file: {cookie_file}"); opts["cookiefile"] = cookie_file
    if outtmpl: opts["outtmpl"] = outtmpl
    if not download: opts["skip_download"] = True
    return opts
def quality_format(q: str) -> str:
    return "b[ext=mp4]/bestvideo*+bestaudio/best" if q == "best" else "worst"

# ========================== 6) Instagram Extraction (Fallback Method) =========
# ... (This section is complete and correct, no changes needed)
def extract_instagram_items(url: str) -> Tuple[List[Dict], Dict]:
    items: List[Dict] = []; meta: Dict = {"title": "", "owner": ""}
    opts = base_ydl_opts(download=False)
    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            if not info: logger.warning(f"yt-dlp returned no info for URL: {url}"); return items, meta
            def push_from_entry(e):
                if not e: return
                media_url = e.get("url") or e.get("webpage_url")
                ext = (e.get("ext") or "").lower(); vcodec = e.get("vcodec")
                typ = "video" if (ext in {"mp4", "webm", "mkv"} or (vcodec and vcodec != "none")) else "photo"
                if not ext: ext = "mp4" if typ == "video" else "jpg"
                filename = f"{e.get('id','ig')}.{ext}"
                if media_url: items.append({"type": typ, "url": media_url, "filename": filename})
            if info.get("_type") == "playlist" and info.get("entries"):
                for entry in info["entries"]:
                    if entry: push_from_entry(entry)
                meta["title"] = info.get("title") or ""; meta["owner"] = (info.get("uploader") or info.get("channel") or "").lstrip("@")
            else:
                push_from_entry(info)
                meta["title"] = info.get("title") or ""; meta["owner"] = (info.get("uploader") or info.get("channel") or "").lstrip("@")
        except Exception as e:
            logger.error(f"An exception occurred inside extract_instagram_items: {e}"); return [], {}
    return items, meta

# ============================== 7) Generic Download ===========================
# ... (This section is complete and correct, no changes needed)
def ytdlp_download(url: str, outtmpl: str, q: str = "best") -> Optional[str]:
    try:
        opts = base_ydl_opts(download=True, outtmpl=outtmpl); opts["format"] = quality_format(q); opts["merge_output_format"] = "mp4"
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True); return ydl.prepare_filename(info)
    except Exception as e:
        logger.error(f"yt-dlp download failed: {e}"); return None

# ============================== 8) ZIP Creation ===============================
# ... (This section is complete and correct, no changes needed)
def download_and_zip(items: List[Dict], zip_path: str) -> str:
    tmpdir = tempfile.mkdtemp(prefix="igzip_")
    try:
        for it in items:
            local = os.path.join(tmpdir, it["filename"])
            with requests.get(it["url"], stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(local, "wb") as f:
                    for chunk in r.iter_content(1024 * 1024):
                        if chunk: f.write(chunk)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for root, _, files in os.walk(tmpdir):
                for fn in files:
                    full = os.path.join(root, fn); z.write(full, os.path.relpath(full, tmpdir))
        return zip_path
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

# ======================== 8.5) Unified Instagram API Downloader ================
# ... (This section is complete and correct, no changes needed)
async def get_insta_media_from_api(url: str) -> Optional[Tuple[List[Dict], Dict]]:
    try:
        api_url = "https://igdownloader.app/api/ajaxSearch"; headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36', 'Content-Type': 'application/x-www-form-urlencoded', 'Origin': 'https://igdownloader.app', 'Referer': 'https://igdownloader.app/'}
        payload = {'q': url, 'type': 'post'}
        async with httpx.AsyncClient() as client:
            r = await client.post(api_url, data=payload, headers=headers, timeout=30); r.raise_for_status(); data = r.json()
        if not data or not data.get("status") == "ok" or "data" not in data: logger.warning(f"Unified API returned a non-ok status for {url}"); return None
        soup = BeautifulSoup(data["data"], "html.parser"); items: List[Dict] = []; meta: Dict = {"title": (soup.find("p", class_="title").text if soup.find("p", class_="title") else "تم التحميل"), "owner": "Instagram"}
        download_widgets = soup.find_all("div", class_="download-items")
        if not download_widgets: return None
        for i, widget in enumerate(download_widgets):
            thumbnail_img = widget.find("img", class_="img-fluid"); download_link = widget.find("a", class_="abutton")
            if not (thumbnail_img and download_link and download_link.get("href")): continue
            href = download_link["href"]; is_video = "video" in thumbnail_img.get("alt", "").lower()
            media_type = "video" if is_video else "photo"; ext = "mp4" if is_video else "jpg"
            filename = f"api_media_{i}.{ext}"
            items.append({"type": media_type, "url": href, "filename": filename})
        return items, meta
    except Exception as e:
        logger.error(f"Unified Instagram API downloader failed: {e}"); return None
        
# =============================== 9) Commands/UI ===============================
# ... (This section is complete and correct, no changes needed)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; user_quality.setdefault(user.id, "best"); user_album_limit.setdefault(user.id, False); db_init()
    text = (f"👋 أهلاً {user.mention_html()}!\n\n" "أرسل أي رابط من:\n" "• 🎵 TikTok (بدون علامة مائية)\n" "• 📸 Instagram (صور/فيديو/ألبوم كـ MediaGroup + ZIP)\n" "• 🎥 YouTube وغيرها مع اختيار الجودة\n\n" "✨ سريع، نظيف، وواجهة أنيقة.")
    await update.message.reply_html(text, reply_markup=main_menu_kb(user.id))
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    try: await q.answer()
    except Exception as e: logger.warning(f"Failed to answer callback query, likely old: {e}"); return
    uid = q.from_user.id
    if q.data == "help":
        text = ("📌 **طريقة الاستخدام:**\n" "1) انسخ رابط المنشور.\n" "2) الصقه هنا.\n" "3) سيُرسل المحتوى مباشرة. للألبومات: تُرسل كـ MediaGroup، ويمكن تنزيلها كـ ZIP.\n\n" "🛠️ من الإعدادات يمكنك تبديل جودة التحميل، وتحديد إرسال أول 10 عناصر فقط من الألبوم.")
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=main_menu_kb(uid))
    elif q.data == "stats":
        db_init(); count = db_get_count(uid)
        await q.edit_message_text(f"📊 حمّلت: **{count}** وسيط/ملف.", parse_mode="Markdown", reply_markup=main_menu_kb(uid))
    elif q.data == "toggle_quality":
        cur = user_quality.get(uid, "best"); user_quality[uid] = "worst" if cur == "best" else "best"
        await q.edit_message_text("✅ تم تبديل جودة التحميل.", reply_markup=main_menu_kb(uid))
    elif q.data == "toggle_album_limit":
        cur = user_album_limit.get(uid, False); user_album_limit[uid] = not cur
        await q.edit_message_text("✅ تم تغيير نطاق الألبوم.", reply_markup=main_menu_kb(uid))
    elif q.data == "developer":
        dev_text = ("👨‍💻 **عن المطور**\n\n" "تم تطوير هذا البوت بواسطة **علي مهدي**.\n" "للتواصل أو للاستفسار، يمكنك زيارة [حساب المطور](https://t.me/ali_mahdi_1).")
        await q.edit_message_text(dev_text, parse_mode="Markdown", reply_markup=main_menu_kb(uid))
    elif q.data.startswith("zip|"):
        _, sid = q.data.split("|", 1); sess = sessions.get(sid)
        if not sess: await q.edit_message_text("❌ انتهت صلاحية الجلسة. أعد إرسال الرابط.", reply_markup=main_menu_kb(uid)); return
        await q.edit_message_text("⏳ جاري تجهيز ملف ZIP...")
        try:
            zip_path = os.path.join(tempfile.gettempdir(), f"album_{sid.replace(':','_')}.zip"); download_and_zip(sess["items"], zip_path)
            with open(zip_path, "rb") as f:
                await q.message.reply_document(document=f, caption=f"📦 ألبوم @{sess.get('owner','')} — {sess.get('title','')[:100]}")
            try: os.remove(zip_path)
            except: pass
            await q.edit_message_text("✅ تم إرسال ملف ZIP.", reply_markup=main_menu_kb(uid))
        except Exception as e:
            logger.error(f"ZIP error: {e}"); await q.edit_message_text("❌ فشل إنشاء ZIP. حاول لاحقًا.", reply_markup=main_menu_kb(uid))

# =============================== 10) Routing & Main Logic =====================

async def download_media_content(url: str, is_photo: bool) -> Optional[bytes]:
    """Downloads content from a URL and returns it as bytes. For photos, it validates the content."""
    try:
        async with httpx.AsyncClient() as client:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
            response = await client.get(url, timeout=60, headers=headers, follow_redirects=True)
            response.raise_for_status()
            content = response.content
        if is_photo:
            try:
                image_stream = io.BytesIO(content); img = Image.open(image_stream); img.verify()
            except Exception as validation_error:
                logger.error(f"Validation failed for image from {url}. It's likely not a direct image link. Error: {validation_error}"); return None
        return content
    except Exception as e:
        logger.error(f"Failed to download URL to bytes: {url}. Error: {e}"); return None

URL_RE = re.compile(r"(https?://\S+)", re.IGNORECASE)

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    url_match = URL_RE.search(update.message.text)
    if not url_match: return
    url = url_match.group(1); chat_id = update.effective_chat.id; msg_id = update.message.message_id
    uid = update.effective_user.id; qpref = user_quality.get(uid, "best")
    limit10 = user_album_limit.get(uid, False)
    processing = await update.message.reply_text("⏳ جاري تحليل الرابط...")
    sent_count = 0
    try:
        if any(d in url for d in IG_DOMAINS):
            items, meta = None, None
            await processing.edit_text("⏳ [1/2] المحاولة عبر الواجهة السريعة...")
            api_result = await get_insta_media_from_api(url)
            if api_result:
                items, meta = api_result; logger.info(f"Success with Unified API for {url}")
            else:
                logger.warning(f"API failed. Falling back to yt-dlp for {url}.")
                await processing.edit_text("⏳ [2/2] المحاولة عبر الطريقة المباشرة...")
                items, meta = extract_instagram_items(url)
            if not items:
                await processing.edit_text("❌ فشلت كل المحاولات لاستخراج المحتوى. قد يكون المنشور خاصاً أو تم حذفه."); return
            
            if limit10 and len(items) > 10: items = items[:10]
            await processing.edit_text(f"✅ تم العثور على {len(items)} عنصر. جاري التنزيل والرفع...")
            
            sid = make_session_id(chat_id, msg_id); sessions[sid] = {"items": items, "title": meta.get("title",""), "owner": meta.get("owner",""), "post_url": url}
            owner = meta.get("owner") or "instagram"; caption_text = f"👤 @{owner}\n📝 { (meta.get('title') or '').strip()[:500] }"
            
            groups: List[List] = []; current: List = []; is_first_item = True
            for i, item in enumerate(items):
                await processing.edit_text(f"📥 جاري تنزيل العنصر رقم {i+1}/{len(items)}...")
                is_photo = item["type"] == "photo"
                media_bytes = await download_media_content(item["url"], is_photo)
                if not media_bytes:
                    logger.warning(f"Failed to download or validate item {i+1}, skipping."); continue
                caption_for_this_item = caption_text if is_first_item else None
                media_input = InputMediaPhoto(media=media_bytes, caption=caption_for_this_item) if is_photo else InputMediaVideo(media=media_bytes, caption=caption_for_this_item)
                current.append(media_input); is_first_item = False
                if len(current) == 10: groups.append(current); current = []
            if current: groups.append(current)

            if not groups: await processing.edit_text("❌ فشل تنزيل كل العناصر من الروابط المستخرجة."); return

            await processing.edit_text(f"📤 جاري رفع {sum(len(g) for g in groups)} عنصر إلى تيليجرام...")
            for g in groups:
                await context.bot.send_media_group(chat_id=chat_id, media=g); sent_count += len(g)
            
            await processing.delete()
            await context.bot.send_message(chat_id=chat_id, text=f"تم إرسال الألبوم ({sent_count} عنصر).", reply_markup=album_kb(sid, url))
        
        elif "tiktok.com" in url:
            workfile = os.path.join(tempfile.gettempdir(), f"tiktok_{chat_id}_{msg_id}.mp4"); path = await download_tiktok_no_wm(url, workfile)
            if not path or not os.path.exists(path):
                outtmpl = os.path.join(tempfile.gettempdir(), f"tiktok_{chat_id}_{msg_id}.%(ext)s"); path = ytdlp_download(url, outtmpl, q=qpref)
            if not path or not os.path.exists(path): await processing.edit_text("❌ فشل التحميل من TikTok."); return
            await processing.edit_text("✅ تم التحميل! جاري الإرسال...")
            with open(path, "rb") as f:
                await context.bot.send_video(chat_id=chat_id, video=f, caption="🎬 TikTok بدون علامة مائية")
            sent_count += 1; os.remove(path); await processing.delete()

        else: # Generic (YouTube, etc.)
            outtmpl = os.path.join(tempfile.gettempdir(), f"media_{chat_id}_{msg_id}.%(ext)s"); path = ytdlp_download(url, outtmpl, q=qpref)
            if not path or not os.path.exists(path): await processing.edit_text("❌ لم أتمكن من التحميل. تأكد من الرابط."); return
            await processing.edit_text("✅ تم التحميل! جاري الإرسال...")
            if path.lower().endswith((".jpg",".jpeg",".png",".webp")):
                with open(path, "rb") as f: await context.bot.send_photo(chat_id=chat_id, photo=f, caption="📸")
            else:
                with open(path, "rb") as f: await context.bot.send_video(chat_id=chat_id, video=f, caption=f"🎬 تم التحميل ({'HD' if qpref=='best' else 'SD'})")
            sent_count += 1; os.remove(path); await processing.delete()
            
        if sent_count > 0: db_init(); db_inc_count(uid, sent_count)
    except Exception as e:
        logger.exception("handle_link error")
        try: await processing.edit_text(f"❌ حدث خطأ غير متوقع: {e}")
        except: pass

# ================================ 11) Main ====================================

async def post_init_tasks(application: Application):
    print("ℹ️ التحقق من Webhook وحذفه إن وجد...")
    if await application.bot.get_webhook_info():
        await application.bot.delete_webhook()
        print("✅ تم حذف الـ Webhook بنجاح.")
    else:
        print("👍 لا يوجد Webhook، سيتم البدء بـ Polling مباشرة.")

def main():
    if not TELEGRAM_BOT_TOKEN:
        print("❌ لم يتم العثور على TELEGRAM_BOT_TOKEN في .env"); return
    db_init()
    app = (Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init_tasks).build())
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    print("🚀 البوت يعمل الآن...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
