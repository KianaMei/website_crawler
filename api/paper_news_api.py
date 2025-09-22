"""纸媒新闻 API 路由。"""
from fastapi import APIRouter, HTTPException, Query
from paper_news.paper_news_crawler import PaperNewsCrawler
from model import NewsResponse

paper_news_router = APIRouter()

@paper_news_router.get(
    "/get_daily_paper_news",
    response_model=NewsResponse,
    summary="获取纸媒新闻（可指定日期）",
    description=(
        "从指定来源抓取某日期（默认最近一期），并提取标题与摘要。\n"
        "支持：人民日报(peopledaily)/光明日报(guangming)/经济日报(economic)/求是(qiushi)/"
        "新华每日电讯(xinhua)/经济参考报(jjckb)。"
    ),
    responses={
        200: {
            "description": "成功",
            "content": {
                "application/json": {
                    "example": {
                        "status": "OK",
                        "news_list": [
                            {
                                "title": "高质量发展迈出新步伐",
                                "url": "http://paper.people.com.cn/...",
                                "origin": "人民日报",
                                "summary": "摘要内容……",
                                "publish_date": "2025-09-19",
                            }
                        ],
                        "err_code": None,
                        "err_info": None,
                    }
                }
            },
        },
        500: {"description": "抓取失败，请查看 err_code/err_info"},
    },
)
async def get_daily_paper_news(
    source: str = Query(default='peopledaily', description='peopledaily|guangming|economic|qiushi|xinhua|jjckb'),
    max_items: int = Query(default=10, ge=1, le=50),
    date: str | None = Query(default=None, description='指定日期 YYYY-MM-DD（为空将自动选择最近一期）'),
) -> NewsResponse:
    """若未提供 `date`，将自动定位最近一期。"""
    crawler = PaperNewsCrawler(source=source, max_items=max_items, date=date)
    resp = crawler.get_news()
    if resp.status != 'OK' or resp.news_list is None:
        raise HTTPException(status_code=500, detail=f"纸媒抓取失败: {resp.err_code or ''} {resp.err_info or ''}")
    return resp
