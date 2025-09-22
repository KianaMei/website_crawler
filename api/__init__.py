from .ai_news_api import ai_news_router
from .cctv_news_api import cctv_news_router
from .paper_news_api import paper_news_router
from .gov_news_api import gov_news_router
from .assoc_chamber_api import assoc_chamber_router

__all__ = [
    "ai_news_router",
    "cctv_news_router",
    "paper_news_router",
    "gov_news_router",
    "assoc_chamber_router",
]

