import os, re, sys
from playwright.sync_api import sync_playwright

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
    errors = []
    if not data.get("title"): errors.append("عنوان نیست")
    if not data.get("category"): errors.append("دسته نیست")
    if len(data["tags"]) < 3: errors.append("حداقل ۳ برچسب لازمه")
    if len(data.get("description", "")) > 2000: errors.append("توضیحات بیشتر از ۲۰۰۰ کاراکتره")
    if errors:
        sys.exit("CAPTION ERROR: " + " | ".join(errors))
    return data

def shot(page, name):
    page.screenshot(path=f"{name}.png", full_page=True)

def add_tags(page, tags):
    label = page.get_by_text("برچسب‌های ویدیو").first
    add_sel = "button.add-item-btn:visible"
    for i, t in enumerate(tags):
        if page.locator(add_sel).count() == 0:  # لیست بسته شده؛ دوباره باز کن
            label.click()
            page.wait_for_timeout(1000)
        tag_in = page.locator("input[name='searchbar']:visible").last
        tag_in.click()
        tag_in.fill(t)
        page.wait_for_timeout(1500)
        shot(page, f"12_tag{i}_typed")
        page.locator(add_sel).first.click()
        page.wait_for_timeout(1500)
        shot(page, f"12_tag{i}_plus")
        left = tag_in.input_value() if tag_in.count() else ""
        print(f"tag {t!r}: input after + = {left!r}")
        if left:
            tag_in.press("Enter")
            page.wait_for_timeout(1000)
        if i == 0:  # دیباگ: HTML کادر برچسب بعد از اولین افزودن
            try:
                box = label.locator("xpath=ancestor::*[.//input[@name='searchbar']][1]")
                open("tags_after.txt", "w", encoding="utf-8").write(box.evaluate("e => e.outerHTML")[:8000])
            except Exception as e:
                print("dom dump failed:", e)

    page.keyboard.press("Escape")
    page.wait_for_timeout(500)
    errs = page.get_by_text("الزامی").count() + page.get_by_text("اجباری").count()
    print("tags error messages visible:", errs)

def main(video, caption_file):
    d = parse_caption(open(caption_file, encoding="utf-8").read())
    user, pw = os.environ["APARAT_USER"], os.environ["APARAT_PASS"]

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(locale="fa-IR", viewport={"width": 1280, "height": 2200})
        page = ctx.new_page()
        page.on("response", lambda r: print("HTTP", r.request.method, r.status, r.url[:140])
                if ("tag" in r.url.lower() or r.status >= 400) else None)
        try:
            # login
            page.goto("https://www.aparat.com/login?returnUrl=/reactupload", timeout=45000)
            page.locator("input").first.fill(user)
            page.get_by_role("button", name="ادامه").click()
            page.locator("input[type=password]").fill(pw, timeout=15000)
            page.keyboard.press("Enter")
            page.wait_for_url("**/reactupload**", timeout=30000)
            page.wait_for_timeout(3000)

            # file
            page.locator("input[type=file]").first.set_input_files(video)
            page.get_by_placeholder("عنوان ویدیو").wait_for(timeout=60000)

            # title + description
            page.get_by_placeholder("عنوان ویدیو").fill(d["title"])
            if d.get("description"):
                page.get_by_placeholder("توضیحات ویدیو").fill(d["description"])

            # category
            page.get_by_text("دسته‌بندی آپارات").first.click()
            search = page.locator("input[placeholder='جستجو...']:visible").first
            search.fill(d["category"])
            page.wait_for_timeout(800)
            opt = page.get_by_role("option", name=d["category"])
            if opt.count():
                opt.first.click()
            else:
                page.get_by_text(d["category"], exact=True).last.click()
            page.wait_for_timeout(500)

            # tags
            page.get_by_text("برچسب‌های ویدیو").first.click()
            page.wait_for_timeout(1000)
            add_tags(page, d["tags"])
            shot(page, "11_after_tags")

            # publish mode
            save_only = d.get("mode", "").startswith("ذخیره")
            if save_only:
                page.get_by_text("انتخاب زمان انتشار").first.click()
                page.get_by_text("ذخیره و عدم انتشار").click()
                page.wait_for_timeout(800)

            # wait for upload to finish
            for i in range(360):  # up to 30 min
                txt = page.inner_text("body")
                m = re.search(r"([۰-۹0-9]+)\s*٪", txt)
                if not m or m.group(1) in ("۱۰۰", "100"):
                    break
                if i % 12 == 0:
                    print("progress:", m.group(0))
                page.wait_for_timeout(5000)
            shot(page, "13_before_publish")

            # دکمه‌ی نهایی: کنار «انصراف»
            cancel = page.locator("button:has-text('انصراف')").first
            btn = cancel.locator("xpath=..").locator("button").filter(has_not_text="انصراف").first
            print("clicking button:", btn.inner_text())
            btn.click()
            page.wait_for_timeout(10000)
            shot(page, "14_after_publish")
            print("final url:", page.url)
            print("page text:", page.inner_text("body")[:600].replace("\n", " | "))
        except Exception as e:
            print("ERROR:", e)
            shot(page, "error")
            raise
        finally:
            browser.close()

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
