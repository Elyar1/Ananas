import os, sys, json, time, asyncio, requests
from telethon import TelegramClient
from telethon.sessions import StringSession

TOKEN = os.environ["TG_BOT_TOKEN"]
OWNER = os.environ["TG_OWNER_ID"]
API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
MSG_ID = int(sys.argv[1])

def notify(text):
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      data={"chat_id": OWNER, "text": text[:4000]}, timeout=20)
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
            notify(f"❌ پیام {MSG_ID} یا ویدیوش پیدا نشد.")
            sys.exit(1)
        stage = "download"
        t0 = time.time()
        path = await client.download_media(msg, file=f"dl_{MSG_ID}")
        meta = {"path": path, "caption": msg.message or "",
                "size": os.path.getsize(path), "secs": round(time.time() - t0)}
        with open(f"meta_{MSG_ID}.json", "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False)
        print("stage: download ok")
    except SystemExit:
        raise
    except Exception as e:
        print("stage failed:", stage)
        notify(f"❌ خطا در مرحله‌ی «{stage}» (پیام {MSG_ID}): {type(e).__name__}: {str(e)[:300]}")
        sys.exit(1)
    finally:
        await client.disconnect()

asyncio.run(main())
