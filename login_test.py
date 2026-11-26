import os
from playwright.sync_api import sync_playwright

USER = os.environ["APARAT_USER"]
PASS = os.environ["APARAT_PASS"]

with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(locale="fa-IR", viewport={"width": 1280, "height": 720})
    page = ctx.new_page()
    try:
        page.goto("https://www.aparat.com/login?returnUrl=/reactupload", timeout=45000)
        page.wait_for_timeout(2000)
        page.screenshot(path="1_login.png")

        page.locator("input").first.fill(USER)
        page.get_by_role("button", name="ادامه").click()
        page.wait_for_timeout(3000)
        page.screenshot(path="2_after_continue.png")

        page.locator("input[type=password]").fill(PASS, timeout=15000)
        page.keyboard.press("Enter")
        page.wait_for_timeout(6000)
        page.screenshot(path="3_after_login.png")
        print("after login:", page.url, "|", page.title())

        page.goto("https://www.aparat.com/reactupload", timeout=45000)
        page.wait_for_timeout(4000)
        page.screenshot(path="4_upload_page.png")
        print("upload page:", page.url, "|", page.title())
    except Exception as e:
        print("ERROR:", e)
        page.screenshot(path="error.png")
    finally:
        browser.close()
