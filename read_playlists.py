import os, sys, urllib.parse, urllib.request
from playwright.sync_api import sync_playwright

USER = os.environ["APARAT_USER"]
PASS = os.environ["APARAT_PASS"]
TOKEN = os.environ["TG_BOT_TOKEN"]
OWNER = os.environ["TG_OWNER_ID"]

def notify(text):
    data = urllib.parse.urlencode({"chat_id": OWNER, "text": text[:4000]}).encode()
    try:
        urllib.request.urlopen(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data, timeout=20).read()
    except Exception:
        print("notify failed")

def main():
    stage = "login"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(locale="fa-IR", viewport={"width": 1280, "height": 1200})
        page = ctx.new_page()
        try:
            page.goto("https://www.aparat.com/login?returnUrl=/reactupload", timeout=45000)
            page.locator("input").first.fill(USER)
            page.get_by_role("button", name="ادامه").click()
            page.locator("input[type=password]").fill(PASS, timeout=15000)
            page.keyboard.press("Enter")
            page.wait_for_url("**/reactupload**", timeout=30000)
            page.wait_for_timeout(2000)

            stage = "open playlists"
            page.goto("https://www.aparat.com/dashboard/myvideos/playlist", timeout=45000)
            page.wait_for_timeout(4000)

            stage = "scroll"
            last, same = -1, 0
            for _ in range(40):
                page.mouse.wheel(0, 3000)
                page.keyboard.press("End")
                page.wait_for_timeout(1200)
                n = len(page.inner_text("body"))
                same = same + 1 if n == last else 0
                last = n
                if same >= 3:
                    break

            stage = "report"
            txt = page.inner_text("body")
            notify(f"طول متن صفحه: {len(txt)} | تعداد «عمومی»: {txt.count('عمومی')}")
            notify("ابتدای متن:\n" + txt[:3000])
            notify("انتهای متن:\n" + txt[-1500:])
            try:
                card = page.get_by_text("عمومی").first.locator("xpath=ancestor::*[.//img][1]")
                notify("HTML اولین کارت:\n" + card.evaluate("e => e.outerHTML")[:3500])
            except Exception as e:
                notify("HTML کارت پیدا نشد: " + type(e).__name__)
            print("stage: report ok")
        except Exception as e:
            print("stage failed:", stage)
            notify(f"❌ خطا در مرحله‌ی «{stage}»: {type(e).__name__}: {str(e)[:300]}")
            sys.exit(1)
        finally:
            browser.close()

main()
