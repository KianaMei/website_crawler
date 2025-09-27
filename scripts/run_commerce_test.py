import asyncio
from gov_news.commerce_news_crawler import CommerceNewsCrawler


async def main() -> None:
    crawler = CommerceNewsCrawler(url="https://www.mofcom.gov.cn/")
    resp = await crawler.get_news()
    news_list = resp.news_list or []
    print("count", len(news_list))
    for idx, item in enumerate(news_list[:5], start=1):
        print(idx, item.title, item.url)


if __name__ == "__main__":
    asyncio.run(main())


