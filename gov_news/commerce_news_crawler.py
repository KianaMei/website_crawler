import sys
sys.path.append(".")
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

from utils import get_html_from_url, get_few_days_ago, join_urls
from model import News, NewsResponse


class CommerceNewsCrawler:
    def __init__(self, 
                 url: str):
        super(CommerceNewsCrawler, self).__init__()
        self.url = url
    
    def get_news_url_dict(self, child_url):
        url = join_urls(self.url, child_url=child_url)
        few_days = get_few_days_ago(day_offset=4)
        news_url_dict = {}
        with sync_playwright() as p:
            # 启动浏览器（可选chromium、firefox、webkit）
            browser = p.chromium.launch(headless=False)  # headless=True表示无头模式（无界面）
            page = browser.new_page()
            
            try:
                # 访问页面并等待JS渲染完成
                page.goto(url, wait_until="networkidle")  # 等待网络空闲，确保JS渲染完成
            
                # 定位class为"txtList_01"的ul标签
                ul_selector = "ul.txtList_01"
            
                # 等待ul元素出现（防止页面加载慢导致元素未渲染）
                page.wait_for_selector(ul_selector, timeout=1000)  # 超时3秒
            
                # 获取ul下的所有li标签
                li_selector = f"{ul_selector} > li"  # 直接子元素li
            
                # 获取所有li元素
                li_elements = page.query_selector_all(li_selector)
            
                # 提取每个li标签下的url title date
                for li in li_elements:
                    a_tag = li.query_selector("a")  # 查找li下的第一个a标签
                    span_tag = li.query_selector("> span")  # 仅查找直接子span
                    if not a_tag or not span_tag:
                        continue
                    # 提取a标签的href和title
                    href = a_tag.get_attribute("href") or None
                    title = a_tag.get_attribute("title") or None
                    date = span_tag.text_content().strip()[1:-1] or None # type: ignore
                    if date not in few_days:
                        # 跳过超过时效的新闻
                        continue
                    news_title = f"{title};{date}"
                    final_url = join_urls(self.url, child_url=href)
                    news_url_dict[news_title] = final_url
            
                return news_url_dict
        
            except Exception as e:
                print(f"获取过程出错: {str(e)}")
                return {}
        
            finally:
                # 确保浏览器关闭
                browser.close()

    def get_news(self):
        ldrhd_news_url_dict = self.get_news_url_dict(child_url=r'xwfb/ldrhd/index.html')
        bldhd_news_url_dict = self.get_news_url_dict(child_url=r'xwfb/bldhd/index.html')
        merged = {** ldrhd_news_url_dict, **bldhd_news_url_dict}
        news_lst = []
        for title, url in merged.items():
            html_text = get_html_from_url(url=url)
            soup = BeautifulSoup(html_text.encode('utf-8'), "html5lib")  # type: ignore
            # TODO 获取文章内容的逻辑
            div = soup.find('div', class_='art-con art-con-bottonmLine')
            p_tags = div.find_all('p', style='text-align: justify; text-indent: 2em;') # type: ignore
            text = "".join([p.get_text(strip=True) for p in p_tags])
            title, publish_date = title.split(";")
            news_lst.append(News(title=title, 
                                 url=url,
                                 origin='商务部', 
                                 summary=text, 
                                 publish_date=publish_date))
        return NewsResponse(news_list=news_lst)

if __name__ == '__main__':
    url = r'https://www.mofcom.gov.cn/'
    crawler = CommerceNewsCrawler(url=url)
    print(crawler.get_news())
