from playwright.sync_api import sync_playwright

pages = {
    "home": "https://www.aparat.com/",
    "login": "https://www.aparat.com/login?returnUrl=/reactupload",
    "upload": "https://www.aparat.com/reactupload",
}

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    for name, url in pages.items():
        try:
            r = page.goto(url, timeout=45000, wait_until="load")
            page.wait_for_timeout(3000)
            print(name, "status:", r.status if r else None, "| final url:", page.url, "| title:", page.title())
        except Exception as e:
            print(name, "ERROR", e)
        page.screenshot(path=f"{name}.png")
    browser.close()
