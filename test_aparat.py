from playwright.sync_api import sync_playwright

pages = {
    "home": "https://www.aparat.com/",
    "login": "https://www.aparat.com/signin",
    "upload": "https://www.aparat.com/upload",
}

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    for name, url in pages.items():
        try:
            r = page.goto(url, timeout=45000)
            print(name, r.status if r else None, page.title())
        except Exception as e:
            print(name, "ERROR", e)
        page.screenshot(path=f"{name}.png")
    browser.close()
