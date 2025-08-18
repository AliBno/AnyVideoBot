# ==============================================================================
#            🔥 VIP Professional Telegram Media Downloader Bot 🔥
#                      Developed by: Ali Mahdi
# ==============================================================================

import asyncio
import logging
import os
import re
import shutil
import tempfile
import zipfile
from typing import List, Dict, Optional, Tuple

from dotenv import load_dotenv
import requests
import yt_dlp

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    InputMediaPhoto, InputMediaVideo, FSInputFile
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

# ============================ 1) In-Memory Store ==============================

user_stats: Dict[int, int] = {}             # {user_id: count}
user_quality: Dict[int, str] = {}           # {user_id: "best" | "worst"}
sessions: Dict[str, Dict] = {}              # session_id -> {"items":[{"type","url","filename"}], "title","owner"}

# helper to build session key per message
def make_session_id(chat_id: int, message_id: int) -> str:
    return f"{chat_id}:{message_id}"

# =============================== 2) UI Helpers ================================

def main_menu_kb(user_id: int) -> InlineKeyboardMarkup:
    q = user_quality.get(user_id, "best")
    kb = [
        [InlineKeyboardButton("ℹ️ طريقة الاستخدام", callback_data="help")],
        [InlineKeyboardButton("📊 إحصائياتي", callback_data="stats")],
        [
            InlineKeyboardButton(
                f"🛠️ جودة التحميل: {'عالية' if q=='best' else 'خفيفة'}",
                callback_data="toggle_quality"
            )
        ],
        [InlineKeyboardButton("👨‍💻 عن المطور", callback_data="developer")],
    ]
    return InlineKeyboardMarkup(kb)

def album_kb(session_id: str, post_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 تنزيل الألبوم كـ ZIP", callback_data=f"zip|{session_id}")],
        [InlineKeyboardButton("👤 فتح المنشور الأصلي", url=post_url)]
    ])

# ============================ 3) TikTok (No WM) ===============================

async def download_tiktok_no_wm(url: str, workfile: str) -> Optional[str]:
    try:
        api = f"https://www.tikwm.com/api/?url={url}"
        r = requests.get(api, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        r.raise_for_status()
        data = (r.json() or {}).get("data") or {}
        dlink = data.get("play")
        if not dlink:
            return None
        with requests.get(dlink, stream=True, timeout=60) as v:
            v.raise_for_status()
            with open(workfile, "wb") as f:
                for chunk in v.iter_content(1024 * 1024):
                    if chunk:
                        f.write(chunk)
        return workfile
    except Exception as e:
        logger.warning(f"TikTok no-wm failed: {e}")
        return None

# =========================== 4) yt-dlp Utilities ==============================

IG_DOMAINS = ("instagram.com", "www.instagram.com")

def base_ydl_opts(download: bool = False, outtmpl: Optional[str] = None) -> dict:
    opts = {
        "quiet": True,
        "noprogress": True,
        "ignoreerrors": True,
        "retries": 3,
        "concurrent_fragment_downloads": 4,
        "nocheckcertificate": True,
        "cachedir": False,
    }
    if outtmpl:
        opts["outtmpl"] = outtmpl
    if not download:
        opts["skip_download"] = True
    return opts

def quality_format(q: str) -> str:
    # prefer mp4 for videos when available
    if q == "best":
        return "b[ext=mp4]/bestvideo*+bestaudio/best"
    else:
        return "worst"

# ========================== 5) Instagram Extraction ===========================

def extract_instagram_items(url: str) -> Tuple[List[Dict], Dict]:
    """
    Returns (items, meta)
    items: list of {"type": "photo"|"video", "url": str, "filename": str}
    meta: {"title":str, "owner":str}
    Uses yt-dlp with download=False to get direct media URLs (fast).
    """
    items: List[Dict] = []
    meta: Dict = {"title": "", "owner": ""}

    opts = base_ydl_opts(download=False)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

        def push_from_entry(e):
            # Determine media url and type
            media_url = e.get("url") or e.get("webpage_url")
            ext = (e.get("ext") or "").lower()
            vcodec = e.get("vcodec")
            typ = "video" if (ext in {"mp4", "webm", "mkv"} or (vcodec and vcodec != "none")) else "photo"
            filename = f"{e.get('id','ig')}.{ext or ('mp4' if typ=='video' else 'jpg')}"
            if media_url:
                items.append({"type": typ, "url": media_url, "filename": filename})

        # playlist (album) vs single
        if info.get("_type") == "playlist" and info.get("entries"):
            for entry in info["entries"]:
                if not entry:
                    continue
                push_from_entry(entry)
            meta["title"] = info.get("title") or ""
            meta["owner"] = (info.get("uploader") or info.get("channel") or "").lstrip("@")
        else:
            push_from_entry(info)
            meta["title"] = info.get("title") or ""
            meta["owner"] = (info.get("uploader") or info.get("channel") or "").lstrip("@")

    return items, meta

# ============================== 6) Generic Download ===========================

def ytdlp_download(url: str, outtmpl: str, q: str = "best") -> Optional[str]:
    try:
        opts = base_ydl_opts(download=True, outtmpl=outtmpl)
        opts["format"] = quality_format(q)
        # merge mp4 when needed
        opts["merge_output_format"] = "mp4"
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return ydl.prepare_filename(info)
    except Exception as e:
        logger.error(f"yt-dlp download failed: {e}")
        return None

# ============================== 7) ZIP Creation ===============================

def download_and_zip(items: List[Dict], zip_path: str) -> str:
    """
    Downloads given media items and packs them into zip_path.
    Returns the zip path.
    """
    tmpdir = tempfile.mkdtemp(prefix="igzip_")
    try:
        for it in items:
            fname = it["filename"]
            url = it["url"]
            local = os.path.join(tmpdir, fname)
            with requests.get(url, stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(local, "wb") as f:
                    for chunk in r.iter_content(1024 * 1024):
                        if chunk:
                            f.write(chunk)
        # zip all
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for root, _, files in os.walk(tmpdir):
                for fn in files:
                    full = os.path.join(root, fn)
                    arc = os.path.relpath(full, tmpdir)
                    z.write(full, arc)
        return zip_path
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

# =============================== 8) Commands/UI ===============================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_quality.setdefault(user.id, "best")
    welcome = (
        f"👋 أهلاً {user.mention_html()}!\n\n"
        "أرسل أي رابط من:\n"
        "• 🎵 TikTok (بدون علامة مائية)\n"
        "• 📸 Instagram (صور/فيديو/ألبوم كـ MediaGroup + ZIP)\n"
        "• 🎥 YouTube وغيرها مع اختيار الجودة\n\n"
        "✨ سريع، نظيف، وواجهة أنيقة."
    )
    await update.message.reply_html(welcome, reply_markup=main_menu_kb(user.id))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    if q.data == "help":
        text = (
            "📌 **طريقة الاستخدام:**\n"
            "1) انسخ رابط المنشور.\n"
            "2) الصقه هنا.\n"
            "3) سيصل المحتوى فورًا. للألبومات: تُرسل كـ MediaGroup ويمكن تنزيلها كـ ZIP.\n\n"
            "🛠️ يمكنك تبديل جودة التحميل من الزر في القائمة."
        )
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=main_menu_kb(uid))

    elif q.data == "stats":
        count = user_stats.get(uid, 0)
        await q.edit_message_text(f"📊 حمّلت: **{count}** ملف/وسيط.", parse_mode="Markdown", reply_markup=main_menu_kb(uid))

    elif q.data == "toggle_quality":
        cur = user_quality.get(uid, "best")
        user_quality[uid] = "worst" if cur == "best" else "best"
        await q.edit_message_text("✅ تم تبديل جودة التحميل.", reply_markup=main_menu_kb(uid))

    elif q.data.startswith("zip|"):
        # zip callback: zip|<session_id>
        _, sid = q.data.split("|", 1)
        sess = sessions.get(sid)
        if not sess:
            await q.edit_message_text("❌ انتهت صلاحية الجلسة. أعد إرسال الرابط.", reply_markup=main_menu_kb(uid))
            return
        await q.edit_message_text("⏳ جاري تجهيز ملف ZIP...")
        try:
            zip_path = os.path.join(tempfile.gettempdir(), f"album_{sid.replace(':','_')}.zip")
            download_and_zip(sess["items"], zip_path)
            await q.message.reply_document(
                document=FSInputFile(zip_path),
                caption=f"📦 ألبوم @{'{0}'.format(sess.get('owner',''))} — {sess.get('title','')[:60]}"
            )
            try:
                os.remove(zip_path)
            except:
                pass
            await q.edit_message_text("✅ تم إرسال ملف ZIP.", reply_markup=main_menu_kb(uid))
        except Exception as e:
            logger.error(f"ZIP error: {e}")
            await q.edit_message_text("❌ فشل إنشاء ZIP. حاول لاحقًا.", reply_markup=main_menu_kb(uid))

# =============================== 9) Routing ===================================

URL_RE = re.compile(r"(https?://\S+)", re.IGNORECASE)

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    url_match = URL_RE.search(update.message.text)
    if not url_match:
        return

    url = url_match.group(1)
    chat_id = update.effective_chat.id
    msg_id = update.message.message_id
    uid = update.effective_user.id
    qpref = user_quality.get(uid, "best")

    processing = await update.message.reply_text("⏳ جاري تحليل الرابط...")

    try:
        sent_count = 0

        # Instagram (special handling: send album as MediaGroup)
        if any(d in url for d in IG_DOMAINS):
            items, meta = extract_instagram_items(url)

            if not items:
                await processing.edit_text("❌ لم أستطع استخراج محتوى إنستغرام. تأكد من أن الرابط عام.")
                return

            # Save session for ZIP
            sid = make_session_id(chat_id, msg_id)
            sessions[sid] = {"items": items, "title": meta.get("title",""), "owner": meta.get("owner","")}

            # Prepare media group chunks (Telegram allows up to 10 items per group)
            # We'll preserve order:
            groups: List[List] = []
            current: List = []
            for it in items:
                if it["type"] == "photo":
                    current.append(InputMediaPhoto(media=it["url"]))
                else:
                    current.append(InputMediaVideo(media=it["url"]))
                if len(current) == 10:
                    groups.append(current)
                    current = []
            if current:
                groups.append(current)

            # Send groups
            # First group with caption
            owner = meta.get("owner") or "instagram"
            caption = f"📸 ألبوم من @{owner}\n" if len(items) > 1 else f"من @{owner}"
            if groups:
                groups[0][0].caption = caption

            # edit processing and send
            await processing.edit_text("✅ تم التحميل! جاري الإرسال...")
            for g in groups:
                await context.bot.send_media_group(chat_id=chat_id, media=g)
                sent_count += len(g)

            # After sending, offer ZIP + link
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"تم إرسال الألبوم ({len(items)} عنصر).",
                reply_markup=album_kb(sid, url)
            )

        # TikTok (no watermark)
        elif "tiktok.com" in url:
            workfile = os.path.join(tempfile.gettempdir(), f"tiktok_{chat_id}_{msg_id}.mp4")
            path = await download_tiktok_no_wm(url, workfile)
            if not path or not os.path.exists(path):
                # fallback to yt-dlp
                outtmpl = os.path.join(tempfile.gettempdir(), f"tiktok_{chat_id}_{msg_id}.%(ext)s")
                path = ytdlp_download(url, outtmpl, q=pref)
            if not path or not os.path.exists(path):
                await processing.edit_text("❌ فشل التحميل من TikTok.")
                return
            await processing.edit_text("✅ تم التحميل! جاري الإرسال...")
            await context.bot.send_video(chat_id=chat_id, video=FSInputFile(path), caption="🎬 TikTok بدون علامة مائية")
            sent_count += 1
            try: os.remove(path)
            except: pass

        # Generic (YouTube, etc.)
        else:
            outtmpl = os.path.join(tempfile.gettempdir(), f"media_{chat_id}_{msg_id}.%(ext)s")
            path = ytdlp_download(url, outtmpl, q=qpref)
            if not path or not os.path.exists(path):
                await processing.edit_text("❌ لم أتمكن من التحميل. تأكد من الرابط.")
                return
            await processing.edit_text("✅ تم التحميل! جاري الإرسال...")
            if path.lower().endswith((".jpg",".jpeg",".png",".webp")):
                await context.bot.send_photo(chat_id=chat_id, photo=FSInputFile(path), caption="📸")
            else:
                await context.bot.send_video(chat_id=chat_id, video=FSInputFile(path), caption=f"🎬 تم التحميل ({'HD' if qpref=='best' else 'SD'})")
            sent_count += 1
            try: os.remove(path)
            except: pass

        # update stats
        if sent_count > 0:
            user_stats[uid] = user_stats.get(uid, 0) + sent_count

    except Exception as e:
        logger.exception("handle_link error")
        await processing.edit_text(f"❌ حدث خطأ غير متوقع: {e}")

# ================================ 10) Main ====================================

def main():
    if not TELEGRAM_BOT_TOKEN:
        print("❌ لم يتم العثور على TELEGRAM_BOT_TOKEN في .env")
        return

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))

    print("🚀 البوت يعمل الآن...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
