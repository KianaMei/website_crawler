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
from typing import Optional, List, Tuple

import logging
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import time
import random


class News(BaseModel):
    title: str
    url: str
    origin: str
    summary: str
    publish_date: str


class Input(BaseModel):
    categories: Optional[List[str]] = Field(default=None, description="发改委栏目（例如 ['fzggwl','gg']）")
    max_pages: int = Field(default=1, ge=1, description="列表最大翻页数")
    max_items: Optional[int] = Field(default=10, description="总抓取数量上限（列表收集软上限）")


class Output(BaseModel):
    news_list: Optional[List[News]] = Field(default=None, description="新闻列表")
    status: str = Field(default="OK", description="响应状态标记")
    err_code: Optional[str] = Field(default=None, description="错误码（可选）")
    err_info: Optional[str] = Field(default=None, description="错误信息（可选）")


Metadata = {
    "name": "get_gov_ndrc",
    "description": "抓取发改委各栏目并返回结果",
    "input": Input.model_json_schema(),
    "output": Output.model_json_schema(),
}


def handler(args: Args[Input]) -> Output:
    logger = getattr(args, "logger", logging.getLogger(__name__))
    inp_obj = getattr(args, "input", None)
    if isinstance(inp_obj, dict):
        cats = inp_obj.get("categories")
        mp = inp_obj.get("max_pages")
        mi = inp_obj.get("max_items")
    else:
        cats = getattr(inp_obj, "categories", None)
        mp = getattr(inp_obj, "max_pages", None)
        mi = getattr(inp_obj, "max_items", None)
    try:
        cats = cats or list(POLICY_CATEGORIES.keys())
        try:
            max_pages = int(mp) if mp is not None else 1
        except Exception:
            max_pages = 1
        try:
            per_cat_limit = int(mi) if mi is not None else 20
        except Exception:
            per_cat_limit = 20
        from datetime import datetime, timedelta, date as _date
        today = datetime.today().date()
        earliest = today - timedelta(days=2)

        # 新逻辑：
        # 1) 若任一栏目存在当天信息，则聚合所有栏目的全部“当天”信息；不限制条数
        # 2) 若所有栏目均无当天信息，则回退聚合“近三天”信息；若仍为空，返回错误
        # 3) 最终按发布日期从新到旧排序
        def _to_date(s: str):
            try:
                y, m, d = s.split('-')
                return _date(int(y), int(m), int(d))
            except Exception:
                return None

        all_todays: List[Tuple[str, str, str]] = []
        all_window: List[Tuple[str, str, str]] = []

        for key in cats:
            conf = POLICY_CATEGORIES.get(key)
            if not conf:
                continue
            page = 1
            while True:
                url = conf['first_page'] if page == 1 else conf['page_pattern'].format(page - 1)
                html = _fetch_html(url)
                rows = _parse_list(html, key)
                if not rows:
                    break
                for title, link, dstr in rows:
                    d = _to_date(dstr or '')
                    if not d:
                        continue
                    if d == today:
                        all_todays.append((title, link, dstr))
                    elif earliest <= d <= today:
                        all_window.append((title, link, dstr))
                if page >= max_pages:
                    break
                page += 1

        selected_rows: List[Tuple[str, str, str]]
        if all_todays:
            selected_rows = all_todays
        else:
            selected_rows = all_window

        if not selected_rows:
            return Output(news_list=None, status='EMPTY', err_code='NO_RECENT', err_info='今天无更新且三天内没有内容')

        # 构造结果并按日期倒序
        items: List[News] = []
        seen_urls = set()
        for title, link, dstr in selected_rows:
            if link in seen_urls:
                continue
            seen_urls.add(link)
            summary = _parse_detail_summary(link)
            items.append(News(title=title, url=link, origin='国家发展改革委', summary=summary, publish_date=dstr or ''))

        def _gkey(n: News):
            try:
                from datetime import datetime as _dt
                return _dt.strptime(n.publish_date or '', '%Y-%m-%d')
            except Exception:
                from datetime import datetime as _dt
                return _dt.min
        items.sort(key=_gkey, reverse=True)

        return Output(news_list=items, status='OK', err_code=None, err_info=None)

        items: List[News] = []
        for key in cats:
            conf = POLICY_CATEGORIES.get(key)
            if not conf:
                continue
            page = 1
            acc: List[Tuple[str, str, str]] = []
            while True:
                url = conf['first_page'] if page == 1 else conf['page_pattern'].format(page - 1)
                html = _fetch_html(url)
                rows = _parse_list(html, key)
                if not rows:
                    break
                acc.extend(rows)
                if per_cat_limit and len(acc) >= per_cat_limit:
                    acc = acc[:per_cat_limit]
                    break
                if page >= max_pages:
                    break
                page += 1

            def _to_date(s: str):
                try:
                    y, m, d = s.split('-')
                    return _date(int(y), int(m), int(d))
                except Exception:
                    return None

            todays: List[Tuple[str, str, str]] = []
            windows: List[Tuple[str, str, str]] = []
            for title, link, dstr in acc:
                d = _to_date(dstr or '')
                if not d:
                    continue
                if d == today:
                    todays.append((title, link, dstr))
                elif earliest <= d <= today:
                    windows.append((title, link, dstr))

            selected: List[Tuple[str, str, str]]
            if todays:
                selected = todays
            else:
                windows.sort(key=lambda x: (_to_date(x[2]) or earliest), reverse=True)
                selected = windows[:3]

            for title, link, dstr in selected:
                summary = _parse_detail_summary(link)
                items.append(News(title=title, url=link, origin='���ҷ���ί', summary=summary, publish_date=dstr or ''))

        # 全局按日期降序排序
        def _gkey(n: News):
            try:
                from datetime import datetime as _dt
                return _dt.strptime(n.publish_date or '', '%Y-%m-%d')
            except Exception:
                from datetime import datetime as _dt
                return _dt.min
        items.sort(key=_gkey, reverse=True)
        status = 'OK' if items else 'EMPTY'
        return Output(news_list=items or None, status=status, err_code=None if items else 'NO_DATA', err_info=None if items else 'No news parsed')
    except Exception as e:
        logger.exception("gov_ndrc handler failed")
        return Output(news_list=None, status="ERROR", err_code="PLUGIN_ERROR", err_info=str(e))


POLICY_CATEGORIES = {
    'fzggwl': {
        'name': '��չ�ĸ�ί',
        'category_path': '/xxgk/zcfb/fzggwl',
        'first_page': 'https://www.ndrc.gov.cn/xxgk/zcfb/fzggwl/index.html',
        'page_pattern': 'https://www.ndrc.gov.cn/xxgk/zcfb/fzggwl/index_{}.html',
    },
    'ghxwj': {
        'name': '�淶���ļ�',
        'category_path': '/xxgk/zcfb/ghxwj',
        'first_page': 'https://www.ndrc.gov.cn/xxgk/zcfb/ghxwj/index.html',
        'page_pattern': 'https://www.ndrc.gov.cn/xxgk/zcfb/ghxwj/index_{}.html',
    },
    'ghwb': {
        'name': '�滮�ı�',
        'category_path': '/xxgk/zcfb/ghwb',
        'first_page': 'https://www.ndrc.gov.cn/xxgk/zcfb/ghwb/index.html',
        'page_pattern': 'https://www.ndrc.gov.cn/xxgk/zcfb/ghwb/index_{}.html',
    },
    'gg': {
        'name': '����',
        'category_path': '/xxgk/zcfb/gg',
        'first_page': 'https://www.ndrc.gov.cn/xxgk/zcfb/gg/index.html',
        'page_pattern': 'https://www.ndrc.gov.cn/xxgk/zcfb/gg/index_{}.html',
    },
    'tz': {
        'name': '֪ͨ',
        'category_path': '/xxgk/zcfb/tz',
        'first_page': 'https://www.ndrc.gov.cn/xxgk/zcfb/tz/index.html',
        'page_pattern': 'https://www.ndrc.gov.cn/xxgk/zcfb/tz/index_{}.html',
    },
}

DATE_RE = re.compile(r"(20\d{2})[-/.��]\s?(\d{1,2})[-/.��]\s?(\d{1,2})[��]?")


def _fetch_html(url: str) -> str:
    DEFAULT_HEADERS = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
        'Accept-Language': 'zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }
    retries = 3
    delay = 1.0
    sess = requests.Session()
    sess.headers.update(DEFAULT_HEADERS)
    sess.trust_env = False
    for attempt in range(retries):
        try:
            resp = sess.get(url, timeout=15, verify=False, proxies={'http': None, 'https': None})
            resp.raise_for_status()
            ct = resp.headers.get('content-type', '') or ''
            data = resp.content

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
                return _norm(resp.encoding) if resp.encoding else None

            cands: List[str] = []
            for c in (_enc_from_meta(data), resp.apparent_encoding and _norm(resp.apparent_encoding), _enc_from_header(), 'utf-8','gb18030'):
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


def _safe_join_url(href: str, category_path: str) -> str:
    if href.startswith('http://') or href.startswith('https://'):
        return href
    href = href.lstrip('./')
    base = 'https://www.ndrc.gov.cn'
    if category_path and not href.startswith('/'):
        return f"{base}{category_path}/{href}"
    return urljoin(base, href)


def _extract_date(text: str) -> Optional[str]:
    m = DATE_RE.search(text or '')
    if m:
        y, mo, d = m.groups()
        try:
            dt = _dt(int(y), int(mo), int(d))
            return dt
        except Exception:
            return None
    m2 = re.search(r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})", text or '')
    if m2:
        y, mo, d = m2.groups()
        try:
            dt = _dt(int(y), int(mo), int(d))
            return dt
        except Exception:
            return None
    return None


def _dt(y: int, m: int, d: int) -> str:
    return f"{y:04d}-{m:02d}-{d:02d}"


def _find_content_node(soup: BeautifulSoup):
    for tag, attrs in [
        ('div', {'class': 'article_con'}),
        ('div', {'class': 'TRS_Editor'}),
        ('div', {'class': 'content'}),
        ('div', {'class': 'article-content'}),
        ('div', {'class': 'main-content'}),
        ('div', {'id': 'zoom'}),
        ('article', {}),
    ]:
        node = soup.find(tag, attrs=attrs)
        if node:
            return node
    return soup


def _parse_list(html: str, cat_key: str) -> List[Tuple[str, str, str]]:
    soup = BeautifulSoup(html or '', 'html5lib')
    items: List[Tuple[str, str, str]] = []
    for li in soup.find_all('li'):
        a = li.find('a', href=True)
        date_span = li.find('span')
        if not a or not date_span:
            continue
        title = (a.get('title') or a.get_text(strip=True) or '').strip()
        href = a['href'].strip()
        url = _safe_join_url(href, POLICY_CATEGORIES[cat_key]['category_path'])
        date_text = date_span.get_text(strip=True)
        date = _extract_date(date_text) or ''
        if title and url:
            items.append((title, url, date))
    return items


def _parse_detail_summary(url: str) -> str:
    html = _fetch_html(url)
    soup = BeautifulSoup(html or '', 'html5lib')
    node = _find_content_node(soup)
    text = node.get_text('\n', strip=True)
    # 保持全文（仅标准化空白符）
    t = re.sub(r"\s+", " ", text).strip()
    return t
