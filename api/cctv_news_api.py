import sys
sys.path.append(".")
from fastapi import APIRouter, HTTPException
from cctv_news import CCTVNewsCrawler
from model import NewsResponse


cctv_news_router = APIRouter()


@cctv_news_router.get("/get_daily_cctv_news")
async def get_daily_cctv_news() -> NewsResponse:
    """
    获取n-1日的新闻连播内容
    """
    try:
        # 创建新闻联播爬取机器人
        url = r"https://tv.cctv.com/lm/xwlb/index.shtml"
        cctv_news_crawler = CCTVNewsCrawler(url=url)
        
        # 获取新闻联播内容数据
        daily_news = cctv_news_crawler.get_news()
        
        return daily_news
        
    except ValueError as e:
        raise HTTPException(
            status_code=404,
            detail=f"Website url error: {str(e)}"
        )
