import os, re, sys, time, asyncio, urllib.parse, urllib.request
from telethon import TelegramClient
from telethon.sessions import StringSession

TOKEN = os.environ["TG_BOT_TOKEN"]
OWNER = os.environ["TG_OWNER_ID"]
API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
MSG_ID = int(os.environ["MESSAGE_ID"])
MODEL = os.environ.get("MODEL", "")
AI = os.environ.get("AI", "0") == "1"
MIN_TAGS, MAX_TAGS = 3, 5

KEYS = {"عنوان": "title", "توضیحات": "description", "دسته": "category",
        "برچسب": "tags", "انتشار": "mode"}
PAT = re.compile(r"^\s*(عنوان|توضیحات|دسته|برچسب(?:\u200c?ها)?|انتشار)\s*[:：]\s*(.*)$")

def parse_caption(text):
    data, cur = {}, None
    for line in text.splitlines():
        m = PAT.match(line)
        if m:
            k = m.group(1)
            cur = KEYS["برچسب" if k.startswith("برچسب") else k]
            data[cur] = m.group(2)
        elif cur:
            data[cur] += "\n" + line
    data = {k: v.strip() for k, v in data.items()}
    data["tags"] = [t.strip() for t in re.split(r"[،,\n]", data.get("tags", "")) if t.strip()]
    return data

def notify(text):
    data = urllib.parse.urlencode({"chat_id": OWNER, "text": text[:4000]}).encode()
    try:
        urllib.request.urlopen(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data, timeout=20).read()
    except Exception:
        print("notify failed")

async def main():
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    stage = "login"
    try:
        await client.start(bot_token=TOKEN)
        stage = "fetch message"
        msg = await client.get_messages(None, ids=MSG_ID)
        if not msg or not msg.media:
            print("stage failed: no message")
            notify("❌ پیام یا ویدیوش پیدا نشد.")
            sys.exit(1)
        f = parse_caption(msg.message or "")
        missing = [n for n, ok in (("عنوان", f.get("title")), ("دسته", f.get("category")),
                                   ("برچسب", len(f["tags"]) >= MIN_TAGS)) if not ok]

        stage = "download"
        size = msg.file.size or 0
        notify(f"⬇️ دانلود شروع شد ({size/1e6:.0f} MB)")
        t0 = time.time()
        path = await client.download_media(msg, file="video_dl")
        dt = max(time.time() - t0, 1)
        real = os.path.getsize(path)
        print("stage: download ok")

        notify("\n".join([
            f"✅ دانلود شد: {real/1e6:.0f} MB در {dt:.0f} ثانیه",
            f"عنوان: {f.get('title') or '—'}",
            f"دسته: {f.get('category') or '—'}",
            f"برچسب‌ها: {'، '.join(f['tags']) or '—'}",
            f"کم‌ها: {'، '.join(missing) or 'ندارد'} | جمینای لازم: {'بله' if AI else 'نه'} | مدل: {MODEL or '—'}",
            "(مرحله‌ی تست: آپلود آپارات هنوز وصل نشده)",
        ]))
    except SystemExit:
        raise
    except Exception as e:
        print("stage failed:", stage)
        notify(f"❌ خطا در مرحله‌ی «{stage}»: {type(e).__name__}: {str(e)[:300]}")
        sys.exit(1)
    finally:
        await client.disconnect()

asyncio.run(main())
