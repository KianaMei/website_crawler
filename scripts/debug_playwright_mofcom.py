import asyncio
import sys
from playwright.async_api import async_playwright


async def visit_and_dump(url: str, out):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            page.set_default_timeout(15000)
            page.set_default_navigation_timeout(15000)
        except Exception:
            pass
        try:
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_selector("ul.txtList_01", timeout=10000)
            lis = await page.query_selector_all("ul.txtList_01 > li")
            print(f"[OK] {url} li_count={len(lis)}", file=out, flush=True)
            for li in lis[:5]:
                a = await li.query_selector("a")
                span = await li.query_selector("> span")
                href = await a.get_attribute("href") if a else ""
                title = await a.get_attribute("title") if a else ""
                date_text = await span.text_content() if span else ""
                print("-", (title or "").strip(), (href or "").strip(), (date_text or "").strip(), file=out, flush=True)
        except Exception as e:
            print(f"[ERR] {url} {e}", file=out, flush=True)
        finally:
            await browser.close()


async def main() -> None:
    base = "https://www.mofcom.gov.cn/"
    with open("tmp_mofcom_debug.log", "w", encoding="utf-8") as out:
        for child in ("xwfb/ldrhd/index.html", "xwfb/bldhd/index.html"):
            await visit_and_dump(base + child, out)
        out.flush()


if __name__ == "__main__":
    asyncio.run(main())


