import os, re, sys, json, difflib, subprocess
from collections import Counter
import requests
from playwright.sync_api import sync_playwright

TOKEN = os.environ["TG_BOT_TOKEN"]
OWNER = os.environ["TG_OWNER_ID"]
USER = os.environ["APARAT_USER"]
PASS = os.environ["APARAT_PASS"]
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = os.environ.get("MODEL") or "gemini-3.5-flash-lite"
IDS = list(dict.fromkeys(int(x) for x in re.split(r"[,\s]+", os.environ["MESSAGE_IDS"]) if x.strip()))
MIN_TAGS, MAX_TAGS = 3, 5
PL_MAX, PL_WARN = 100, 90
API = f"https://api.telegram.org/bot{TOKEN}"
STATE = {"cats": None, "playlists": {}}
procs = {}

FALLBACK_CATS = ["خانه و زندگی", "محیط زیست", "مالی و اقتصادی", "اجتماعی", "علوم پایه",
                 "فرهنگ و هنر", "استایل و مد", "سلامت و تندرستی", "غذا و نوشیدنی",
                 "خودرو و وسایل نقلیه", "کودک و خانواده", "قانون و سیاست",
                 "فناوری و رایانه", "سفر و گردشگری", "حیوانات", "کسب و کار"]

KEYS = {"عنوان": "title", "توضیحات": "description", "دسته": "category",
        "برچسب": "tags", "انتشار": "mode"}
PAT = re.compile(r"^\s*(عنوان|توضیحات|دسته|برچسب(?:\u200c?ها)?|انتشار)\s*[:：]\s*(.*)$")
LINK_RE = re.compile(r"(?:https?://)?(?:www\.)?aparat\.com/v/([A-Za-z0-9_-]+)")

SYSTEM = """You prepare Aparat (Persian video site) metadata for a channel owner.
Return ONLY a JSON object with keys: title, description, category, tags, playlist.
- Write in natural Persian. Do not invent facts beyond the caption.
- title: max 80 characters.
- description: 2-5 short sentences, max 800 characters.
- category: MUST be copied exactly from CATEGORIES.
- tags: array of 3 to 5 short Persian tags (1-3 words, no commas).
- playlist: MUST be copied exactly from PLAYLISTS, or "" if none fits.
- If a field is listed in already_provided, repeat it unchanged."""

# ---------------- helpers ----------------
def notify(text):
    try:
        requests.post(API + "/sendMessage", data={"chat_id": OWNER, "text": text[:4000]}, timeout=20)
    except Exception:
        print("notify failed")

def notify_photo(png, caption):
    try:
        requests.post(API + "/sendPhoto", data={"chat_id": OWNER, "caption": caption[:1000]},
                      files={"photo": ("e.png", png)}, timeout=60)
    except Exception:
        print("notify failed")

def to_int(s):
    s = s.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    m = re.search(r"\d+", s)
    return int(m.group()) if m else 0

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

def closest(v, options):
    v = (v or "").strip()
    if v in options:
        return v
    m = difflib.get_close_matches(v, options, n=1, cutoff=0.6)
    return m[0] if m else ""

def start_fetch(mid):
    if mid not in procs:
        procs[mid] = subprocess.Popen([sys.executable, "tg_fetch.py", str(mid)])

# ---------------- gemini ----------------
def gemini(model, system, user):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    if model.startswith("gemma"):
        body = {"contents": [{"role": "user", "parts": [{"text": system + "\n\n" + user}]}]}
    else:
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.4}}
    r = requests.post(url, headers={"x-goog-api-key": GEMINI_KEY}, json=body, timeout=90)
    if r.status_code == 429:
        raise RuntimeError("سقف رایگان این مدل پر شده؛ با /models مدل دیگه‌ای انتخاب کن یا فیلدها رو دستی بنویس")
    r.raise_for_status()
    parts = r.json()["candidates"][0]["content"]["parts"]
    t = "".join(p.get("text", "") for p in parts).strip()
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.M).strip()
    return json.loads(t)

def build_fields(f, caption, cats, open_lists):
    missing = (not f.get("title")) or (not f.get("category")) or len(f["tags"]) < MIN_TAGS
    out = dict(f)
    out["playlist"] = ""
    if not (missing or open_lists):
        return out
    if not GEMINI_KEY:
        if missing:
            raise RuntimeError("فیلدها کامل نیست و GEMINI_API_KEY توی گیت‌هاب تنظیم نشده")
        return out
    given = {k: f[k] for k in ("title", "description", "category") if f.get(k)}
    if f["tags"]:
        given["tags"] = f["tags"]
    payload = {"caption": caption, "already_provided": given,
               "CATEGORIES": cats, "PLAYLISTS": list(open_lists)}
    ai = gemini(MODEL, SYSTEM, json.dumps(payload, ensure_ascii=False))
    for k in ("title", "description"):
        if not out.get(k):
            out[k] = str(ai.get(k, "") or "").strip()
    out["category"] = closest(out.get("category") or str(ai.get("category", "") or ""), cats) or out.get("category", "")
    tags = list(out["tags"])
    for t in (ai.get("tags") or []):
        t = str(t).replace("،", " ").replace(",", " ").strip()
        if t and t not in tags and len(tags) < MAX_TAGS:
            tags.append(t)
    out["tags"] = tags
    pl = ai.get("playlist") or ""
    out["playlist"] = closest(str(pl), list(open_lists)) if open_lists else ""
    if not out["title"] or not out["category"] or len(out["tags"]) < MIN_TAGS:
        raise RuntimeError("جمینای فیلدها رو کامل نساخت (عنوان/دسته/برچسب)")
    return out

# ---------------- aparat ----------------
def login(page):
    page.goto("https://www.aparat.com/login?returnUrl=/reactupload", timeout=45000)
    page.locator("input").first.fill(USER)
    page.get_by_role("button", name="ادامه").click()
    page.locator("input[type=password]").fill(PASS, timeout=15000)
    page.keyboard.press("Enter")
    page.wait_for_url("**/reactupload**", timeout=30000)
    page.wait_for_timeout(2000)

def read_playlists(ctx):
    pg = ctx.new_page()
    try:
        pg.goto("https://www.aparat.com/dashboard/myvideos/playlist", timeout=45000)
        pg.wait_for_selector(".playlist-cnt", timeout=30000)
        m = re.search(r"از\s*([0-9۰-۹]+)\s*لیست", pg.inner_text("body"))
        total = to_int(m.group(1)) if m else 0
        out, prev_first = {}, None
        for _ in range(15):
            rows = pg.locator("[role=row]").filter(has=pg.locator(".playlist-cnt"))
            first = None
            for i in range(rows.count()):
                r = rows.nth(i)
                title = (r.locator("img").first.get_attribute("alt") or "").strip()
                if first is None:
                    first = title
                if title:
                    out[title] = to_int(r.locator(".playlist-cnt").first.inner_text())
            if (total and len(out) >= total) or first == prev_first:
                break
            prev_first = first
            nxt = pg.get_by_role("button", name="صفحه بعد")
            if nxt.count() == 0:
                nxt = pg.get_by_text("صفحه بعد")
            if nxt.count() == 0 or not nxt.first.is_enabled():
                break
            nxt.first.click()
            pg.wait_for_timeout(2500)
        return out
    finally:
        pg.close()

def close_dd(page):
    sel = "input[name='searchbar']:visible"
    if page.locator(sel).count():
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
    if page.locator(sel).count():
        page.mouse.click(6, 300)
        page.wait_for_timeout(400)

def dd_search(page):
    loc = page.locator("input[name='searchbar']:visible")
    if loc.count() == 0:
        loc = page.locator("input[placeholder='جستجو...']:visible")
    return loc.first

def page_lines(page):
    return [l.strip() for l in page.inner_text("body").splitlines() if l.strip()]

def read_categories(page):
    close_dd(page)
    base = Counter(page_lines(page))
    page.get_by_text("دسته‌بندی آپارات").first.click()
    page.wait_for_timeout(1000)
    try:
        box = dd_search(page).bounding_box()
    except Exception:
        box = None
    found = []
    for _ in range(14):
        for line, n in Counter(page_lines(page)).items():
            if (n > base.get(line, 0) and line not in found and len(line) > 1
                    and not line.startswith("جستجو") and "در حال جستجو" not in line):
                found.append(line)
        if box:
            page.mouse.move(box["x"] + 100, box["y"] + 140)
        page.mouse.wheel(0, 250)
        page.wait_for_timeout(300)
    close_dd(page)
    return found

def pick(page, label, text):
    close_dd(page)
    page.get_by_text(label).first.click()
    page.wait_for_timeout(900)
    dd_search(page).fill(text[:25])
    page.wait_for_timeout(1200)
    try:
        opt = page.get_by_role("option", name=text, exact=True)
        if opt.count():
            opt.first.click()
            return True
        t = page.get_by_text(text, exact=True)
        if t.count():
            t.last.click()
            return True
        return False
    finally:
        page.wait_for_timeout(500)
        close_dd(page)

def add_tags(page, tags):
    label = page.get_by_text("برچسب‌های ویدیو").first
    add_sel = "button.add-item-btn:visible"
    close_dd(page)
    label.click()
    page.wait_for_timeout(1000)
    for t in tags:
        if page.locator(add_sel).count() == 0:
            label.click()
            page.wait_for_timeout(1000)
        tag_in = page.locator("input[name='searchbar']:visible").last
        tag_in.click()
        tag_in.fill(t)
        page.wait_for_timeout(1200)
        page.locator(add_sel).first.click()
        page.wait_for_timeout(1200)
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)

def find_link(page):
    try:
        extra = page.evaluate("""() => [...document.querySelectorAll('input,textarea')].map(e => e.value || '')
            .concat([...document.querySelectorAll('a[href]')].map(a => a.href))""")
    except Exception:
        extra = []
    txt = "\n".join(extra) + "\n" + page.inner_text("body")
    m = LINK_RE.search(txt)
    return "https://www.aparat.com/v/" + m.group(1) if m else None

def process(ctx, idx, total, mid, proc, start_next):
    tag = f"[{idx}/{total}] "
    stage, page, path = "download", None, None
    try:
        rc = proc.wait()
        start_next()  # دانلود ویدیوی بعدی هم‌زمان با آپلود این یکی
        if rc != 0:
            print("stage failed: download")
            return False  # tg_fetch خودش خطا رو گزارش کرده
        meta_file = f"meta_{mid}.json"
        with open(meta_file, encoding="utf-8") as fh:
            meta = json.load(fh)
        os.remove(meta_file)
        path, caption = meta["path"], meta["caption"]
        notify(f"{tag}⬇️ دانلود شد ({meta['size']/1e6:.0f} MB، {meta['secs']} ثانیه). آپلود شروع شد.")
        f = parse_caption(caption)
        if len(f["tags"]) > MAX_TAGS:
            raise RuntimeError(f"حداکثر {MAX_TAGS} برچسب مجازه")
        save_only = f.get("mode", "").startswith("ذخیره")

        stage = "open upload page"
        page = ctx.new_page()
        page.goto("https://www.aparat.com/reactupload", timeout=45000)
        page.locator("input[type=file]").first.set_input_files(path)
        page.get_by_placeholder("عنوان ویدیو").wait_for(timeout=90000)

        stage = "read categories"
        open_lists = {t: c for t, c in STATE["playlists"].items() if c < PL_MAX}
        missing = (not f.get("title")) or (not f.get("category")) or len(f["tags"]) < MIN_TAGS
        if STATE["cats"] is None and (missing or open_lists):
            cats = read_categories(page)
            if len(cats) < 5:
                cats = FALLBACK_CATS
                notify("⚠️ دسته‌ها از فرم خونده نشد؛ از لیست پیش‌فرض استفاده شد.")
            else:
                notify("ℹ️ دسته‌ها (" + str(len(cats)) + "): " + "، ".join(cats))
            STATE["cats"] = cats
        cats = STATE["cats"] or FALLBACK_CATS

        stage = "metadata"
        fin = build_fields(f, caption, cats, open_lists)

        stage = "fill form"
        page.get_by_placeholder("عنوان ویدیو").fill(fin["title"][:100])
        if fin.get("description"):
            page.get_by_placeholder("توضیحات ویدیو").fill(fin["description"][:2000])
        if not pick(page, "دسته‌بندی آپارات", fin["category"]):
            raise RuntimeError("دسته توی لیست آپارات پیدا نشد: " + fin["category"])
        add_tags(page, fin["tags"])

        pl_note = "—"
        if fin["playlist"]:
            stage = "playlist"
            try:
                pl_note = fin["playlist"] if pick(page, "ذخیره در لیست پخش", fin["playlist"]) else "انتخاب نشد"
            except Exception:
                pl_note = "انتخاب نشد"
        if save_only:
            page.get_by_text("انتخاب زمان انتشار").first.click()
            page.get_by_text("ذخیره و عدم انتشار").click()
            page.wait_for_timeout(800)

        stage = "wait upload"
        page.get_by_text("آماده انتشار").first.wait_for(timeout=45 * 60 * 1000)

        stage = "publish"
        cancel = page.locator("button:has-text('انصراف')").first
        btn = cancel.locator("xpath=..").locator("button").filter(has_not_text="انصراف").first
        btn.click()

        stage = "get link"
        link = None
        for _ in range(40):
            link = find_link(page)
            if link:
                break
            page.wait_for_timeout(2000)
        if not link:
            raise RuntimeError("لینک ویدیو پیدا نشد. متن صفحه: " + page.inner_text("body")[:400].replace("\n", " | "))

        if pl_note not in ("—", "انتخاب نشد"):
            STATE["playlists"][fin["playlist"]] = STATE["playlists"].get(fin["playlist"], 0) + 1
        notify(f"{tag}{'📝 ذخیره شد (منتشر نشده)' if save_only else '✅ منتشر شد'}\n{link}\n"
               f"عنوان: {fin['title']}\nدسته: {fin['category']}\n"
               f"برچسب‌ها: {'، '.join(fin['tags'])}\nلیست: {pl_note}")
        if pl_note not in ("—", "انتخاب نشد"):
            n = STATE["playlists"][fin["playlist"]]
            if n >= PL_WARN:
                notify(f"⚠️ لیست «{fin['playlist']}» به {n} از {PL_MAX} رسید.")
        print("stage: upload ok")
        return True
    except Exception as e:
        print("stage failed:", stage)
        msg = f"{tag}❌ خطا در مرحله‌ی «{stage}»: {type(e).__name__}: {str(e)[:400]}"
        sent = False
        if page:
            try:
                notify_photo(page.screenshot(full_page=True), msg)
                sent = True
            except Exception:
                pass
        if not sent:
            notify(msg)
        return False
    finally:
        if page:
            try:
                page.close()
            except Exception:
                pass
        if path and os.path.exists(path):
            os.remove(path)

def main():
    if IDS:
        start_fetch(IDS[0])  # دانلود اولی هم‌زمان با لاگین و خوندن لیست‌ها
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(locale="fa-IR", viewport={"width": 1280, "height": 2200})
        try:
            pg = ctx.new_page()
            login(pg)
            pg.close()
        except Exception as e:
            print("stage failed: login")
            notify(f"❌ لاگین آپارات ناموفق: {type(e).__name__}")
            sys.exit(1)
        try:
            STATE["playlists"] = read_playlists(ctx)
            full = [t for t, c in STATE["playlists"].items() if c >= PL_MAX]
            notify(f"ℹ️ {len(STATE['playlists'])} لیست پخش خونده شد" + (f" (پر: {len(full)})" if full else ""))
        except Exception as e:
            print("stage failed: playlists")
            notify(f"⚠️ لیست‌های پخش خونده نشد ({type(e).__name__}). ویدیوها بدون لیست آپلود می‌شن.")
        ok = 0
        for i, mid in enumerate(IDS, 1):
            nxt = IDS[i] if i < len(IDS) else None
            start_next = (lambda n=nxt: start_fetch(n)) if nxt is not None else (lambda: None)
            if process(ctx, i, len(IDS), mid, procs.pop(mid), start_next):
                ok += 1
        if len(IDS) > 1:
            notify(f"پایان: {ok} از {len(IDS)} ویدیو موفق")
        browser.close()
        sys.exit(0 if ok == len(IDS) else 1)

main()
