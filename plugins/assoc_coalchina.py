"""
抓取中国煤炭工业协会（coalchina.org.cn）网站新闻/通知的插件。

说明：
- 站点时常出现编码与结构不稳定的问题（页面乱码/栏目链接异常等），本实现做了鲁棒解码、
  多路径列表解析与详情页回退策略，以尽可能返回可用信息。
- 与现有插件风格一致，导出入口函数 `handler(args: Args[Input]) -> Output`。
"""

# 低代码平台兼容：runtime/pydantic 非必需，提供文件内兜底实现
try:
    from runtime import Args  # type: ignore
except Exception:  # pragma: no cover
    class Args:  # 兜底占位，避免导入失败
        def __init__(self, input=None, logger=None):
            self.input = input
            self.logger = logger

try:
    from pydantic import BaseModel, Field  # type: ignore
except Exception:  # pragma: no cover
    class BaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

        @classmethod
        def model_json_schema(cls):
            return {}

    def Field(default=None, **kwargs):  # noqa: N802
        return default

from typing import Optional, List, Tuple, Dict

import logging
import re
import time
import random
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


class News(BaseModel):
    # 输出顺序：先标题，再正文
    title: str
    summary: str
    url: str
    origin: str
    publish_date: str


class Input(BaseModel):
    channels: Optional[List[str]] = Field(
        default=None,
        description="抓取频道：notice(通知公告)|news(协会动态)|industry(行业资讯集合)。None=默认 ['notice','news']",
    )
    catids: Optional[List[int]] = Field(
        default=None,
        description="直接指定 catid 列表（如 150、106）。若提供将优先使用。",
    )
    max_pages: int = Field(default=2, ge=1, description="列表最大翻页数")
    max_items: Optional[int] = Field(default=8, ge=1, description="每频道最大抓取条数")
    since_days: int = Field(default=7, ge=1, description="近 N 天时间窗口")
    strict_nowadays: bool = Field(default=False, description="严格限制近 N 天；不回补更早内容")


class Output(BaseModel):
    news_list: Optional[List[News]] = Field(default=None)
    status: str = Field(default="OK")
    err_code: Optional[str] = Field(default=None)
    err_info: Optional[str] = Field(default=None)


Metadata = {
    "name": "assoc_coalchina",
    "description": "中国煤炭工业协会（coalchina.org.cn）新闻/通知抓取器",
    "input": (Input.model_json_schema() if hasattr(Input, 'model_json_schema') else {}),
    "output": (Output.model_json_schema() if hasattr(Output, 'model_json_schema') else {}),
}


ORIGIN = "中国煤炭工业协会"
INDEX_BASE = "https://www.coalchina.org.cn/"

# 经验映射：可按关键词扩展
COAL_CHANNELS: Dict[str, Dict[str, str]] = {
    "notice": {
        "name": "通知公告",
        "catid": "61",  # 通知公告
    },
    "news": {
        "name": "协会动态",
        "catid": "60",  # 协会动态
    },
    "industry": {
        "name": "行业资讯",
        # 行业资讯必抓：你指定的 6 个子栏目（静态重写形式亦适配）
        # 12=行业新闻(聚合) 20=经济运行 25=价格指数 39=政策法规 44=国际合作 67=统计数据
        "mandatory_catids": [12, 20, 25, 39, 44, 67],
        # 备选（动态发现）示例：仅作为注释留存，默认不启用；如需启用，将其合并到运行时 catids 即可
        # "discovery_candidates": [15, 16, 18, 19],  # 15=地方动态 16=企业动态 18=上市公司 19=战略合作
    },
}


def handler(args) -> Output:
    logger = getattr(args, "logger", None) or logging.getLogger(__name__)
    inp = getattr(args, "input", None)

    # 解析输入
    if isinstance(inp, dict):
        chs = inp.get("channels")
        mp = inp.get("max_pages")
        mi = inp.get("max_items")
        sd = inp.get("since_days")
        sn = inp.get("strict_nowadays")
        catids = inp.get("catids")
    else:
        chs = getattr(inp, "channels", None)
        mp = getattr(inp, "max_pages", None)
        mi = getattr(inp, "max_items", None)
        sd = getattr(inp, "since_days", None)
        sn = getattr(inp, "strict_nowadays", None)
        catids = getattr(inp, "catids", None) if inp is not None else None

    try:
        # 频道归一
        mapped: List[str] = []
        for ch in (chs or ["industry"]):
            mapped.append(ch)
        # 去重保序
        seen_ch = set()
        channels = [c for c in mapped if not (c in seen_ch or seen_ch.add(c))]

        try:
            max_pages = int(mp) if mp is not None else 2
        except Exception:
            max_pages = 2
        try:
            max_items = int(mi) if mi is not None else 8
        except Exception:
            max_items = 8
        try:
            since_days = int(sd) if sd is not None else 7
        except Exception:
            since_days = 7

        def _to_bool(v):
            if isinstance(v, bool):
                return v
            if isinstance(v, str):
                return v.strip().lower() in ("1", "true", "yes", "y", "on")
            if isinstance(v, (int, float)):
                return bool(v)
            return False

        strict_nowadays = _to_bool(sn)

        # 发现栏目（catid）（禁用首页自动发现，避免误入 60/61 等非行业资讯）
        discovered_catids: List[int] = []
        if catids and isinstance(catids, list):
            try:
                discovered_catids = [int(x) for x in catids if str(x).isdigit()]
            except Exception:
                discovered_catids = []
        # 对于单 catid 频道（notice/news），仅在显式传入时才使用；默认 industry 不需要此分支

        # 构造列表 URL
        list_endpoints: List[Tuple[str, str]] = []  # (channel_label, list_url)
        for ch in channels:
            conf = COAL_CHANNELS.get(ch)
            if not conf:
                continue
            # 单 catid 频道（notice/news）
            if (conf.get("catid") or "").isdigit():
                cid = conf["catid"]
                # 同时支持两种 URL 形式
                list_endpoints.append((ch, f"{INDEX_BASE}index.php?m=content&c=index&a=lists&catid={cid}"))
                list_endpoints.append((ch, f"{INDEX_BASE}list-{cid}-1.html"))
            # 行业资讯集合频道（industry）
            mand = conf.get("mandatory_catids") or []
            if mand:
                for cid in mand:
                    list_endpoints.append(("industry", f"{INDEX_BASE}index.php?m=content&c=index&a=lists&catid={cid}"))
                    list_endpoints.append(("industry", f"{INDEX_BASE}list-{cid}-1.html"))
            # 预留：动态发现的候选（默认注释关闭）
            # cand = conf.get("discovery_candidates") or []
            # for cid in cand:
            #     list_endpoints.append(("industry_auto", f"{INDEX_BASE}index.php?m=content&c=index&a=lists&catid={cid}"))
            #     list_endpoints.append(("industry_auto", f"{INDEX_BASE}list-{cid}-1.html"))
        # 将用户/自动发现的 catid 也加入（归入 'auto' 分组）
        for cid in discovered_catids:
            list_endpoints.append(("auto", f"{INDEX_BASE}index.php?m=content&c=index&a=lists&catid={cid}"))
            list_endpoints.append(("auto", f"{INDEX_BASE}list-{cid}-1.html"))

        # 去重列表 URL（保序）
        uniq_endpoints: List[Tuple[str, str]] = []
        seen_url = set()
        for tag, u in list_endpoints:
            if u not in seen_url:
                uniq_endpoints.append((tag, u))
                seen_url.add(u)

        # 今日日期，便于配额控制
        try:
            from datetime import datetime as _dt
            today_str = _dt.today().strftime("%Y-%m-%d")
        except Exception:
            today_str = ""

        # 抓取聚合
        collected: List[Dict[str, str]] = []
        for tag, first_page in uniq_endpoints:
            # 分页 URL 规则（两种形式均支持）：
            # 1) index.php?m=...&catid=XX&page=N
            # 2) list-XX-N.html
            page_urls = [first_page]
            if "list-" in first_page:
                # 已是重写形式
                m = re.search(r"list-(\d+)-1\.html", first_page)
                if m:
                    cid = m.group(1)
                    for i in range(2, max_pages + 1):
                        page_urls.append(f"{INDEX_BASE}list-{cid}-{i}.html")
            else:
                for i in range(2, max_pages + 1):
                    sep = "&" if ("?" in first_page) else "?"
                    page_urls.append(f"{first_page}{sep}page={i}")

            acc: List[Tuple[str, str, str]] = []
            for u in page_urls:
                html = _fetch_html(u)
                if not html:
                    continue
                acc.extend(_parse_list_phpcms(html, INDEX_BASE))
                if max_items:
                    try:
                        non_today = sum(1 for _, _, d in acc if d != today_str)
                        if non_today >= max_items:
                            break
                    except Exception:
                        if len(acc) >= max_items:
                            break

            for title, url, date in acc:
                collected.append({
                    "title": title,
                    "url": url,
                    "date": date,
                    "origin": ORIGIN,
                    "channel": tag,
                })

        # URL 去重
        uniq_items: List[Dict[str, str]] = []
        seen_urls = set()
        for it in collected:
            if it["url"] not in seen_urls:
                uniq_items.append(it)
                seen_urls.add(it["url"])

        # 详情补全摘要与日期
        enriched: List[Dict[str, str]] = []
        for it in uniq_items:
            summary, date_fb = _parse_detail(it["url"])  # 失败返回空串
            use_date = it["date"] or (date_fb or "")
            enriched.append({**it, "summary": summary, "date": use_date})

        # 全局选择逻辑：
        # ① 若有“当天”则仅返回当天（不限条数）
        # ② 否则返回近三天内全部（不限条数）
        # ③ 若仍无，返回具体诊断
        from datetime import datetime, timedelta
        today = datetime.today().date()
        earliest = today - timedelta(days=2)

        def _to_date(s: str):
            try:
                y, m, d = s.split("-")
                return datetime(int(y), int(m), int(d)).date()
            except Exception:
                return None

        # 排序一次，便于后续统一输出
        enriched.sort(key=lambda it: (_to_date(it.get("date") or "") or datetime.min.date()), reverse=True)

        todays = [it for it in enriched if _to_date(it.get("date") or "") == today]
        if todays:
            selected = todays
            any_filtered_due_to_time = False
        else:
            window = [it for it in enriched if (_to_date(it.get("date") or "") or datetime.min.date()) >= earliest]
            selected = window
            any_filtered_due_to_time = (len(enriched) > 0 and len(window) == 0)

        news_list: List[News] = []
        for it in selected:
            news_list.append(News(
                title=it["title"],
                summary=it.get("summary", ""),
                url=it["url"],
                origin=it["origin"],
                publish_date=it.get("date", ""),
            ))

        status = "OK" if news_list else "EMPTY"
        if news_list:
            return Output(news_list=news_list, status=status)
        else:
            # 诊断信息：统计每个来源入口解析条数与最常见日期概况
            diag_counts: Dict[str, int] = {}
            date_samples: List[str] = []
            for it in uniq_items:
                src = it.get("channel") or "auto"
                diag_counts[src] = diag_counts.get(src, 0) + 1
                if it.get("date"):
                    date_samples.append(it["date"])  # type: ignore[index]
            diag_parts = [f"{k}:{v}" for k, v in sorted(diag_counts.items())]
            date_parts = ",".join(sorted(set(date_samples), reverse=True)[:5])
            if any_filtered_due_to_time:
                return Output(status="EMPTY", err_code="NO_RECENT", err_info=f"今天无更新，且最近三天均无内容（入口:{'|'.join(diag_parts)}; 样本日期:{date_parts}）")
            return Output(status="EMPTY", err_code="NO_DATA", err_info=f"未解析到有效列表项或详情（入口:{'|'.join(diag_parts)}）")
    except Exception as e:
        logger.exception("assoc_coalchina failed")
        return Output(status="ERROR", err_code="PLUGIN_ERROR", err_info=str(e))


# ---------- 抓取与解析工具 ----------

def _fetch_html(url: str) -> str:
    DEFAULT_HEADERS = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    retries = 3
    delay = 1.0
    sess = requests.Session()
    sess.headers.update(DEFAULT_HEADERS)
    sess.trust_env = False
    for attempt in range(retries):
        try:
            resp = sess.get(url, timeout=15, verify=False, proxies={"http": None, "https": None})
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "") or ""
            data = resp.content

            def _norm(cs: str) -> str:
                cs = (cs or "").strip().strip("\"'").lower()
                return "gb18030" if cs in ("gb2312", "gb-2312", "gbk") else ("utf-8" if cs in ("utf8", "utf-8") else (cs or "utf-8"))

            def _enc_from_meta(b: bytes) -> Optional[str]:
                m = re.search(br'charset\s*=\s*["\']?([a-zA-Z0-9_\-]+)', b[:4096], re.IGNORECASE)
                if m:
                    try:
                        return _norm(m.group(1).decode("ascii", errors="ignore"))
                    except Exception:
                        return None
                return None

            def _enc_from_header() -> Optional[str]:
                m = re.search(r"charset=([^;\s]+)", ct, re.IGNORECASE)
                if m:
                    return _norm(m.group(1))
                return _norm(resp.encoding) if resp.encoding else None

            cands: List[str] = []
            for c in (_enc_from_meta(data), resp.apparent_encoding and _norm(resp.apparent_encoding), _enc_from_header(), "utf-8", "gb18030"):
                if c and c not in cands:
                    cands.append(c)  # type: ignore[arg-type]

            best_txt = None
            best_bad = 10**9
            for ec in cands:
                try:
                    txt = data.decode(ec, errors="replace")
                    bad = txt.count("\ufffd")
                    if bad < best_bad:
                        best_txt = txt
                        best_bad = bad
                        if bad == 0:
                            break
                except Exception:
                    continue
            return best_txt or data.decode("utf-8", errors="ignore")
        except requests.RequestException:
            if attempt < retries - 1:
                time.sleep(delay * (1 + random.random() * 0.5))
                continue
            raise


DATE_RE = re.compile(r"(20\d{2})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})[日]?")


def _extract_date(text: str) -> Optional[str]:
    s = text or ""
    s = s.replace("年", "-").replace("月", "-").replace("日", "")
    m = re.search(r"(20\d{2})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{1,2})", s)
    if m:
        y, mo, d = m.groups()
        try:
            from datetime import datetime
            dt = datetime(int(y), int(mo), int(d))
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return None
    m2 = re.search(r"(20\d{2}-\d{1,2}-\d{1,2})", s)
    if m2:
        return m2.group(1)
    return None


def _find_content_node(soup: BeautifulSoup):
    for tag, attrs in [
        ("div", {"id": "zoom"}),
        ("div", {"class": "content"}),
        ("div", {"class": "article"}),
        ("div", {"class": "TRS_Editor"}),
        ("div", {"class": "article-content"}),
        ("div", {"class": "detail-main"}),
        ("article", {}),
    ]:
        node = soup.find(tag, attrs=attrs)
        if node:
            return node
    return soup


def _parse_list_phpcms(html: str, base_url: str) -> List[Tuple[str, str, str]]:
    """尽量兼容 PHPCMS 列表结构。

    解析优先级：
    - 常见结构 ul/li -> a + span.time/date
    - 退化：任意 li/a；若 href 包含 'a=show&catid=' 优先
    - 兜底：从所有 a[href] 中抽取标题 + 推断日期
    """
    soup = BeautifulSoup(html, "html5lib")
    items: List[Tuple[str, str, str]] = []

    # 仅解析常见列表（不做全页兜底）
    for li in soup.select("ul li"):
        a = li.find("a", href=True)
        if not a:
            continue
        title = a.get_text(strip=True)
        href = a.get("href", "").strip()
        if not title or not href or href.startswith("javascript:"):
            continue
        url = urljoin(base_url, href)
        # 仅接受内容页链接
        if ("a=show" not in href) and ("content" not in href):
            continue
        tm = li.find("span", class_=re.compile(r"time|date|pub", re.I))
        date_text = tm.get_text(strip=True) if tm else li.get_text(" ", strip=True)
        date = _extract_date(date_text) or ""
        items.append((title, url, date))
    return items


def _parse_detail(url: str) -> Tuple[str, Optional[str]]:
    html = _fetch_html(url)
    if not html:
        return "", None
    soup = BeautifulSoup(html, "html5lib")
    node = _find_content_node(soup)
    for tag in node.find_all(["script", "style", "noscript"]):
        tag.decompose()
    # 移除常见 UI 区块
    for sel in ["header", "footer", "nav", "aside", ".share", ".read", ".crumbs"]:
        for t in node.select(sel):
            t.decompose()
    text = node.get_text("\n", strip=True) or ""
    if not text:
        # meta description 回退
        desc = soup.find("meta", attrs={"name": "description"})
        if desc and desc.get("content"):
            text = desc.get("content") or ""
    summary = re.sub(r"\s+", " ", text).strip()
    # 禁止使用整页时间作为发布日期回退，无法确定则返回 None
    return summary, None


def _discover_catids_from_homepage() -> List[int]:
    """从首页发现可用 catid。按关键词挑选更相关的栏目。"""
    try:
        html = _fetch_html(INDEX_BASE)
    except Exception:
        html = ""
    if not html:
        return []
    soup = BeautifulSoup(html, "html5lib")
    catids: List[int] = []
    kw_map = {
        "通知": 3,
        "公告": 3,
        "协会动态": 2,
        "动态": 1,
        "要闻": 1,
    }
    for a in soup.select('a[href*="a=lists"][href*="catid="]'):
        href = a.get("href", "")
        m = re.search(r"catid=(\d+)", href)
        if not m:
            continue
        cid = int(m.group(1))
        txt = a.get_text(strip=True)
        score = 0
        for k, w in kw_map.items():
            if k in txt:
                score += w
        # 优先保留高分栏目
        if score > 0 or (cid in (106, 150)):
            catids.append(cid)
    # 去重保序
    seen: set = set()
    out: List[int] = []
    for cid in catids:
        if cid not in seen:
            seen.add(cid)
            out.append(cid)
    return out[:6]


# 低代码平台直接入口（无需 Args/类型依赖）
def get_coal_news(params: Optional[dict] = None) -> dict:
    """便于在低代码平台直接调用。

    调用示例：
        get_coal_news({
            "channels": ["notice", "news"],
            "max_pages": 2,
            "max_items": 8,
            "since_days": 7,
            "strict_nowadays": False,
            "catids": [150, 106],
        })
    返回值为字典：{"status": "OK|EMPTY|ERROR", "news_list":[...], "err_code":..., "err_info":...}
    """
    params = params or {}
    # 构造简化 Input 对象；若无 pydantic 则使用 BaseModel 兜底
    try:
        inp = Input(**params)
    except Exception:
        # 直接丢给 handler 的字典分支
        inp = params

    out = handler(Args(input=inp))  # type: ignore[arg-type]

    # 将 Output 转为基础 dict，避免外部依赖 pydantic
    def _to_dict(obj):
        if hasattr(obj, "model_dump"):
            return obj.model_dump()  # pydantic v2
        if hasattr(obj, "dict"):
            return obj.dict()  # pydantic v1
        if isinstance(obj, (list, tuple)):
            return [
                _to_dict(x) for x in obj
            ]
        if hasattr(obj, "__dict__"):
            return {k: _to_dict(v) for k, v in obj.__dict__.items() if not k.startswith("__")}
        return obj

    res = _to_dict(out)

    # 保证 news_list 字段顺序：title -> summary -> url -> origin -> publish_date
    try:
        nl = res.get("news_list") if isinstance(res, dict) else None
        if isinstance(nl, list):
            ordered = []
            for it in nl:
                if isinstance(it, dict):
                    ordered.append({
                        "title": it.get("title", ""),
                        "summary": it.get("summary", ""),
                        "url": it.get("url", ""),
                        "origin": it.get("origin", ""),
                        "publish_date": it.get("publish_date", ""),
                    })
                else:
                    ordered.append(it)
            res["news_list"] = ordered
    except Exception:
        pass

    return res



