"""
每个插件文件都需要导出名为 `handler` 的函数，作为工具入口。

参数:
- args: 入口函数的参数对象
- args.input: 输入参数（例如 args.input.xxx）
- args.logger: 日志记录器，由运行时注入

返回: Output
"""

from runtime import Args
from pydantic import BaseModel, Field
from typing import Optional, List, Tuple, Dict

import logging
import re
import time
import random
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


class News(BaseModel):
    title: str
    url: str
    origin: str
    summary: str
    publish_date: str


class Input(BaseModel):
    channels: Optional[List[str]] = Field(default=None, description="中国工商联（政策速递）频道：zy|bw|df|qggsl|jd（None=全部）")
    max_pages: int = Field(default=1, ge=0, description="列表最大翻页数（0 表示不抓取列表页）")
    max_items: Optional[int] = Field(default=5, ge=0, description="每频道最大抓取条数（0 表示不抓取条目）")


class Output(BaseModel):
    news_list: Optional[List[News]] = Field(default=None)
    status: str = Field(default="OK")
    err_code: Optional[str] = Field(default=None)
    err_info: Optional[str] = Field(default=None)


Metadata = {
    "name": "assoc_acfic_policy",
    "description": "中国工商联（政策速递）频道抓取器",
    "input": Input.model_json_schema(),
    "output": Output.model_json_schema(),
}


ACFIC_CHANNELS: Dict[str, Dict[str, str]] = {
    'zy': {
        'name': 'Central',
        'base': 'https://www.acfic.org.cn/zcsd/zy/',
        'first_page': 'https://www.acfic.org.cn/zcsd/zy/index.html',
        'page_pattern': 'https://www.acfic.org.cn/zcsd/zy/index_{}.html',
        'origin': '全国工商联',
    },
    'bw': {
        'name': 'Ministries',
        'base': 'https://www.acfic.org.cn/zcsd/bw/',
        'first_page': 'https://www.acfic.org.cn/zcsd/bw/index.html',
        'page_pattern': 'https://www.acfic.org.cn/zcsd/bw/index_{}.html',
        'origin': '全国工商联',
    },
    'df': {
        'name': 'Local',
        'base': 'https://www.acfic.org.cn/zcsd/df/',
        'first_page': 'https://www.acfic.org.cn/zcsd/df/index.html',
        'page_pattern': 'https://www.acfic.org.cn/zcsd/df/index_{}.html',
        'origin': '全国工商联',
    },
    'qggsl': {
        'name': 'ACFIC',
        'base': 'https://www.acfic.org.cn/zcsd/qggsl/',
        'first_page': 'https://www.acfic.org.cn/zcsd/qggsl/index.html',
        'page_pattern': 'https://www.acfic.org.cn/zcsd/qggsl/index_{}.html',
        'origin': '全国工商联',
    },
    'jd': {
        'name': 'Interpretation',
        'base': 'https://www.acfic.org.cn/zcsd/jd/',
        'first_page': 'https://www.acfic.org.cn/zcsd/jd/index.html',
        'page_pattern': 'https://www.acfic.org.cn/zcsd/jd/index_{}.html',
        'origin': '全国工商联',
    },
}


def handler(args: Args[Input]) -> Output:
    logger = getattr(args, "logger", logging.getLogger(__name__))
    inp = getattr(args, "input", None)
    channels = None
    max_pages = 1
    max_items: Optional[int] = 5
    if isinstance(inp, dict):
        channels = inp.get('channels')
        mp = inp.get('max_pages')
        mi = inp.get('max_items')
    else:
        channels = getattr(inp, 'channels', None)
        mp = getattr(inp, 'max_pages', None)
        mi = getattr(inp, 'max_items', None)
    # 规范化 max_pages：None/非法 -> 1；允许 0 表示不抓取列表页
    try:
        max_pages = int(mp) if mp is not None else 1
        if max_pages < 0:
            max_pages = 1
    except Exception:
        max_pages = 1
    # 规范化 max_items：None/非法 -> 5；允许 0 表示不抓取条目
    try:
        max_items = int(mi) if mi is not None else 5
        if max_items is not None and max_items < 0:
            max_items = 5
    except Exception:
        max_items = 5

    try:
        use_channels = channels or list(ACFIC_CHANNELS.keys())
        news_list: List[News] = []
        any_filtered_due_to_time = False  # 是否因为“当天/近三天”筛选而被清空
        diag_summaries: List[str] = []    # 记录每频道 采集数->入选数，便于空结果说明
        for ch in use_channels:
            if ch not in ACFIC_CHANNELS:
                continue
            conf = ACFIC_CHANNELS[ch]
            per = 0
            page = 1
            start_idx = len(news_list)
            # 今日字符串，用于采集阶段判断“今天”不占配额
            try:
                from datetime import datetime as _dt
                today_str = _dt.today().strftime('%Y-%m-%d')
            except Exception:
                today_str = ''
            while page <= max_pages:
                url = conf['first_page'] if page == 1 else conf['page_pattern'].format(page - 1)
                html = _fetch_html(url)
                if not html:
                    break
                for title, link, date in _parse_list(html, conf['base']):
                    is_today = (date == today_str)
                    if is_today or (max_items is None or per < max_items):
                        summary = _parse_detail_summary(link)
                        news_list.append(News(title=title, url=link, origin=conf['origin'], summary=summary, publish_date=date or ''))
                        if not is_today:
                            per += 1
                page += 1
            # 根据“当天优先/近三天最多3条”重排当前频道新增内容（无命中则清空该频道新增，不做兜底）
            try:
                from datetime import datetime, timedelta, date as _date
                today = datetime.today().date()
                earliest = today - timedelta(days=2)
                def _to_date(s: str):
                    try:
                        y, m, d = s.split('-')
                        return _date(int(y), int(m), int(d))
                    except Exception:
                        return None
                bucket = news_list[start_idx:]
                todays = [n for n in bucket if _to_date(n.publish_date or '') == today]
                selected = []
                if todays:
                    selected = todays
                else:
                    windows = [n for n in bucket if (lambda d: d and (earliest <= d <= today))(_to_date(n.publish_date or ''))]
                    windows.sort(key=lambda n: (_to_date(n.publish_date or '') or earliest), reverse=True)
                    selected = windows[:3]
                if len(bucket) > 0 and len(selected) == 0:
                    any_filtered_due_to_time = True
                news_list[start_idx:] = selected
                # 修正 per，避免后续分页判断受影响
                per = len(selected)
                # 记录诊断摘要
                diag_summaries.append(f"{ch}:{len(bucket)}->{len(selected)}")
            except Exception:
                pass
        # 全局按日期降序排序
        try:
            from datetime import datetime as _dt
            def _gkey(n: News):
                try:
                    return _dt.strptime(n.publish_date or '', '%Y-%m-%d')
                except Exception:
                    return _dt.min
            news_list = sorted(news_list, key=_gkey, reverse=True)
        except Exception:
            pass
        status = 'OK' if news_list else 'EMPTY'
        if news_list:
            return Output(news_list=news_list, status=status, err_code=None, err_info=None)
        else:
            # 若因“当天/近三天”筛选导致为空，返回明确提示
            if any_filtered_due_to_time:
                return Output(news_list=None, status='EMPTY', err_code='NO_RECENT', err_info='今天无更新，且最近三天均无内容')
            # 其它情况：列表解析为空/请求失败/日期无法解析
            detail = ('; '.join(diag_summaries)) if diag_summaries else 'no channels or no items parsed'
            return Output(news_list=None, status='EMPTY', err_code='NO_DATA', err_info=f'No data (parsed/selected summary: {detail})')
    except Exception as e:
        logger.exception('assoc_acfic_policy failed')
        return Output(status='ERROR', err_code='PLUGIN_ERROR', err_info=str(e))


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


def _extract_date(text: str) -> Optional[str]:
    s = (text or '').strip()
    s = s.replace('年', '-').replace('月', '-').replace('日', '')
    m = re.search(r"(20\d{2})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{1,2})", s)
    if m:
        y, mo, d = m.groups()
        try:
            from datetime import datetime
            dt = datetime(int(y), int(mo), int(d))
            return dt.strftime('%Y-%m-%d')
        except Exception:
            return None
    m2 = re.search(r"(20\d{2}-\d{1,2}-\d{1,2})", s)
    if m2:
        return m2.group(1)
    return None


def _find_content_node(soup: BeautifulSoup):
    for tag, attrs in [
        ('div', {'class': 'TRS_Editor'}),
        ('div', {'class': 'zhengwen'}),
        ('div', {'class': 'article'}),
        ('div', {'class': 'content'}),
        ('div', {'id': 'zoom'}),
        ('article', {}),
    ]:
        node = soup.find(tag, attrs=attrs)
        if node:
            return node
    return soup


def _parse_list(html: str, base_url: str) -> List[Tuple[str, str, str]]:
    soup = BeautifulSoup(html, 'html5lib')
    container = soup.find('div', class_='right_qlgz') or soup
    items: List[Tuple[str, str, str]] = []
    for ul in container.find_all('ul'):
        for li in ul.find_all('li'):
            a = li.find('a', href=True)
            if not a:
                continue
            title_span = a.find('span')
            # 日期通常不在 <a> 内，优先在 li 级查找
            date_span = li.find('span', class_='time') or a.find('span', class_='time')
            title = (title_span.get_text(strip=True) if title_span else a.get_text(strip=True) or '').strip()
            href = a['href'].strip()
            url = urljoin(base_url, href)
            # 尽量缩小日期文本范围
            date_text = date_span.get_text(strip=True) if date_span else (li.find('span').get_text(strip=True) if li.find('span') else li.get_text(" ", strip=True))
            date = _extract_date(date_text) or ''
            if title and url:
                items.append((title, url, date))
    return items


def _parse_detail_summary(url: str) -> str:
    html = _fetch_html(url)
    if not html:
        return ''
    soup = BeautifulSoup(html, 'html5lib')
    node = _find_content_node(soup)
    text = node.get_text('\n', strip=True)
    t = re.sub(r"\s+", " ", text).strip()
    return t
