"""
每个插件文件都需要导出名为 `handler` 的函数，作为工具入口。

参数:
- args: 入口函数的参数对象
- args.input: 输入参数（例如 args.input.xxx）
- args.logger: 日志记录器，由运行时注入

返回:
返回的数据必须与声明的输出参数结构一致。
"""

from runtime import Args
from pydantic import BaseModel, Field
from typing import Optional, List, Tuple, Dict

import logging
import re
import time
import random
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin


ORIGIN_NAME = "中国有色金属工业协会"
SITE_BASE = "https://www.chinania.org.cn/"


class News(BaseModel):
    title: str
    url: str
    origin: str
    summary: str
    publish_date: str


DEFAULT_CHANNELS = [
    # 行业新闻：仅保留“国内新闻”
    "hangyexinwen/guoneixinwen",
    # 行业统计三子栏
    "hangyetongji/jqzs",
    "hangyetongji/tongji",
    "hangyetongji/chanyeshuju",
]


class Input(BaseModel):
    channels: Optional[List[str]] = Field(
        default=DEFAULT_CHANNELS,
        description=(
            "频道路径（相对 /html/），默认包含："
            "行业新闻/[guoneixinwen]；"
            "行业统计/[jqzs, tongji, chanyeshuju]"
        ),
    )
    max_pages: int = Field(default=1, ge=1, description="每个频道最多翻页（目前仅首页稳定）")
    # 时间与数量策略
    days_limit: int = Field(default=3, ge=1, description="仅保留最近N天内（含今天）")
    ensure_all_today: bool = Field(default=True, description="是否无上限包含当天全部信息")
    min_today_fill: int = Field(default=3, ge=0, description="若当天不足该条数，则用N天内最近内容补足到该数")
    per_channel_max: Optional[int] = Field(default=3, description="每个子栏目最大条数（默认3；仅在当天无内容时生效）")


class Output(BaseModel):
    news_list: Optional[List[News]] = Field(default=None, description="新闻列表")
    status: str = Field(default="OK", description="状态标记")
    err_code: Optional[str] = Field(default=None, description="错误码")
    err_info: Optional[str] = Field(default=None, description="错误信息")


Metadata = {
    "name": "get_assoc_cnia",
    "description": (
        "抓取中国有色金属工业协会：行业新闻(国内新闻) 与 行业统计(景气指数/统计/产业数据)"
    ),
    "input": Input.model_json_schema(),
    "output": Output.model_json_schema(),
}


def handler(args: Args[Input]) -> Output:
    logger = getattr(args, "logger", logging.getLogger(__name__))
    inp_obj = getattr(args, "input", None)
    # 兼容字典/None/pydantic 对象
    if isinstance(inp_obj, dict):
        channels = inp_obj.get("channels") or DEFAULT_CHANNELS
        try:
            max_pages = int(inp_obj.get("max_pages") or 1)
        except Exception:
            max_pages = 1
        try:
            days_limit = int(inp_obj.get("days_limit") or 3)
        except Exception:
            days_limit = 3
        ensure_all_today = bool(inp_obj.get("ensure_all_today") if inp_obj.get("ensure_all_today") is not None else True)
        try:
            min_today_fill = int(inp_obj.get("min_today_fill") or 3)
        except Exception:
            min_today_fill = 3
        try:
            per_channel_max = inp_obj.get("per_channel_max")
            per_channel_max = int(per_channel_max) if per_channel_max is not None else 3
        except Exception:
            per_channel_max = 3
    elif inp_obj is None:
        channels = DEFAULT_CHANNELS
        max_pages = 1
        days_limit = 3
        ensure_all_today = True
        min_today_fill = 3
        per_channel_max = 3
    else:
        channels = getattr(inp_obj, "channels", None) or DEFAULT_CHANNELS
        max_pages = int(getattr(inp_obj, "max_pages", 1) or 1)
        days_limit = int(getattr(inp_obj, "days_limit", 3) or 3)
        ea = getattr(inp_obj, "ensure_all_today", True)
        ensure_all_today = bool(True if ea is None else ea)
        min_today_fill = int(getattr(inp_obj, "min_today_fill", 3) or 3)
        pcm = getattr(inp_obj, "per_channel_max", 3)
        per_channel_max = int(pcm) if pcm is not None else 3

    try:
        session = _make_session()
        items: List[News] = []
        seen_global = set()

        from datetime import datetime, timedelta
        today = datetime.today().date()
        earliest = today - timedelta(days=max(0, days_limit - 1))

        # 定义频道与匹配规则
        rules: Dict[str, Dict[str, str]] = {}
        for ch in channels:
            ch = (ch or "").strip("/")
            if not ch:
                continue
            index_url = urljoin(SITE_BASE, f"html/{ch}/")
            # 仅抓取当前频道下的文章详情链接
            # 例如 /html/hangyexinwen/…/id.html 或 /html/hangyetongji/jqzs/…/id.html
            path_prefix = f"/html/{ch}/"
            rules[ch] = {
                "index": index_url,
                "prefix": path_prefix,
            }

        for ch, conf in rules.items():
            index_url = conf["index"]
            prefix = conf["prefix"]
            # 当前站点翻页样式不稳定，优先抓取首页足量链接
            for page in range(1, max_pages + 1):
                url = index_url if page == 1 else _possible_page_url(index_url, page)
                try:
                    html = _fetch_html(session, url)
                except Exception:
                    if page == 1:
                        # 首页失败则直接进入下一个频道
                        break
                    else:
                        continue
                rows = _extract_list_links(html, prefix)
                if not rows:
                    if page > 1:
                        break

                # 收集每个频道的候选，先分类“今日”和“近N天内”
                ch_today: List[News] = []
                ch_window: List[News] = []

                def _date_in_window(dstr: str) -> Optional[str]:
                    try:
                        from datetime import datetime as _dt
                        d = _dt.strptime(dstr, "%Y-%m-%d").date()
                        if d >= earliest and d <= today:
                            return "today" if d == today else "window"
                    except Exception:
                        return None
                    return None

                for title, link, date_title in rows:
                    # 先尝试标题中的日期
                    eff_date = date_title
                    summary = ""
                    det_date = None
                    # 若标题无日期或需确认，则解析详情
                    if not eff_date:
                        try:
                            summary, det_date = _parse_detail(session, link)
                        except Exception:
                            summary, det_date = "", None
                        eff_date = det_date or ""
                    else:
                        # 需要摘要仍需解析详情
                        try:
                            summary, det_date = _parse_detail(session, link)
                            if det_date:
                                eff_date = det_date
                        except Exception:
                            summary = ""

                    if not eff_date:
                        continue
                    bucket = _date_in_window(eff_date)
                    if not bucket:
                        continue
                    news = News(title=title, url=link, origin=ORIGIN_NAME, summary=summary, publish_date=eff_date)
                    if bucket == "today":
                        ch_today.append(news)
                    else:
                        ch_window.append(news)

                # 频道内选择逻辑（按你的新规则）
                # ① 若存在当天内容，则仅返回当天全部，不抓取任何历史
                if ch_today:
                    selected = list(ch_today)
                else:
                    # ② 当天没有，则抓取历史三天内（days_limit）按时间倒序最多 per_channel_max 条
                    def _key_hist(n: News):
                        from datetime import datetime as _dt
                        try:
                            return _dt.strptime(n.publish_date, "%Y-%m-%d")
                        except Exception:
                            return _dt.min
                    ch_window_sorted = sorted(ch_window, key=_key_hist, reverse=True)
                    limit = per_channel_max if per_channel_max is not None else 3
                    selected = ch_window_sorted[:max(0, int(limit))]

                # 追加到全局（跨频道去重）
                for n in selected:
                    if n.url in seen_global:
                        continue
                    items.append(n)
                    seen_global.add(n.url)
                # 仅首页或设定页处理；该站翻页不稳定，处理一页后即可跳出
                break

        # 全部频道合并后，按日期全局降序排序
        def _gkey(n: News):
            from datetime import datetime as _dt
            try:
                return _dt.strptime(n.publish_date, "%Y-%m-%d")
            except Exception:
                return _dt.min
        items = sorted(items, key=_gkey, reverse=True)

        status = "OK" if items else "EMPTY"
        return Output(news_list=items or None, status=status, err_code=None if items else "NO_DATA", err_info=None if items else "No news parsed")
    except Exception as e:
        logger.exception("assoc_cnia handler failed")
        return Output(news_list=None, status="ERROR", err_code="PLUGIN_ERROR", err_info=str(e))


def _make_session() -> requests.Session:
    sess = requests.Session()
    sess.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    })
    # 统一与项目其它插件的网络策略
    sess.trust_env = False
    return sess


def _fetch_html(sess: requests.Session, url: str) -> str:
    retries = 3
    delay = 1.0
    for attempt in range(retries):
        try:
            r = sess.get(url, timeout=20, verify=False, proxies={'http': None, 'https': None})
            r.raise_for_status()
            data = r.content
            ct = r.headers.get('content-type', '') or ''

            def _norm(cs: str) -> str:
                cs = (cs or '').strip().strip('"\'').lower()
                return 'gb18030' if cs in ('gb2312','gb-2312','gbk') else ('utf-8' if cs in ('utf8','utf-8') else (cs or 'utf-8'))

            def _enc_from_meta(b: bytes) -> Optional[str]:
                m = re.search(br'charset\s*=\s*["\']?([a-zA-Z0-9_\-]+)', b[:4096], re.IGNORECASE)
                if m:
                    try:
                        return _norm(m.group(1).decode('ascii', errors='ignore'))
                    except Exception:
                        return None
                return None

            def _enc_from_header() -> Optional[str]:
                m = re.search(r'charset=([^;\s]+)', ct, re.IGNORECASE)
                if m:
                    return _norm(m.group(1))
                return _norm(r.encoding) if r.encoding else None

            cands: List[str] = []
            for c in (_enc_from_meta(data), r.apparent_encoding and _norm(r.apparent_encoding), _enc_from_header(), 'utf-8','gb18030'):
                if c and c not in cands:
                    cands.append(c)  # type: ignore[arg-type]

            best_txt = None
            best_bad = 10**9
            for ec in cands:
                try:
                    txt = data.decode(ec, errors='replace')
                    bad = txt.count('\ufffd')
                    if bad < best_bad:
                        best_txt = txt
                        best_bad = bad
                        if bad == 0:
                            break
                except Exception:
                    continue
            return best_txt or data.decode('utf-8', errors='ignore')
        except requests.RequestException:
            if attempt < retries - 1:
                time.sleep(delay * (1 + random.random() * 0.5))
                continue
            raise


def _possible_page_url(index_url: str, page: int) -> str:
    # 常见 CMS 翻页：index_2.html / index_3.html
    # chinania 某些频道未开放此形式，失败时由调用方兜底
    if not index_url.endswith('/'):
        index_url = index_url.rstrip('/') + '/'
    return urljoin(index_url, f"index_{page}.html")


def _extract_list_links(html: str, path_prefix: str) -> List[Tuple[str, str, str]]:
    soup = BeautifulSoup(html or '', 'html5lib')
    seen = set()
    out: List[Tuple[str, str, str]] = []
    # 仅接受形如 /html/<channel>/YYYY/MMDD/ID.html 的详情链接，排除 index*.html 等列表/翻页链接
    # 规则：必须以指定频道前缀开头，且结尾形如 20YY/MMDD/ID.html
    # 使用前缀判断 + 尾部正则，避免整串正则在不同解析场景下偶发不匹配
    tail_pat = re.compile(r"^20\d{2}/\d{4}/\d+\.html$")
    bad_titles = {
        '上一页','上页','下一页','下页','首页','尾页','返回','返回首页','更多','更多>','更多>>','查看更多','上一篇','下一篇'
    }
    for a in soup.find_all('a', href=True):
        href = (a.get('href') or '').strip()
        if not href:
            continue
        # 规范化为站内绝对路径进行匹配
        site_path = href
        if href.startswith('http'):
            try:
                # 只处理本站链接
                if href.startswith(SITE_BASE):
                    site_path = '/' + href[len(SITE_BASE):].lstrip('/')
                else:
                    continue
            except Exception:
                continue
        # 前缀校验
        if not site_path.startswith(path_prefix):
            continue
        # 过滤 index*.html 等（仅接受形如 20YY/MMDD/ID.html 的尾部）
        tail = site_path[len(path_prefix):]
        if not tail_pat.match(tail):
            continue
        title_raw = a.get_text(strip=True) or ''
        title = _strip_date_suffix(title_raw)
        if not title or title in bad_titles:
            continue
        absu = href if href.startswith('http') else urljoin(SITE_BASE, href.lstrip('/'))
        if absu in seen:
            continue
        # 优先从 URL 提取日期（/YYYY/MMDD/ID.html）
        date = ''
        m = re.match(r'^(20\d{2})/(\d{2})(\d{2})/\d+\.html$', tail)
        if m:
            y, mo, d = m.groups()
            try:
                date = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
            except Exception:
                date = ''
        if not date:
            date = _extract_date(title) or ''
        out.append((title, absu, date))
        seen.add(absu)
    return out


DATE_RE = re.compile(r"(20\d{2})\D(\d{1,2})\D(\d{1,2})")
DATE_TAIL_RE = re.compile(
    r"[\s\u3000]*[（(]?\s*(20\d{2})\s*[./\-年]\s*(\d{1,2})\s*[./\-月]\s*(\d{1,2})(?:日)?\s*[）)]?\s*$"
)


def _extract_date(text: str) -> Optional[str]:
    m = DATE_RE.search(text or '')
    if m:
        y, mo, d = m.groups()
        try:
            return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
        except Exception:
            return None
    return None


def _strip_date_suffix(title: str) -> str:
    """移除标题末尾可能附带的日期片段，例如：
    "... 2025-09-25"、"...(2025/9/25)"、"...（2025年9月25日）" 等。
    仅去尾部的日期模式，避免误伤正文数字。
    """
    if not title:
        return title
    return DATE_TAIL_RE.sub('', title).strip()


def _parse_detail(sess: requests.Session, url: str) -> Tuple[str, Optional[str]]:
    html = _fetch_html(sess, url)
    soup = BeautifulSoup(html or '', 'html5lib')
    # 常见内容容器候选
    candidates = [
        '.article_con', '.TRS_Editor', '.content', '.article-content', '.main-content',
        '#zoom', 'article', '.article-detail', '.detail', '.content_area', '.art-con',
        '.content-box', '.news-content', '.main', '.contentArea', '.contentAreaW'
    ]
    node = None
    for sel in candidates:
        node = soup.select_one(sel)
        if node:
            break
    node = node or soup
    # 清理无关元素
    for t in node.find_all(['script', 'style', 'noscript']):
        t.decompose()
    for sel in ['header', 'footer', 'nav', 'aside', '.share', '.toolbar', '.breadcrumb', '.position', '.article_title', '.source', '.editor']:
        for t in node.select(sel):
            t.decompose()
    text = node.get_text('\n', strip=True)
    # 提取日期（常见格式包含“时间：YYYY-MM-DD”或正文中首个日期）
    date = None
    m = re.search(r"(20\d{2})\s*[年\-/.]\s*(\d{1,2})\s*[月\-/.]\s*(\d{1,2})", text)
    if m:
        y, mo, d = m.groups()
        try:
            date = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
        except Exception:
            date = None
    # 返回全文（不截断），仅规范空白
    t = re.sub(r"\s+", " ", text).strip()
    summary = t
    return summary, date
