import sys
import asyncio
sys.path.append(".")
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

from utils import get_html_from_url, get_few_days_ago, join_urls
from model import News, NewsResponse


class CommerceNewsCrawler:
    def __init__(self, url: str):
        super(CommerceNewsCrawler, self).__init__()
        self.url = url

    async def get_news_url_dict(self, child_url):
        url = join_urls(self.url, child_url=child_url)
        few_days = get_few_days_ago(day_offset=4)
        news_url_dict = {}
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            try:
                await page.goto(url, wait_until="networkidle")
                ul_selector = "ul.txtList_01"
                await page.wait_for_selector(ul_selector, timeout=10000)
                li_selector = f"{ul_selector} > li"
                li_elements = await page.query_selector_all(li_selector)
                for li in li_elements:
                    a_tag = await li.query_selector("a")
                    span_tag = await li.query_selector("> span")
                    if not a_tag or not span_tag:
                        continue
                    href = await a_tag.get_attribute("href") or None
                    title = await a_tag.get_attribute("title") or None
                    date_text = await span_tag.text_content()
                    date = date_text.strip()[1:-1] if date_text else None
                    if date not in few_days:
                        continue
                    news_title = f"{title};{date}"
                    final_url = join_urls(self.url, child_url=href)
                    news_url_dict[news_title] = final_url
                return news_url_dict
            except Exception as e:
                print(f"获取过程出错: {str(e)}")
                return {}
            finally:
                await browser.close()

    async def get_news(self) -> NewsResponse:
        ldrhd_task = self.get_news_url_dict(child_url=r'xwfb/ldrhd/index.html')
        bldhd_task = self.get_news_url_dict(child_url=r'xwfb/bldhd/index.html')
        results = await asyncio.gather(ldrhd_task, bldhd_task)
        
        merged = {**results[0], **results[1]}
        news_lst = []
        for title, url in merged.items():
            # 使用现有同步方法获取HTML，因为API路由是async，但get_html_from_url是sync
            html_text = get_html_from_url(url=url)
            if not html_text:
                continue
            soup = BeautifulSoup(html_text.encode('utf-8'), "html5lib")
            div = soup.find('div', class_='art-con art-con-bottonmLine')
            if not div:
                continue
            p_tags = div.find_all('p')
            text = "".join([p.get_text(strip=True) for p in p_tags])
            title_part, publish_date = title.split(";")
            news_lst.append(News(title=title_part,
                                 url=url,
                                 origin='商务部',
                                 summary=text,
                                 publish_date=publish_date))
        return NewsResponse(news_list=news_lst)


async def main():
    url = r'https://www.mofcom.gov.cn/'
    crawler = CommerceNewsCrawler(url=url)
    news_response = await crawler.get_news()
    print(news_response)

if __name__ == '__main__':
    asyncio.run(main())
