import sys
sys.path.append(".")
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

from utils import get_html_from_url
from model import News, NewsResponse


class CCTVNewsCrawler:
    def __init__(self, 
                 url: str):
        super(CCTVNewsCrawler, self).__init__()
        self.url = url
    
    def get_news_dict(self):
        html_text = get_html_from_url(url=self.url)
        soup = BeautifulSoup(html_text.encode('utf-8'), "html5lib")  # type: ignore
        # 获取汇总新闻要点的ul标签
        ul_tag = soup.find('ul', id='content')
        # 遍历ul标签中的每个li标签，同时解析li标签内a标签的href和title字段
        li_tags = ul_tag.find_all('li') # type: ignore
        news_dict = {}
        for idx, li_tag in enumerate(li_tags):
            # 跳过第一个视频链接
            if idx == 0:
                continue
            a_tag = li_tag.find('a') # type: ignore
            # 获取新闻详细内容的url
            href = a_tag.get('href', None) # type: ignore
            # 获取新闻标题，处理后作为新闻内容摘要
            title = a_tag.get('title', None)[4:] # type: ignore
            news_dict[title] = href
        return news_dict
    
    def get_news(self):
        """
        基于主页面ul标签解析结果, 获取每个子新闻的详情
        汇总新闻摘要和新闻详情, 转化为形成api输出类
        """
        news_dict = self.get_news_dict()
        news_list = []
        for title, url in news_dict.items():
            child_html_text = get_html_from_url(url=url)
            child_soup = BeautifulSoup(child_html_text.encode('utf-8'), "html5lib") # type: ignore
            content_div_tag = child_soup.find('div', class_="content_area")
            p_tags = content_div_tag.find_all('p') # type: ignore
            child_content = ""
            for p_tag in p_tags:
                child_content += p_tag.get_text(strip=True)
            # 新闻联播时间是t-1
            today = datetime.today()
            yesterday = today - timedelta(days=1)
            yesterday_str = datetime.strftime(yesterday, r"%Y-%m-%d")
            news = News(title=title, 
                        url=url, 
                        origin='新闻联播', 
                        summary=child_content, 
                        publish_date=yesterday_str)
            news_list.append(news)
        result = NewsResponse(news_list=news_list)
        return result


if __name__ == "__main__":
    url = r"https://tv.cctv.com/lm/xwlb/index.shtml"
    crawler = CCTVNewsCrawler(url=url)
    results = crawler.get_news()
    print(results)
