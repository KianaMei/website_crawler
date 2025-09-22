"""协会/商会相关 API 路由。"""
from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from AssocChamber import ACFICPolicyCrawler, CFLPNewsCrawler, ChinaISACrawler
from AssocChamber.chinaisa_crawler import CHINAISA_COLUMNS
from model import NewsResponse, News


assoc_chamber_router = APIRouter()


@assoc_chamber_router.get(
    "/get_acfic_policies",
    response_model=NewsResponse,
    summary="获取全联政策信息（多频道）",
    description="抓取 中央/部委/地方/全联/解读 的政策信息，并统一为 NewsResponse",
    responses={
        200: {"description": "成功"},
        500: {"description": "抓取失败"},
    },
)
async def get_acfic_policies(
    channels: str = Query(default='zy,bw,df,qggsl,jd', description='频道 CSV: zy,bw,df,qggsl,jd'),
    max_pages: int = Query(default=1, ge=1, le=10),
    max_items: int = Query(default=5, ge=1, le=100),
) -> NewsResponse:
    """抓取全联相关部门政策信息，统一返回 NewsResponse。"""
    chs = [s.strip() for s in channels.split(',') if s.strip()]
    crawler = ACFICPolicyCrawler(channels=chs or None, max_pages=max_pages, max_items=max_items)
    resp = crawler.get_news()
    if resp.status != 'OK' or resp.news_list is None:
        raise HTTPException(status_code=500, detail=f"ACFIC 抓取失败: {resp.err_code or ''} {resp.err_info or ''}")
    origin_map = {
        'ACFIC-Central': '全联政策-中央',
        'ACFIC-Ministries': '全联政策-部委',
        'ACFIC-Local': '全联政策-地方',
        'ACFIC': '全联政策',
        'ACFIC-Interpretation': '全联政策-解读',
    }
    localized_list = [
        News(
            title=n.title,
            url=n.url,
            origin=origin_map.get(n.origin, n.origin),
            summary=n.summary,
            publish_date=n.publish_date,
        ) for n in (resp.news_list or [])
    ]
    return NewsResponse(news_list=localized_list, status=resp.status, err_code=resp.err_code, err_info=resp.err_info)


@assoc_chamber_router.get(
    "/get_cflp_news",
    response_model=NewsResponse,
    summary="获取中国物流与采购联合会（CFLP）的政策/资讯",
    description=(
        "支持 channels=zcfg(政策法规),zixun(资讯)，since_days 限制近 N 天（默认 7 天）"
    ),
    responses={
        200: {"description": "成功"},
        500: {"description": "抓取失败"},
    },
)
async def get_cflp_news(
    channels: str = Query(default='zcfg,zixun', description='频道 CSV: zcfg,zixun'),
    max_pages: int = Query(default=1, ge=1, le=10),
    max_items: int = Query(default=8, ge=1, le=100),
    since_days: int = Query(default=7, ge=1, le=60, description='近 N 天的数据，遇到分页前停止'),
) -> NewsResponse:
    """抓取 CFLP 政策/资讯并统一返回 NewsResponse。"""
    chs = [s.strip() for s in channels.split(',') if s.strip()]
    mapped = ['zixun' if c == 'dzsp' else c for c in chs] or None
    crawler = CFLPNewsCrawler(channels=mapped, max_pages=max_pages, max_items=max_items, since_days=since_days)
    resp = crawler.get_news()
    if resp.status != 'OK' or resp.news_list is None:
        raise HTTPException(status_code=500, detail=f"CFLP 抓取失败: {resp.err_code or ''} {resp.err_info or ''}")
    origin_map = {
        'CFLP-Policy': '中国物流与采购联合会-政策法规',
        'CFLP-News': '中国物流与采购联合会-资讯',
        'CFLP-News-Electronics': '中国物流与采购联合会-资讯-电子/装备',
    }
    localized_list = [
        News(
            title=n.title,
            url=n.url,
            origin=origin_map.get(n.origin, n.origin),
            summary=n.summary,
            publish_date=n.publish_date,
        ) for n in (resp.news_list or [])
    ]
    return NewsResponse(news_list=localized_list, status=resp.status, err_code=resp.err_code, err_info=resp.err_info)


# ---------------- ChinaISA: 路由 ----------------

@assoc_chamber_router.get(
    "/chinaisa/news",
    response_model=NewsResponse,
    summary="中国钢铁工业协会-新闻抓取",
    description=(
        "columns 为 columnId 的 CSV（为空使用默认 8 个栏目）；"
        "支持 page/size/max/since_days/max_pages 等参数"
    ),
)
async def chinaisa_news(
    columns: str = Query(default='', description='栏目 columnId CSV，空则使用默认'),
    page: int = Query(default=1, ge=1, le=50),
    size: int = Query(default=20, ge=1, le=100),
    max: int = Query(default=60, ge=1, le=1000),
    since_days: int | None = Query(default=None, ge=1, le=60),
    max_pages: int = Query(default=3, ge=1, le=10),
    include_subtabs: bool = Query(default=True, description='是否包含子栏目（统计分析/行业信息/价格指数等）'),
) -> NewsResponse:
    cids = [s.strip() for s in columns.split(',') if s.strip()] or None
    crawler = ChinaISACrawler(
        column_ids=cids,
        page_no=page,
        page_size=size,
        max_items=max,
        since_days=since_days,
        max_pages=max_pages,
        include_subtabs=include_subtabs,
    )
    resp = crawler.get_news()
    if resp.status != 'OK' or resp.news_list is None:
        raise HTTPException(status_code=500, detail=f"ChinaISA 抓取失败: {resp.err_code or ''} {resp.err_info or ''}")
    return resp


@assoc_chamber_router.get(
    "/chinaisa/sections",
    summary="中国钢铁工业协会-栏目结构与映射",
    description=(
        "返回栏目与子栏目结构，提供 baseline_subtabs（基线映射）与 subtabs（实时检测），并标注 added/missing"
    ),
)
async def chinaisa_sections(include_subtabs: bool = Query(default=True)):
    cr = ChinaISACrawler()
    sections = await run_in_threadpool(cr.get_sections, include_subtabs)
    # 简要提取重要分组，供前端使用
    groups_keys = [
        '2e3c87064bdfc0e43d542d87fce8bcbc8fe0463d5a3da04d7e11b4c7d692194b',
        '1b4316d9238e09c735365896c8e4f677a3234e8363e5622ae6e79a5900a76f56',
        '17b6a9a214c94ccc28e56d4d1a2dbb5acef3e73da431ddc0a849a4dcfc487d04',
    ]
    groups = []
    for pid in groups_keys:
        if pid in sections:
            g = sections[pid].copy()
            g['id'] = pid
            groups.append(g)
    return {"sections": sections, "groups": groups}


# --- 已按要求停用：chinaisa/sample ---
# @assoc_chamber_router.get(
#     "/chinaisa/sample",
#     summary="中国钢铁工业协会-各栏目样例抓取",
#     description="针对默认 8 个栏目各抓取少量记录用于快速查看",
# )
# async def chinaisa_sample(size: int = Query(default=3, ge=1, le=10)):
#     results = []
#     for cid, name in CHINAISA_COLUMNS.items():
#         cr = ChinaISACrawler(column_ids=[cid], page_no=1, page_size=size, max_items=size, max_pages=2)
#         r = cr.get_news()
#         results.append({
#             'id': cid,
#             'name': name,
#             'status': r.status,
#             'err_code': r.err_code,
#             'err_info': r.err_info,
#             'count': len(r.news_list or []),
#             'items': [n.model_dump() for n in (r.news_list or [])],
#         })
#     return {'columns': results}
