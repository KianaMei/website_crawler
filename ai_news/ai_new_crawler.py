import sys
sys.path.append(".")
from datetime import datetime
from bs4 import BeautifulSoup, Tag
from urllib.parse import urlparse, urlunparse

from utils import get_html_from_url
from model import News, NewsResponse


class AiNewsCrawler:
    def __init__(self, 
                 url: str):
        super(AiNewsCrawler, self).__init__()
        self.url = url
    
    def get_base_url(self):
        """
        从完整URL中提取基础域名部分(协议+域名)
        Return:
            str: 提取后的基础URL, 如https://news.aibase.com
        """
        # 解析URL
        parsed_url = urlparse(self.url)
        # 组合协议和域名部分
        base_url = urlunparse((parsed_url.scheme, parsed_url.netloc, '', '', '', ''))
    
        return base_url
    
    def get_daily_new_url(self):
        html_text = get_html_from_url(url=self.url)
        soup = BeautifulSoup(html_text.encode('utf-8'), "html5lib")  # type: ignore
        # 通过class锚定目标div
        target_div = soup.find('div', class_="grid grid-cols-1 md:grid-cols-1 md:gap-[16px] gap-[32px] w-full pb-[40px]")
        # 获取目标div下的跳转链接，这些链接是按照时间顺序倒序排序，选择第一个链接作为今日推送
        daily_a_tag = target_div.find('a') # type: ignore
        base_url = self.get_base_url()
        target_url = base_url + daily_a_tag.get('href', None) # type: ignore
        return target_url
    
    def get_news(self) -> NewsResponse:
        target_url = self.get_daily_new_url()
        html_text = get_html_from_url(url=target_url)
        soup = BeautifulSoup(html_text.encode('utf-8'), "html5lib")  # type: ignore
        # 通过class锚定目标div
        class_name = 'overflow-hidden space-y-[20px] text-[15px] leading-[25px] break-words mainColor post-content text-wrap'
        target_div = soup.find('div', class_=class_name)
        # 搜集所有p标签, 根据规则筛选重要文本内容
        p_tags = target_div.find_all('p') # type: ignore
        
        title, texts, news_lst = "", [], []
        for idx, p in enumerate(p_tags):
            if idx == 0 or idx == 1: # 跳过无用信息
                continue
            
            # 获取所有直接子标签(仅一级，不包含嵌套标签)
            direct_children = [child for child in p.children if isinstance(child, Tag)] # type: ignore
            # 条件1:仅存在一个strong标签
            if len(direct_children) > 0 and direct_children[0].name == 'strong': # type: ignore
                strong_tag = p.find('strong') # type: ignore
                strong_direct_children = [child for child in strong_tag.children if isinstance(child, Tag)] # type: ignore
                if len(strong_direct_children) > 0 and strong_direct_children[0].name == 'img': # 跳过图片
                    continue
                if len(texts) > 0:
                    # 结束上一篇新闻
                    summary = "".join(texts)
                    texts = [] # 清空历史记录
                    today_str = datetime.strftime(datetime.today(), r"%Y-%m-%d")
                    news = News(title=title, url=target_url, origin="Aibase", summary=summary, publish_date=today_str)
                    news_lst.append(news)
                title = strong_tag.get_text(strip=True) # type: ignore
            # 条件2:没有子标签
            else:
                text = p.get_text(strip=True) # type: ignore
                texts.append(text)
            
            if idx == len(p_tags)-1:
                # 手动回收最后一个新闻
                summary = "".join(texts)
                today_str = datetime.strftime(datetime.today(), r"%Y-%m-%d")
                news = News(title=title, url=target_url, origin="Aibase", summary=summary, publish_date=today_str)
                news_lst.append(news)
        
        # 构造最终返回结果 简要和详细内容
        result = NewsResponse(news_list=news_lst)
        return result


if __name__ == '__main__':
    url = r'https://news.aibase.com/zh/daily'
    crawler = AiNewsCrawler(url=url)
    print(crawler.get_daily_new_url())
    print(crawler.get_news())
