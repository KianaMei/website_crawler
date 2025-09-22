import sys
sys.path.append(".")
from fastapi import APIRouter, HTTPException
from ai_news import AiNewsCrawler
from model import NewsResponse


ai_news_router = APIRouter()


@ai_news_router.get("/get_daily_ai_news")
async def get_daily_ai_news() -> NewsResponse:
    """
    获取当日的新闻连播内容
    """
    try:
        # 创建ai新闻爬取机器人
        url = r"https://news.aibase.com/zh/daily"
        ai_news_crawler = AiNewsCrawler(url=url)
        
        # 获取ai新闻内容数据
        daily_news = ai_news_crawler.get_news()
        
        return daily_news
        
    except ValueError as e:
        raise HTTPException(
            status_code=404,
            detail=f"Website url error: {str(e)}"
        )
