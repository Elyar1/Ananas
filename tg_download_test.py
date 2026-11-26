import os, time, asyncio
from telethon import TelegramClient, events
from telethon.sessions import StringSession

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
BOT_TOKEN = os.environ["TG_BOT_TOKEN"]
WAIT_SECONDS = 15 * 60

async def main():
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.start(bot_token=BOT_TOKEN)
    me = await client.get_me()
    print("logged in as bot:", me.username, flush=True)
    done = asyncio.Event()

    @client.on(events.NewMessage(incoming=True))
    async def handler(event):
        msg = event.message
        if not (msg.video or msg.document):
            await event.reply("ویدیو رو بفرست")
            return
        size = msg.file.size if msg.file else 0
        print(f"got media: {size/1e6:.1f} MB, caption={msg.message!r}", flush=True)
        await event.reply(f"دریافت شد ({size/1e6:.0f} MB)، شروع دانلود...")
        t0 = time.time()
        last = [0.0]

        def prog(cur, total):
            if time.time() - last[0] > 10:
                last[0] = time.time()
                print(f"  {cur/1e6:.0f}/{total/1e6:.0f} MB", flush=True)

        path = await client.download_media(msg, file="video_dl", progress_callback=prog)
        dt = max(time.time() - t0, 1)
        real = os.path.getsize(path)
        print(f"DOWNLOADED {path} {real/1e6:.1f} MB in {dt:.0f}s ({real/1e6/dt:.1f} MB/s)", flush=True)
        await event.reply(f"دانلود کامل شد: {real/1e6:.0f} MB در {dt:.0f} ثانیه")
        done.set()

    print("listening... send a video to the bot now", flush=True)
    try:
        await asyncio.wait_for(done.wait(), timeout=WAIT_SECONDS)
    except asyncio.TimeoutError:
        print("TIMEOUT: no video received", flush=True)
        raise SystemExit(1)
    finally:
        await client.disconnect()

asyncio.run(main())
