"""政府新闻 API 路由（并集融合）"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List
from model import NewsResponse
from model.enums import NDRCCategory
from api.param_parsers import parse_multi_select

# Crawlers from both codebases
from gov_news.ndrc_news_crawler import NDRCNewsCrawler
from gov_news.transport_news_crawler import TransportNewsCrawler
from gov_news.commerce_news_crawler import CommerceNewsCrawler


gov_news_router = APIRouter()


# 发改委（NDRC）- 来自 main
@gov_news_router.get(
    "/get_daily_ndrc_news",
    response_model=NewsResponse,
    summary="获取国家发改委要闻/规范/通知等（可选分类）",
    description=(
        "抓取国家发改委多分类内容，统一为 NewsResponse。\n"
        "支持 CSV 与重复参数两种写法，可选: fzggwl(综合), ghxwj(规范性文件), ghwb(规划文本), gg(公告), tz(通知)。"
    ),
    responses={
        200: {"description": "成功"},
        400: {"description": "请求参数不合法"},
        500: {"description": "抓取失败"},
    },
)
async def get_daily_ndrc_news(
    categories_raw: Optional[List[str]] = Query(None, alias='categories', description='支持 CSV 与重复参数；可选 fzggwl ghxwj ghwb gg tz'),
    max_pages: int = Query(default=1, ge=1, le=10),
    max_items: int = Query(default=10, ge=1, le=100),
) -> NewsResponse:
    try:
        cats = parse_multi_select(categories_raw, NDRCCategory, 'categories', ['fzggwl'])
        crawler = NDRCNewsCrawler(categories=cats or None, max_pages=max_pages, max_items=max_items)
        resp = crawler.get_news()
        if resp.status != 'OK' or resp.news_list is None:
            raise HTTPException(status_code=500, detail=f"发改委抓取失败: {resp.err_code or ''} {resp.err_info or ''}")
        return resp
    except HTTPException:
        # 重新抛出参数解析错误（已在 parse_multi_select 中处理）
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"请求参数不合法: {e}")


# 交通运输部（MOT）- 来自 wait
@gov_news_router.get(
    "/get_transport_gov_news",
    response_model=NewsResponse,
    summary="获取交通运输部要闻（近 N 天）",
    responses={
        200: {"description": "成功"},
        404: {"description": "网站 URL 错误"},
        500: {"description": "抓取失败"},
    },
)
async def get_transport_gov_news() -> NewsResponse:
    try:
        url = r'https://www.mot.gov.cn/jiaotongyaowen/'
        transport_gov_news_crawler = TransportNewsCrawler(url=url)
        return transport_gov_news_crawler.get_news()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=f"Website url error: {str(e)}")


# 商务部（MOFCOM）- 来自 wait
@gov_news_router.get(
    "/get_commerce_gov_news",
    response_model=NewsResponse,
    summary="获取商务部要闻（近 N 天）",
    responses={
        200: {"description": "成功"},
        404: {"description": "网站 URL 错误"},
        500: {"description": "抓取失败"},
    },
)
async def get_commerce_gov_news() -> NewsResponse:
    try:
        url = r'https://www.mofcom.gov.cn/'
        commerce_gov_news_crawler = CommerceNewsCrawler(url=url)
        return commerce_gov_news_crawler.get_news()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=f"Website url error: {str(e)}")

