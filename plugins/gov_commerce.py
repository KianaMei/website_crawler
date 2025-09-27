"""
每个插件文件都需要导出名为 `handler` 的函数，作为工具入口。

参数:
- args: 入口函数的参数对象
- args.input: 输入参数（例如 args.input.xxx）
- args.logger: 日志记录器，由运行时注入

提示: 请在 Metadata 中补充 input/output，有助于 LLM 正确识别并调用工具。

返回:
返回的数据必须与声明的输出参数结构一致。
"""

from runtime import Args
from pydantic import BaseModel, Field
from typing import Optional, List, Dict

import logging
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time
import random


DEFAULT_URL = "https://www.mofcom.gov.cn/zcfb/index.html"

# 简易调试输出（直接打印到控制台；同时尽量写入运行时 logger）
DEBUG_MODE = True
_DBG_LOGGER = None  # 由 handler 在 debug=True 时注入

def _dbg(msg: str) -> None:
    if not DEBUG_MODE:
        return
    try:
        # 始终往控制台打印（便于你在控制台直接看到）
        print(f"[gov_commerce] {msg}", flush=True)
        # 同时尝试写入运行时 logger（不影响控制台输出）
        if _DBG_LOGGER is not None:
            try:
                _DBG_LOGGER.info(f"[gov_commerce] {msg}")
            except Exception:
                pass
    except Exception:
        pass


class News(BaseModel):
    title: str
    url: str
    origin: str
    summary: str
    publish_date: str


class Input(BaseModel):
    url: Optional[str] = Field(default=DEFAULT_URL, description="商务部 政策聚合页地址（含三子栏目）")
    days: int = Field(default=3, ge=1, le=60, description="仅保留最近 N 天（严格过滤）")
    max_items: int = Field(default=50, ge=1, le=200, description="最大返回条数上限")
    debug: bool = Field(default=True, description="是否打印调试信息到终端（默认开启）")


    target_date: Optional[str] = Field(default=None, description="ָ������ YYYY-MM-DD�������ø����ڵ�����������Ȩ�� days")

class Output(BaseModel):
    news_list: Optional[List[News]] = Field(default=None, description="新闻列表")
    status: str = Field(default="OK", description="响应状态标记")
    err_code: Optional[str] = Field(default=None, description="错误码（可选）")
    err_info: Optional[str] = Field(default=None, description="错误信息（可选）")


Metadata = {
    "name": "get_gov_commerce",
    "description": "使用 requests+BeautifulSoup 抓取商务部新闻并返回结果（纯同步，无 Playwright）",
    "input": Input.model_json_schema(),
    "output": Output.model_json_schema(),
}


def handler(args: Args[Input]) -> Output:
    """商务部新闻（requests+BS4 同步）插件"""
    logger = getattr(args, "logger", logging.getLogger(__name__))
    url = args.input.url or DEFAULT_URL
    # 启用/关闭调试
    global DEBUG_MODE, _DBG_LOGGER
    # 默认开启调试；可通过传入 debug=False 显式关闭
    DEBUG_MODE = bool(getattr(args.input, "debug", True))
    _DBG_LOGGER = logger if DEBUG_MODE else None
    _dbg(f"start url={url} days={args.input.days} max_items={args.input.max_items}")
    try:
        # ָ������（������ʽ������ YYYY-MM-DD）
        tdate_raw = getattr(args.input, 'target_date', None)
        tdate = _normalize_date_str(tdate_raw) if tdate_raw else None
        if tdate_raw and not tdate:
            _dbg(f"invalid target_date='{tdate_raw}', expect YYYY-MM-DD, ignored")
        res = _get_news(url, days=args.input.days, max_items=args.input.max_items, target_date=tdate)
        items = [
            News(title=n['title'], url=n['url'], origin='商务部', summary=n['summary'], publish_date=n['publish_date'])
            for n in res
        ]
        _dbg(f"done collected={len(items)}")
        status = 'OK' if items else 'EMPTY'
        return Output(news_list=items or None, status=status, err_code=None if items else 'NO_DATA', err_info=None if items else 'No news parsed')
    except Exception as e:
        logger.exception("gov_commerce handler failed")
        return Output(news_list=None, status="ERROR", err_code="PLUGIN_ERROR", err_info=str(e))


def _normalize_date_str(s: Optional[str]) -> Optional[str]:
    """����������ַ�������Ϊ YYYY-MM-DD��ʽ"""
    try:
        if not s:
            return None
        ss = str(s).strip()
        m = re.search(r'(20\d{2})[\./\-��](\d{1,2})[\./\-��](\d{1,2})', ss)
        if m:
            y, mo, d = m.groups()
            return f"{y}-{int(mo):02d}-{int(d):02d}"
        m2 = re.fullmatch(r'(20\d{2}-\d{2}-\d{2})', ss)
        if m2:
            return m2.group(1)
    except Exception:
        return None
    return None


def _get_news(base_url: str, days: int, max_items: int, target_date: Optional[str] = None):
    base_domain = _get_domain(base_url)

    # 发现“政策发布｜政策解读｜政策图解”三个栏目 URL
    tab_urls = _discover_policy_tabs(base_url)
    if not tab_urls:
        tab_urls = _fallback_policy_tabs(base_url)
    _dbg(f"tabs found: {len(tab_urls)}")

    # 逐个栏目解析列表（保留每个栏目的独立结果，以便按规则挑选）
    tab_results: List[Dict[str, str]] = []
    for list_url in tab_urls:
        d = _parse_policy_list(list_url, base_domain, max(3, days or 3), target_date=target_date)
        if d:
            tab_results.append(d)
        _dbg(f"list parsed: {list_url} -> {len(d or {})} items")

    # 额外：对聚合首页也做一次全页扫描（防止新稿只挂在首页焦点区/卡片区）
    extra_home = _scan_page_for_detail_links(base_url, base_domain, max(3, days or 3), target_date=target_date)
    if extra_home:
        tab_results.append(extra_home)
        _dbg(f"home page extra scan -> {len(extra_home)} items")

    # 选择策略：
    # 1) 以“站点最新日期”为准：返回该最新日期的所有文章（所有栏目，不限条数）
    # 2) 若无法解析出任何日期：退化为每栏目近三天前3条
    from datetime import datetime

    def _split_title_date(k: str):
        if ';' in k:
            a, b = k.split(';', 1)
            return a, b
        return k, ''

    # 收集所有条目
    all_items: List[tuple[str, str]] = []  # (title_date_key, url)
    date_set = set()
    for d in tab_results:
        for k, v in d.items():
            title, dt = _split_title_date(k)
            if dt:
                date_set.add(dt)
            all_items.append((k, v))

    selected: List[tuple[str, str]] = []
    if date_set:
        # 选择集合中最大的日期（站点最新日期）
        try:
            latest = max(date_set)
        except Exception:
            latest = None
        if latest:
            _dbg(f"latest date={latest}")
            for k, v in all_items:
                _, dt = _split_title_date(k)
                if dt == latest:
                    selected.append((k, v))
    else:
        recent_3 = set(_few_days(3))
        for d in tab_results:
            taken = 0
            for k, v in d.items():
                if taken >= 3:
                    break
                _, dt = _split_title_date(k)
                if dt in recent_3:
                    selected.append((k, v))
                    taken += 1
    # ���ȼ���ָ�����ڣ�����������
    if target_date:
        selected = [(k, v) for (k, v) in all_items if _split_title_date(k)[1] == target_date]
        _dbg(f"override by target_date={target_date}, selected={len(selected)}")
    _dbg(f"selected total={len(selected)}")

    out: List[Dict[str, str]] = []
    for title_date, link in selected:
        html = _fetch_html(link)
        soup = BeautifulSoup(html, 'html5lib')
        # 详情页内容容器回退列表
        content_selectors = [
            'div.art-con.art-con-bottonmLine',
            'div.TRS_Editor',
            'div#zoom',
            'div.article-con',
            'div.conTxt',
            'div#content',
            'div.content',
            'div#article',
            'div.article',
            'div#zoomcon',
        ]
        div = None
        for sel in content_selectors:
            nodes = soup.select(sel)
            if nodes:
                div = _pick_best_node(nodes)
                if div:
                    break
        # 基于结构选择正文容器：优先从常见容器中选文本量最大的一个
        _strip_unwanted_tags(soup)
        main_node = div or _select_main_content_node(soup)
        if main_node is None:
            main_node = soup
        _prune_non_content(main_node)
        text = _extract_article_text_from_node(main_node)
        if ';' in title_date:
            title_part, publish_date = title_date.split(';', 1)
        else:
            title_part, publish_date = title_date, ''
        out.append({
            'title': title_part or '',
            'url': link,
            'summary': text or '',
            'publish_date': publish_date,
        })
    return out

def _scan_page_for_detail_links(page_url: str, base_domain: str, days: int, target_date: Optional[str] = None) -> Dict[str, str]:
    few_days = _few_days(days)
    allowed_dates = {target_date} if target_date else set(few_days)
    html = _fetch_html(page_url)
    soup = BeautifulSoup(html, 'html5lib')
    href_pat = re.compile(r"/(zcfb|zcjd|zctj)/.+/art/\d{4}/[a-zA-Z0-9_\-]+\.html", re.IGNORECASE)
    out: Dict[str, str] = {}
    added = 0
    for a in soup.find_all('a'):
        href = a.get('href') or ''
        if not href or not href_pat.search(href):
            continue
        abs_url = urljoin(page_url, href)
        if not _same_domain(abs_url, base_domain):
            continue
        title = a.get('title') or a.get_text(strip=True)
        # 优先取近邻文本的日期，其次详情页
        parent = a.find_parent('li') or a.parent
        ctx_text = parent.get_text(' ', strip=True) if parent is not None else a.get_text(' ', strip=True)
        date = None
        m = re.search(r'(20\d{2})[\-/\.年](\d{1,2})[\-/\.月](\d{1,2})', ctx_text)
        if not m:
            m = re.search(r'(20\d{2}-\d{2}-\d{2})', ctx_text)
        if m:
            if len(m.groups()) == 3:
                y, mo, d = m.groups()
                date = f"{y}-{int(mo):02d}-{int(d):02d}"
            else:
                date = m.group(1)
        if not date:
            date = _extract_date_from_detail(abs_url)
        if date and date in allowed_dates:
            key = f"{title};{date}"
            if key not in out:
                out[key] = abs_url
                added += 1
    if added:
        _dbg(f"page-scan {page_url} added={added}")
    return out

def _fetch_trs_dataproxy_list(list_url: str, page_html: str) -> List[Dict[str, str]]:
    """尝试解析 TRS dataproxy.jsp 接口，返回 [{'title','href','date'}...]"""
    results: List[Dict[str, str]] = []
    # 匹配常见的 dataproxy.jsp 接口片段
    m = re.search(r"(/module/web/jpage/dataproxy\\.jsp\?[^'\"<>]+)", page_html, re.IGNORECASE)
    if not m:
        return results
    dp_path = m.group(1)
    dp_url = urljoin(list_url, dp_path)
    dp_html = _fetch_html(dp_url)
    soup = BeautifulSoup(dp_html, 'html5lib')
    # 直接查找 li/a/span 结构
    li_candidates = soup.find_all('li') or []
    for li in li_candidates:
        a = li.find('a')
        if not a:
            continue
        title = a.get('title') or a.get_text(strip=True)
        href = a.get('href') or ''
        span = li.find('span')
        date_text = (span.get_text(strip=True) if span else li.get_text(" ", strip=True))
        # 复用主流程日期提取规则
        d = None
        mm = re.search(r'(20\d{2})[\-/\.年](\d{1,2})[\-/\.月](\d{1,2})', date_text)
        if not mm:
            mm = re.search(r'(20\d{2}-\d{2}-\d{2})', date_text)
        if mm:
            if len(mm.groups()) == 3:
                y, mo, dd = mm.groups()
                d = f"{y}-{int(mo):02d}-{int(dd):02d}"
            else:
                d = mm.group(1)
        results.append({'title': title or '', 'href': href or '', 'date': d or ''})
    return results


def _fetch_html(url: str) -> str:
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15',
    ]
    base_headers = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'accept-language': 'zh-CN,zh;q=0.9,en;q=0.6',
        'connection': 'close',
        'referer': 'https://www.mofcom.gov.cn/',
    }

    def _decode_response(resp: requests.Response) -> str:
        content_type = resp.headers.get('content-type', '') or ''
        html_bytes: bytes = resp.content

        def _normalize_charset(cs: str) -> str:
            cs_l = cs.strip().strip('\"\'').lower()
            if cs_l in ('gb2312', 'gb-2312', 'gbk'):
                return 'gb18030'
            if cs_l in ('utf8', 'utf-8'):
                return 'utf-8'
            return cs_l or 'utf-8'

        def _encoding_from_header() -> Optional[str]:
            m = re.search(r'charset=([^;\s]+)', content_type, re.IGNORECASE)
            if m:
                return _normalize_charset(m.group(1))
            if resp.encoding:
                try:
                    return _normalize_charset(resp.encoding)
                except Exception:
                    return None
            return None

        def _encoding_from_meta(data: bytes) -> Optional[str]:
            head = data[:4096]
            m = re.search(br'charset\s*=\s*["\']?([a-zA-Z0-9_\-]+)', head, re.IGNORECASE)
            if m:
                try:
                    return _normalize_charset(m.group(1).decode('ascii', errors='ignore'))
                except Exception:
                    return None
            return None

        candidates: List[str] = []
        meta_enc = _encoding_from_meta(html_bytes)
        if meta_enc:
            candidates.append(meta_enc)
        app_enc = resp.apparent_encoding
        if app_enc:
            n = _normalize_charset(app_enc)
            if n and n not in candidates:
                candidates.append(n)
        head_enc = _encoding_from_header()
        if head_enc and head_enc not in candidates:
            candidates.append(head_enc)
        for fb in ('utf-8', 'gb18030'):
            if fb not in candidates:
                candidates.append(fb)

        def _decode_with_best(encodings: List[str]) -> Optional[str]:
            best_txt = None
            best_bad = 10**9
            best_enc = None
            for ec in encodings:
                try:
                    txt = html_bytes.decode(ec, errors='replace')
                    bad = txt.count('\ufffd')
                    score = (bad, 0 if ec == 'utf-8' else 1)
                    if bad < best_bad or best_txt is None or score < (best_bad, 1 if best_enc != 'utf-8' else 0):
                        best_txt = txt
                        best_bad = bad
                        best_enc = ec
                except Exception:
                    continue
            return best_txt

        html_content = _decode_with_best(candidates)
        if html_content is not None:
            return html_content
        return resp.text or ''

    # 尝试 https → http 降级
    variations = [url]
    if url.startswith('https://'):
        variations.append('http://' + url[len('https://'):])

    last_exc: Exception | None = None
    for attempt in range(3):
        for u in variations:
            try:
                headers = base_headers.copy()
                headers['user-agent'] = random.choice(user_agents)
                s = requests.Session()
                s.headers.update(headers)
                s.trust_env = False
                resp = s.get(u, timeout=15, verify=False, proxies={'http': None, 'https': None}, allow_redirects=True)
                resp.raise_for_status()
                return _decode_response(resp)
            except requests.exceptions.RequestException as e:
                last_exc = e
                time.sleep(0.8 + random.random() * 0.5)
                continue
    if last_exc:
        raise last_exc
    raise RuntimeError('Failed to fetch url')


def _discover_policy_tabs(index_url: str) -> List[str]:
    """在 zcfb 聚合页上发现“政策发布｜政策解读｜政策图解”三个子栏目链接"""
    html = _fetch_html(index_url)
    soup = BeautifulSoup(html, 'html5lib')
    base_domain = _get_domain(index_url)
    wanted_keys = ['政策发布', '政策解读', '政策图解']
    found: List[str] = []
    for a in soup.find_all('a'):
        text = (a.get_text(strip=True) or '').replace('\xa0', '')
        href = a.get('href') or ''
        if not href:
            continue
        if any(k in text for k in wanted_keys):
            abs_url = urljoin(index_url, href)
            if _same_domain(abs_url, base_domain) and abs_url not in found:
                found.append(abs_url)
        if len(found) >= 3:
            break
    # 追加“政策发布”下的二级分类列表（如 /zcfb/dwmygl/index.html 等）
    sub_urls: List[str] = []
    sub_pat = re.compile(r"/zcfb/[^/]+/index\.html", re.IGNORECASE)
    for a in soup.find_all('a'):
        href = a.get('href') or ''
        if not href or not sub_pat.search(href):
            continue
        abs_url = urljoin(index_url, href)
        if _same_domain(abs_url, base_domain) and abs_url not in found and abs_url not in sub_urls:
            sub_urls.append(abs_url)
    out = found + sub_urls
    _dbg(f"discover tabs: primary={len(found)} subs={len(sub_urls)}")
    return out


def _fallback_policy_tabs(index_url: str) -> List[str]:
    """当页面解析失败时的回退子栏目地址猜测"""
    base = index_url.rsplit('/', 1)[0] + '/'
    guesses = [
        'zcfb/index.html',   # 政策发布
        'zcjd/index.html',   # 政策解读
        'zctj/index.html',   # 政策图解
    ]
    out: List[str] = []
    for g in guesses:
        out.append(urljoin(base, g))
    return out


def _parse_policy_list(list_url: str, base_domain: str, days: int, target_date: Optional[str] = None) -> Dict[str, str]:
    """解析一个政策列表页，返回 {"标题;日期": 详情URL}"""
    few_days = _few_days(days)
    allowed_dates = {target_date} if target_date else set(few_days)
    html = _fetch_html(list_url)
    soup = BeautifulSoup(html, 'html5lib')
    news_url_dict: Dict[str, str] = {}

    # 常见列表容器（同时兼容二级分类列表页）
    candidate_ul_selectors = [
        'ul.txtList_01', 'ul.txtList_02', 'ul.txtList_03',
        'div.list-con ul', 'div.leftbox ul', 'div.m-list ul',
        'div#list ul', 'div.list ul',
        'div.zcfb_list ul', 'div.zcjd_list ul', 'div.zctj_list ul',
        'div.list.f-mt30 ul', 'section.list ul',
    ]
    li_nodes: List = []
    for sel in candidate_ul_selectors:
        ul = soup.select_one(sel)
        if ul:
            li_nodes = ul.find_all('li')
            if li_nodes:
                _dbg(f"list {list_url} using selector '{sel}' li={len(li_nodes)}")
                break

    # dataproxy 回退
    if not li_nodes:
        dp_nodes = _fetch_trs_dataproxy_list(list_url, html)
        for item in dp_nodes:
            title = (item.get('title') or '').strip()
            href = (item.get('href') or '').strip()
            date = (item.get('date') or '').strip()
            if not title or not href:
                continue
            final_url = urljoin(list_url, href)
            if not _same_domain(final_url, base_domain):
                continue
            # 严格：需在窗口内；若列表无日期，尝试详情页解析
            if not date:
                date = _extract_date_from_detail(final_url)
            if date and date in allowed_dates:
                key = f"{title};{date}"
                if key not in news_url_dict:
                    news_url_dict[key] = final_url
        if news_url_dict:
            _dbg(f"list {list_url} dataproxy matched={len(news_url_dict)}")
            return news_url_dict

    # 链接模式回退：直接匹配 /zcfb|/zcjd|/zctj/ 下的文章链接
    if not li_nodes:
        href_pat = re.compile(r"/(zcfb|zcjd|zctj)/.+/art/\d{4}/[a-zA-Z0-9_\-]+\.html", re.IGNORECASE)
        for a in soup.find_all('a'):
            href = a.get('href') or ''
            if not href or not href_pat.search(href):
                continue
            abs_url = urljoin(list_url, href)
            if not _same_domain(abs_url, base_domain):
                continue
            title = a.get('title') or a.get_text(strip=True)
            # 近邻文本尝试拿日期
            parent = a.find_parent('li') or a.parent
            ctx_text = parent.get_text(' ', strip=True) if parent is not None else a.get_text(' ', strip=True)
            date = None
            m = re.search(r'(20\d{2})[\-/\.年](\d{1,2})[\-/\.月](\d{1,2})', ctx_text)
            if not m:
                m = re.search(r'(20\d{2}-\d{2}-\d{2})', ctx_text)
            if m:
                if len(m.groups()) == 3:
                    y, mo, d = m.groups()
                    date = f"{y}-{int(mo):02d}-{int(d):02d}"
                else:
                    date = m.group(1)
            if not date:
                date = _extract_date_from_detail(abs_url)
            # 严格：必须解析出日期且在窗口内
            if date and date in allowed_dates:
                key = f"{title};{date}"
                if key not in news_url_dict:
                    news_url_dict[key] = abs_url
        if news_url_dict:
            _dbg(f"list {list_url} link-pattern matched={len(news_url_dict)}")
            return news_url_dict

    def _extract_date(raw_text: str) -> Optional[str]:
        text = (raw_text or '').strip()
        m = re.search(r'(20\d{2})[\-/\.年](\d{1,2})[\-/\.月](\d{1,2})', text)
        if not m:
            m = re.search(r'(20\d{2}-\d{2}-\d{2})', text)
        if not m:
            return None
        if len(m.groups()) == 3:
            y, mo, d = m.groups()
            return f"{y}-{int(mo):02d}-{int(d):02d}"
        return m.group(1)

    # 第一轮：近 N 天（按 UL/LI 结构）
    for li in li_nodes:
        a_tag = li.find('a')
        if not a_tag:
            continue
        href = a_tag.get('href') or ''
        title = a_tag.get('title') or a_tag.get_text(strip=True)
        span_tag = li.find('span')
        li_text = li.get_text(' ', strip=True)
        date = _extract_date(span_tag.get_text() if span_tag else li_text)
        final_url = urljoin(list_url, href)
        if not _same_domain(final_url, base_domain):
            continue
        if not date:
            date = _extract_date_from_detail(final_url)
        if date and date in allowed_dates:
            news_url_dict[f"{title};{date}"] = final_url
    _dbg(f"list {list_url} final in-window items={len(news_url_dict)}")

    # 补充扫描：即使存在 UL/LI，也额外在整页扫描符合规则的详情链接
    # 场景：新稿可能出现在“焦点区/顶部卡片”而不在 UL/LI 中
    href_pat = re.compile(r"/(zcfb|zcjd|zctj)/.+/art/\d{4}/[a-zA-Z0-9_\-]+\.html", re.IGNORECASE)
    existed = set(news_url_dict.values())
    added = 0
    for a in soup.find_all('a'):
        href = a.get('href') or ''
        if not href or not href_pat.search(href):
            continue
        abs_url = urljoin(list_url, href)
        if abs_url in existed or not _same_domain(abs_url, base_domain):
            continue
        title = a.get('title') or a.get_text(strip=True)
        parent = a.find_parent('li') or a.parent
        ctx_text = parent.get_text(' ', strip=True) if parent is not None else a.get_text(' ', strip=True)
        date = _extract_date(ctx_text)
        if not date:
            date = _extract_date_from_detail(abs_url)
        if date and date in allowed_dates:
            key = f"{title};{date}"
            if key not in news_url_dict:
                news_url_dict[key] = abs_url
                existed.add(abs_url)
                added += 1
    if added:
        _dbg(f"list {list_url} page-scan extra added={added}")

    # 不再做“前10条不限日期”回退；严格日期窗口

    return news_url_dict

def _extract_date_from_detail(detail_url: str) -> Optional[str]:
    """从详情页解析发布日期：先取 head meta[PubDate]，再回退正文信息块。"""
    try:
        html = _fetch_html(detail_url)
    except Exception:
        return None
    # meta PubDate/MakeTime（允许含时间，只取日期部分）
    m = re.search(r'name=["\'](?:PubDate|MakeTime)["\'][^>]*content=["\'](20\d{2}-\d{2}-\d{2})', html, re.IGNORECASE)
    if not m:
        # 带时间的 PubDate: 2025-09-26 17:34 或 2025-09-26T17:34
        m = re.search(r'name=["\'](?:PubDate|MakeTime)["\'][^>]*content=["\'](20\d{2}-\d{2}-\d{2})[^"\']*', html, re.IGNORECASE)
    if m:
        d = m.group(1)
        _dbg(f"detail date meta PubDate={d} url={detail_url}")
        return d
    # 发文日期（中文）块优先
    m4 = re.search(r'【发文日期】\s*([0-9]{4})年\s*([0-9]{1,2})月\s*([0-9]{1,2})日', html)
    if m4:
        y, mo, d = m4.groups()
        try:
            dd = f"{y}-{int(mo):02d}-{int(d):02d}"
            _dbg(f"detail date info-block={dd} url={detail_url}")
            return dd
        except Exception:
            pass
    # 形如 2025年09月26日 / 2025-09-26
    m2 = re.search(r'(20\d{2})[\./-]?年?(\d{1,2})[\./-]?月?(\d{1,2})日?', html)
    if m2:
        y, mo, d = m2.groups()
        try:
            dd = f"{y}-{int(mo):02d}-{int(d):02d}"
            _dbg(f"detail date generic-cn={dd} url={detail_url}")
            return dd
        except Exception:
            pass
    m3 = re.search(r'(20\d{2}-\d{2}-\d{2})', html)
    if m3:
        dd = m3.group(1)
        _dbg(f"detail date generic-iso={dd} url={detail_url}")
        return dd
    return None

def _get_domain(url: str) -> str:
    try:
        netloc = urlparse(url).netloc.lower()
        if netloc.startswith('www.'):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return ''


def _same_domain(url: str, base_domain: str) -> bool:
    try:
        d = _get_domain(url)
        return d == (base_domain[4:] if base_domain.startswith('www.') else base_domain) or d == base_domain
    except Exception:
        return False


def _strip_unwanted_tags(soup_node):
    for tag in soup_node.find_all(['style', 'script', 'noscript', 'link', 'meta']):
        try:
            tag.decompose()
        except Exception:
            continue


def _clean_text(text: str) -> str:
    if not text:
        return ''
    # 去掉明显的 CSS 代码片段
    if text.count('{') > 2 and ('font-family' in text or 'margin' in text):
        text = re.sub(r'\{[^\}]*\}', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _few_days(n: int):
    """返回北京时区下，包含今天在内的最近 n 天日期字符串列表。
    说明：运行环境可能不在东八区，导致当天（北京时区）的内容被过滤。
    这里改为按 UTC+8 计算“今天”，避免误差。
    """
    from datetime import datetime, timedelta, timezone
    beijing = timezone(timedelta(hours=8))
    base = datetime.now(beijing).date()
    return [ (base - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(0, n) ]


def _extract_article_text_from_node(node) -> str:
    """从节点中抽取更像正文的段落，过滤“发布单位/文号/日期”等提示字段"""
    # 移除明显的“信息栏”段落
    def is_meta_line(t: str) -> bool:
        t = t.strip()
        if not t:
            return True
        bad_prefix = (
            '【发布单位】', '【发文日期】', '【发布时间】', '【发布文号】',
            '（此件公开发布）', '（此件主动公开）', '附件：', '来源：', '责任编辑：',
        )
        if t.startswith(bad_prefix):
            return True
        # 单纯日期/编号行
        if re.fullmatch(r'20\d{2}[年/-]\d{1,2}[月/-]\d{1,2}日?', t):
            return True
        if len(t) <= 2:  # 极短噪声
            return True
        return False

    # 优先拼接 <p>
    ps = node.find_all('p')
    texts: List[str] = []
    for p in ps:
        s = _clean_text(p.get_text(' ', strip=True))
        if s and not is_meta_line(s):
            texts.append(s)
    if not texts:
        s = _clean_text(node.get_text(' ', strip=True))
        # 再次切分过滤
        parts = [x for x in re.split(r'[\n\r]+', s) if x and not is_meta_line(x)]
        s2 = ' '.join(parts)
        return s2[:2000]
    return ' '.join(texts)[:2000]


def _select_main_content_node(soup) -> Optional[BeautifulSoup]:
    """在常见正文容器候选中，选择文本量最大的节点"""
    candidates = [
        ('div', 'art-con art-con-bottonmLine'),
        ('div', 'TRS_Editor'),
        ('div', 'zoom'),
        ('div', 'article-con'),
        ('div', 'conTxt'),
        ('div', 'content'),
        ('div', 'article'),
        ('div', 'zoomcon'),
        ('div', 'conBox'),
        ('div', 'container'),
    ]
    best = None
    best_len = 0
    for tag, cls in candidates:
        # 使用 CSS 选择器，支持多 class
        cls_selector = '.'.join(cls.split())
        nodes = soup.select(f"{tag}.{cls_selector}")
        for n in nodes:
            txt = _clean_text(n.get_text(' ', strip=True))
            if len(txt) > best_len:
                best_len = len(txt)
                best = n
    # 如果依然没有，退化为页面中段落总量最多的块级 div
    if best is None:
        for n in soup.find_all('div')[:50]:
            pcount = len(n.find_all('p'))
            if pcount >= 3:
                txt = _clean_text(n.get_text(' ', strip=True))
                if len(txt) > best_len:
                    best = n
                    best_len = len(txt)
    return best


def _pick_best_node(nodes: List) -> Optional[BeautifulSoup]:
    """在候选节点中选择最佳正文节点：优先 ergodic=article，其次 p 数/文本长度"""
    if not nodes:
        return None
    # 优先选带 ergodic="article" 的
    for n in nodes:
        try:
            if (n.get('ergodic') or '').lower() == 'article':
                return n
        except Exception:
            continue
    # 次选：p 段落多且文本长
    best = None
    best_score = -1
    for n in nodes:
        try:
            pcount = len(n.find_all('p'))
            tlen = len(_clean_text(n.get_text(' ', strip=True)))
            score = pcount * 1000 + tlen
            if score > best_score:
                best = n
                best_score = score
        except Exception:
            continue
    return best


def _prune_non_content(node) -> None:
    """移除常见的非正文结构块，例如信息栏、分享、文章来源、责任编辑等"""
    bad_ids = ['info', 'source', 'share', 'editor', 'top', 'bottom', 'breadcrumb']
    bad_classes = [
        'info', 'source', 'share', 'share-box', 'meta', 'article-meta', 'statement',
        'print', 'editor', 'editorName', 'sourceline', 'pubtime', 'tags',
    ]
    # 移除带有这些 id/class 的块级元素
    for el in list(node.find_all(True)):
        try:
            cid = (el.get('id') or '').lower()
            classes = ' '.join(el.get('class') or []).lower()
            if cid in bad_ids:
                el.decompose()
                continue
            if any(bc in classes for bc in bad_classes):
                el.decompose()
                continue
        except Exception:
            continue
