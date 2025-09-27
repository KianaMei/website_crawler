import sys
sys.path.append(".")
from fastapi import APIRouter, HTTPException
from ai_news import AiNewsCrawler
from model import NewsResponse


ai_news_router = APIRouter()


@ai_news_router.get("/get_daily_ai_news")
async def get_daily_ai_news() -> NewsResponse:
    """
    获取当日的AI新闻资讯
    """
    try:
        # 创建ai新闻爬取机器人
        url = r"https://news.aibase.com/zh/daily"
        ai_news_crawler = AiNewsCrawler(url=url)
        
        # 获取ai新闻内容数据
        daily_news = ai_news_crawler.get_news()
        
        # 如果爬虫返回ERROR状态，转换为HTTP异常
        if daily_news.status == "ERROR":
            raise HTTPException(
                status_code=500,
                detail=f"Crawling failed: {daily_news.err_info or daily_news.err_code}"
            )
        
        return daily_news
        
    except HTTPException:
        raise  # 重新抛出HTTP异常
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )
