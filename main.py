from fastapi import FastAPI
from api import (
    cctv_news_router,
    ai_news_router,
    paper_news_router,
    gov_news_router,
    assoc_chamber_router,
)


tags_metadata = [
    {"name": "CCTV 新闻", "description": "央视新闻联播摘要抓取"},
    {"name": "AI 新闻", "description": "Aibase 每日 AI 动态"},
    {"name": "纸媒新闻", "description": "人日报/光明日报/经济日报/求是/新华/经济参考报"},
    {"name": "政府新闻", "description": "国家发改委/交通运输部/商务部等"},
    {"name": "行业/协会", "description": "全国工商联/CFLP/ChinaISA 等"},
]

app = FastAPI(
    title="网站采集聚合 API",
    description="统一抓取 CCTV/AI/纸媒/政府/行业协会 等来源，统一 NewsResponse",
    version="0.1.0",
    openapi_tags=tags_metadata,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    swagger_ui_parameters={
        "defaultModelsExpandDepth": -1,
        "docExpansion": "none",
        "displayRequestDuration": True,
    },
)

# 注册路由（并集）
app.include_router(cctv_news_router, prefix="/api", tags=["CCTV 新闻"])
app.include_router(ai_news_router, prefix="/api", tags=["AI 新闻"])
app.include_router(paper_news_router, prefix="/api", tags=["纸媒新闻"])
app.include_router(gov_news_router, prefix="/api", tags=["政府新闻"])
app.include_router(assoc_chamber_router, prefix="/api", tags=["行业/协会"])

