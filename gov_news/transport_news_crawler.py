import sys
sys.path.append(".")
from bs4 import BeautifulSoup

from utils import get_html_from_url, get_few_days_ago, join_urls
from model import News, NewsResponse


class TransportNewsCrawler:
    def __init__(self, 
                 url: str):
        super(TransportNewsCrawler, self).__init__()
        self.url = url
    
    def get_target_div(self):
        html_text = get_html_from_url(url=self.url)
        soup = BeautifulSoup(html_text.encode('utf-8'), "html5lib")  # type: ignore
        # 依据class信息获取汇总新闻的div标签
        div = soup.find('div', class_='list-group tab-content')
        # 获取div下所有的分段栏目
        div_groups = div.find_all('div')  # type: ignore
        return div_groups
    
    def get_news_url_dict(self):
        div_groups = self.get_target_div()
        if not div_groups:
            # 没有找到目标div
            return {}
        few_days = get_few_days_ago(day_offset=2)
        news_url_dict = {}
        for div in div_groups:
            a_tag_list = div.find_all('a', class_='list-group-item') # type: ignore
            for a_tag in a_tag_list:
                # 获取新闻链接的发布日期
                # for child in a_tag.children: # type: ignore
                #     print(child)
                span_tag = a_tag.find('span', class_='badge') # type: ignore
                date = span_tag.get_text(strip=True)  # type: ignore
                if date not in few_days:
                    # 日期不在检索范围内则跳过
                    continue
                href = a_tag.get('href', None) # type: ignore
                title = a_tag.get('title', None) # type: ignore
                if not href or not title:
                    # 跳过没有链接或没有标题的a标签
                    continue
                url = join_urls(self.url, href)
                # 标题附上日期信息
                title = f"{title};{date}"
                news_url_dict[title] = url
        return news_url_dict
    
    def get_news(self):
        news_url_dict = self.get_news_url_dict()
        news_lst = []
        for title, url in news_url_dict.items():
            html_text = get_html_from_url(url=url)
            soup = BeautifulSoup(html_text.encode('utf-8'), "html5lib")  # type: ignore
            # 获取文章内容所在的div
            div = soup.find('div', id='Zoom')
            # 定位包含文章段落的span标签
            span_tags = div.find_all('span', style='line-height: 2em;') # type: ignore
            text = "".join([span_tag.get_text(strip=True) for span_tag in span_tags])
            title, publish_date = title.split(";")
            news_lst.append(News(title=title, 
                                 url=url,
                                 origin='交通部', 
                                 summary=text, 
                                 publish_date=publish_date))
        return NewsResponse(news_list=news_lst)


if __name__ == '__main__':
    url = r'https://www.mot.gov.cn/jiaotongyaowen/'
    crawler = TransportNewsCrawler(url=url)
    print(crawler.get_news())
