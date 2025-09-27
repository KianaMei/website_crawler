import sys
sys.path.append(".")
from datetime import datetime
from bs4 import BeautifulSoup, Tag
from urllib.parse import urlparse, urlunparse
from typing import Optional, List
import logging

from utils import get_html_from_url
from model import News, NewsResponse

logger = logging.getLogger(__name__)


class AiNewsCrawler:
    def __init__(self, url: str):
        super(AiNewsCrawler, self).__init__()
        self.url = url
    
    def get_base_url(self) -> str:
        """
        从完整URL中提取基础域名部分(协议+域名)
        Return:
            str: 提取后的基础URL, 如https://news.aibase.com
        """
        parsed_url = urlparse(self.url)
        base_url = urlunparse((parsed_url.scheme, parsed_url.netloc, '', '', '', ''))
        return base_url
    
    def get_daily_new_url(self) -> Optional[str]:
        """获取最新一期AI日报的URL"""
        try:
            html_text = get_html_from_url(url=self.url)
            if not html_text:
                logger.error("Failed to fetch index page")
                return None
                
            soup = BeautifulSoup(html_text, "html5lib")
            target_div = soup.find('div', class_="grid grid-cols-1 md:grid-cols-1 md:gap-[16px] gap-[32px] w-full pb-[40px]")
            
            if not target_div:
                logger.error("Daily news container not found")
                return None
                
            daily_a_tag = target_div.find('a')
            if not daily_a_tag or not daily_a_tag.get('href'):
                logger.error("Daily news link not found")
                return None
                
            base_url = self.get_base_url()
            target_url = base_url + daily_a_tag.get('href')
            return target_url
            
        except Exception as e:
            logger.error(f"Error getting daily news URL: {e}")
            return None
    
    def get_news(self) -> NewsResponse:
        """抓取AI新闻并返回标准格式"""
        try:
            target_url = self.get_daily_new_url()
            if not target_url:
                return NewsResponse(
                    news_list=None, 
                    status="ERROR", 
                    err_code="URL_NOT_FOUND", 
                    err_info="Failed to get daily news URL"
                )
                
            html_text = get_html_from_url(url=target_url)
            if not html_text:
                return NewsResponse(
                    news_list=None, 
                    status="ERROR", 
                    err_code="CONTENT_FETCH_FAILED", 
                    err_info="Failed to fetch content from daily news URL"
                )
                
            soup = BeautifulSoup(html_text, "html5lib")
            class_name = 'overflow-hidden space-y-[20px] text-[15px] leading-[25px] break-words mainColor post-content text-wrap'
            target_div = soup.find('div', class_=class_name)
            
            if not target_div:
                return NewsResponse(
                    news_list=None, 
                    status="ERROR", 
                    err_code="CONTENT_CONTAINER_NOT_FOUND", 
                    err_info="Content container div not found"
                )
                
            p_tags = target_div.find_all('p')
            if not p_tags:
                return NewsResponse(
                    news_list=None, 
                    status="ERROR", 
                    err_code="NO_CONTENT_PARAGRAPHS", 
                    err_info="No content paragraphs found"
                )
            
            title, texts, news_lst = "", [], []
            today_str = datetime.strftime(datetime.today(), r"%Y-%m-%d")
            
            for idx, p in enumerate(p_tags):
                if idx == 0 or idx == 1:  # 跳过无用信息
                    continue
                
                # 获取所有直接子标签(仅一级，不包含嵌套标签)
                direct_children = [child for child in p.children if isinstance(child, Tag)]
                
                # 条件1:存在strong标签(标题)
                if direct_children and direct_children[0].name == 'strong':
                    strong_tag = p.find('strong')
                    if strong_tag:
                        # 跳过包含图片的strong标签
                        strong_children = [child for child in strong_tag.children if isinstance(child, Tag)]
                        if strong_children and strong_children[0].name == 'img':
                            continue
                            
                        # 结束上一篇新闻
                        if texts and title:
                            summary = "".join(texts).strip()
                            if summary:  # 只有内容不为空才添加
                                news = News(
                                    title=title, 
                                    url=target_url, 
                                    origin="Aibase", 
                                    summary=summary, 
                                    publish_date=today_str
                                )
                                news_lst.append(news)
                            texts = []  # 清空历史记录
                        
                        title = strong_tag.get_text(strip=True)
                
                # 条件2:普通内容段落
                else:
                    text = p.get_text(strip=True)
                    if text:  # 只添加非空文本
                        texts.append(text)
                
                # 处理最后一个新闻
                if idx == len(p_tags) - 1 and title and texts:
                    summary = "".join(texts).strip()
                    if summary:
                        news = News(
                            title=title, 
                            url=target_url, 
                            origin="Aibase", 
                            summary=summary, 
                            publish_date=today_str
                        )
                        news_lst.append(news)
            
            # 构造最终返回结果
            if news_lst:
                return NewsResponse(news_list=news_lst, status="OK")
            else:
                return NewsResponse(
                    news_list=None, 
                    status="EMPTY", 
                    err_code="NO_NEWS_PARSED", 
                    err_info="No valid news items could be parsed"
                )
                
        except Exception as e:
            logger.error(f"Error in get_news: {e}")
            return NewsResponse(
                news_list=None, 
                status="ERROR", 
                err_code="PARSING_ERROR", 
                err_info=f"Error parsing news: {str(e)}"
            )


if __name__ == '__main__':
    url = r'https://news.aibase.com/zh/daily'
    crawler = AiNewsCrawler(url=url)
    print(crawler.get_daily_new_url())
    print(crawler.get_news())
