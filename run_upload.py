import os, re, sys, json, difflib, subprocess, datetime as dt
from collections import Counter
import jdatetime
import requests
from playwright.sync_api import sync_playwright

TOKEN = os.environ["TG_BOT_TOKEN"]
OWNER = os.environ["TG_OWNER_ID"]
USER = os.environ["APARAT_USER"]
PASS = os.environ["APARAT_PASS"]
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = os.environ.get("MODEL") or "gemini-3.5-flash-lite"
SCHED_START = os.environ.get("SCHED_START", "").strip()
SCHED_STEP = int(os.environ.get("SCHED_STEP") or 0)
DEVICE_RE = re.compile(os.environ.get("DEVICE_PATTERN") or "Linux")
MIN_TAGS, MAX_TAGS = 3, 5
PL_MAX, PL_WARN = 100, 90
API = f"https://api.telegram.org/bot{TOKEN}"
STATE = {"cats": None, "playlists": {}, "last_slot": None}
procs = {}
TEHRAN = dt.timezone(dt.timedelta(hours=3, minutes=30))

def parse_items(s):
    out, seen = [], set()
    for part in re.split(r"[,\s]+", s):
        if not part.strip():
            continue
        v, _, c = part.partition("+")
        v = int(v)
        if v in seen:
            continue
        seen.add(v)
        out.append((v, int(c) if c.strip() else None))
    return out

ITEMS = parse_items(os.environ["MESSAGE_IDS"])

FALLBACK_CATS = ["خانه و زندگی", "محیط زیست", "مالی و اقتصادی", "اجتماعی", "علوم پایه",
                 "فرهنگ و هنر", "استایل و مد", "سلامت و تندرستی", "غذا و نوشیدنی",
                 "خودرو و وسایل نقلیه", "کودک و خانواده", "قانون و سیاست",
                 "فناوری و رایانه", "سفر و گردشگری", "حیوانات", "کسب و کار"]
MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
          "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
HDR = re.compile("(" + "|".join(MONTHS) + r")\s+([0-9۰-۹]{4})")

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

FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
def fa(n):
    return str(n).translate(FA_DIGITS)

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

def fetch_now(mid):
    rc = subprocess.run([sys.executable, "tg_fetch.py", str(mid)]).returncode
    if rc != 0:
        return None
    mf = f"meta_{mid}.json"
    with open(mf, encoding="utf-8") as fh:
        meta = json.load(fh)
    os.remove(mf)
    return meta

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

# ---------------- aparat: login, devices, playlists ----------------
def login(page):
    page.goto("https://www.aparat.com/login?returnUrl=/reactupload", timeout=45000)
    page.locator("input").first.fill(USER)
    page.get_by_role("button", name="ادامه").click()
    page.locator("input[type=password]").fill(PASS, timeout=15000)
    page.keyboard.press("Enter")
    page.wait_for_url("**/reactupload**", timeout=30000)
    page.wait_for_timeout(2000)

def cleanup_devices(ctx):
    """دستگاه‌های قدیمی Linux (ران‌های قبلی) رو حذف می‌کنه تا سقف ۱۰ دستگاه پر نشه."""
    pg = ctx.new_page()
    removed = 0
    try:
        pg.goto("https://www.aparat.com/dashboard/settings/devices", timeout=45000)
        pg.wait_for_timeout(3000)
        for _ in range(12):
            target = None
            titles = pg.get_by_text(DEVICE_RE)
            for i in range(titles.count()):
                row = titles.nth(i).locator("xpath=ancestor::*[.//button][1]")
                txt = row.inner_text()
                if len(re.findall(r"WebKit", txt)) != 1 or "آنلاین" in txt:
                    continue
                btns = row.locator("button")
                if btns.count():
                    target = btns.last
                    break
            if target is None:
                break
            target.click()
            pg.wait_for_timeout(700)
            item = pg.get_by_text(re.compile(r"خروج|حذف|قطع")).first
            item.click()
            pg.wait_for_timeout(700)
            conf = pg.get_by_role("button", name=re.compile(r"^\s*(تأیید|تایید|بله|خروج|حذف)"))
            if conf.count():
                conf.last.click()
            pg.wait_for_timeout(1800)
            removed += 1
        if removed:
            notify(f"🧹 {removed} دستگاه قدیمی آپارات حذف شد.")
    except Exception as e:
        print("stage failed: devices")
        try:
            notify_photo(pg.screenshot(), f"⚠️ پاک‌سازی دستگاه‌ها ناموفق ({type(e).__name__}). اگه ۱۰ تا پر شده دستی حذف کن.")
        except Exception:
            notify(f"⚠️ پاک‌سازی دستگاه‌ها ناموفق ({type(e).__name__}).")
    finally:
        pg.close()

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

# ---------------- aparat: form ----------------
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

def set_cover(page, cover_path):
    with page.expect_file_chooser(timeout=15000) as fc:
        page.get_by_text("بارگذاری تصویر").first.click()
    fc.value.set_files(cover_path)
    page.wait_for_timeout(7000)

# ---------------- aparat: schedule ----------------
def next_slot(k):
    start = dt.datetime.strptime(SCHED_START, "%Y-%m-%d %H:%M").replace(tzinfo=TEHRAN)
    slot = start + dt.timedelta(minutes=SCHED_STEP * k)
    earliest = (dt.datetime.now(TEHRAN) + dt.timedelta(minutes=8)).replace(second=0, microsecond=0)
    if slot < earliest:
        slot = earliest
    last = STATE["last_slot"]
    if last and slot <= last:
        slot = last + dt.timedelta(minutes=max(SCHED_STEP, 1))
    STATE["last_slot"] = slot
    return slot

def cal_header(dlg):
    m = HDR.search(dlg.inner_text())
    return (to_int(m.group(2)), MONTHS.index(m.group(1)) + 1) if m else None

def goto_month(page, dlg, ty, tm):
    cur = cal_header(dlg)
    if cur is None:
        return False
    if cur == (ty, tm):
        return True
    hb = dlg.get_by_text(HDR).first.bounding_box()
    cy = hb["y"] + hb["height"] / 2
    arrows = []
    btns = dlg.locator("button, [role=button]")
    for i in range(btns.count()):
        b = btns.nth(i)
        if (b.inner_text() or "").strip():
            continue
        bb = b.bounding_box()
        if bb and abs(bb["y"] + bb["height"] / 2 - cy) < 30:
            arrows.append((bb["x"], b))
    arrows.sort(key=lambda a: a[0])
    if len(arrows) < 2:
        return False
    fwd, back = arrows[0][1], arrows[-1][1]  # در راست‌به‌چپ معمولاً فلش چپ = ماه بعد
    for _ in range(30):
        cur = cal_header(dlg)
        if cur is None:
            return False
        if cur == (ty, tm):
            return True
        diff = (ty * 12 + tm) - (cur[0] * 12 + cur[1])
        (fwd if diff > 0 else back).click()
        page.wait_for_timeout(350)
        new = cal_header(dlg)
        if new and new != cur:
            moved = (new[0] * 12 + new[1]) - (cur[0] * 12 + cur[1])
            if (moved > 0) != (diff > 0):
                fwd, back = back, fwd
    return False

def set_schedule(page, slot):
    page.get_by_text("انتخاب زمان انتشار").first.click()
    page.get_by_text("زمان‌بندی انتشار ویدیو").click()
    page.get_by_text("ساعت انتشار").first.wait_for(timeout=15000)
    dlg = page.get_by_text("ساعت انتشار").first.locator(
        "xpath=ancestor::*[.//button[contains(., 'ثبت زمان انتشار')]][1]")
    jd = jdatetime.date.fromgregorian(year=slot.year, month=slot.month, day=slot.day)
    if not goto_month(page, dlg, jd.year, jd.month):
        raise RuntimeError("ماه تقویم پیدا نشد")
    cells = dlg.get_by_text(re.compile(rf"^\s*({jd.day}|{fa(jd.day)})\s*$"))
    cand = []
    for i in range(cells.count()):
        bb = cells.nth(i).bounding_box()
        if bb:
            cand.append((bb["y"], i))
    if not cand:
        raise RuntimeError("روز توی تقویم پیدا نشد")
    cand.sort()
    # روزهای ماه قبل/بعد هم توی شبکه هستن: روزهای ≥۲۰ پایین‌ترین، روزهای کوچک بالاترین
    cells.nth((cand[-1] if jd.day >= 20 else cand[0])[1]).click()
    page.wait_for_timeout(400)
    ins = [i for i in dlg.locator("input").all() if i.is_visible()]
    if len(ins) < 2:
        raise RuntimeError("کادر ساعت و دقیقه پیدا نشد")
    ins.sort(key=lambda e: e.bounding_box()["x"])
    ins[0].fill(f"{slot.hour:02d}")
    ins[1].fill(f"{slot.minute:02d}")
    page.wait_for_timeout(300)
    if to_int(ins[0].input_value()) != slot.hour or to_int(ins[1].input_value()) != slot.minute:
        raise RuntimeError("ساعت درست ثبت نشد")
    dlg.get_by_role("button", name="ثبت زمان انتشار").click()
    page.wait_for_timeout(800)
    return f"{jd.year}/{jd.month:02d}/{jd.day:02d} {slot.hour:02d}:{slot.minute:02d}"

# ---------------- aparat: link ----------------
def find_link(page):
    try:
        extra = page.evaluate("""() => [...document.querySelectorAll('input,textarea')].map(e => e.value || '')
            .concat([...document.querySelectorAll('a[href]')].map(a => a.href))""")
    except Exception:
        extra = []
    txt = "\n".join(extra) + "\n" + page.inner_text("body")
    m = LINK_RE.search(txt)
    return "https://www.aparat.com/v/" + m.group(1) if m else None

# ---------------- main flow ----------------
def process(ctx, idx, total, mid, cid, proc, start_next):
    tag = f"[{idx}/{total}] "
    stage, page, path, cover_path = "download", None, None, None
    try:
        rc = proc.wait()
        start_next()  # دانلود ویدیوی بعدی هم‌زمان با آپلود این یکی
        if rc != 0:
            print("stage failed: download")
            return False  # tg_fetch خودش خطا رو گزارش کرده
        mf = f"meta_{mid}.json"
        with open(mf, encoding="utf-8") as fh:
            meta = json.load(fh)
        os.remove(mf)
        path, caption = meta["path"], meta["caption"]
        notify(f"{tag}⬇️ دانلود شد ({meta['size']/1e6:.0f} MB، {meta['secs']} ثانیه). آپلود شروع شد.")
        if cid:
            cm = fetch_now(cid)
            if cm:
                cover_path = cm["path"]
            else:
                notify(f"{tag}⚠️ کاور دانلود نشد؛ بدون کاور ادامه می‌دم.")
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

        sched_note = ""
        if save_only:
            page.get_by_text("انتخاب زمان انتشار").first.click()
            page.get_by_text("ذخیره و عدم انتشار").click()
            page.wait_for_timeout(800)
        elif SCHED_START and SCHED_STEP:
            stage = "schedule"
            sched_note = set_schedule(page, next_slot(idx - 1))

        stage = "wait upload"
        page.get_by_text("آماده انتشار").first.wait_for(timeout=45 * 60 * 1000)

        cover_note = "—"
        if cover_path:
            stage = "cover"
            try:
                set_cover(page, cover_path)
                cover_note = "✅"
                if idx == 1:
                    notify_photo(page.screenshot(), f"{tag}بررسی کاور")
            except Exception as e:
                cover_note = f"❌ ({type(e).__name__})"

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
        if save_only:
            head = "📝 ذخیره شد (منتشر نشده)"
        elif sched_note:
            head = f"🕒 زمان‌بندی شد برای {sched_note} (وقت تهران)"
        else:
            head = "✅ منتشر شد"
        notify(f"{tag}{head}\n{link}\nعنوان: {fin['title']}\nدسته: {fin['category']}\n"
               f"برچسب‌ها: {'، '.join(fin['tags'])}\nلیست: {pl_note}\nکاور: {cover_note}")
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
        for pth in (path, cover_path):
            if pth and os.path.exists(pth):
                os.remove(pth)

def main():
    start_fetch(ITEMS[0][0])  # دانلود اولی هم‌زمان با لاگین و خوندن لیست‌ها
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(locale="fa-IR", timezone_id="Asia/Tehran",
                                  viewport={"width": 1280, "height": 2200})
        pg = ctx.new_page()
        try:
            login(pg)
        except Exception as e:
            print("stage failed: login")
            msg = (f"❌ لاگین آپارات ناموفق: {type(e).__name__}\n"
                   "اگه ۱۰ دستگاه پر شده، از صفحه‌ی دستگاه‌های آپارات چند تا Linux-WebKit-Chrome رو حذف کن.")
            try:
                notify_photo(pg.screenshot(), msg)
            except Exception:
                notify(msg)
            sys.exit(1)
        pg.close()
        try:
            STATE["playlists"] = read_playlists(ctx)
            full = [t for t, c in STATE["playlists"].items() if c >= PL_MAX]
            notify(f"ℹ️ {len(STATE['playlists'])} لیست پخش خونده شد" + (f" (پر: {len(full)})" if full else ""))
        except Exception as e:
            print("stage failed: playlists")
            notify(f"⚠️ لیست‌های پخش خونده نشد ({type(e).__name__}). ویدیوها بدون لیست آپلود می‌شن.")
        cleanup_devices(ctx)
        ok = 0
        for i, (mid, cid) in enumerate(ITEMS, 1):
            nxt = ITEMS[i][0] if i < len(ITEMS) else None
            start_next = (lambda n=nxt: start_fetch(n)) if nxt is not None else (lambda: None)
            if process(ctx, i, len(ITEMS), mid, cid, procs.pop(mid), start_next):
                ok += 1
        if len(ITEMS) > 1:
            notify(f"پایان: {ok} از {len(ITEMS)} ویدیو موفق")
        browser.close()
        sys.exit(0 if ok == len(ITEMS) else 1)

main()
