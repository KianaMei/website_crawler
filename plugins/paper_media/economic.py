"""
经济日报独立插件

每个插件文件都需要导出名为 `handler` 的函数，作为工具入口。
"""

from typing import List
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from pydantic import BaseModel, Field
from typing import Optional, List, Tuple, TypeVar, Generic
import logging
import requests
import time
import random
import re

T = TypeVar('T')

class Args(Generic[T]):
    def __init__(self, input_data: T):
        self.input = input_data

class News(BaseModel):
    title: str
    url: str
    origin: str
    summary: str
    publish_date: str

class PaperInput(BaseModel):
    source: str = Field(default="economic", description="纸媒来源")
    max_items: int = Field(default=10, ge=1, le=50, description="最多抓取条数")
    date: Optional[str] = Field(default=None, description="指定日期（YYYY-MM-DD）")

class PaperOutput(BaseModel):
    news_list: Optional[List[News]] = Field(default=None, description="新闻列表")
    status: str = Field(default="OK", description="响应状态标记")
    err_code: Optional[str] = Field(default=None, description="错误码（可选）")
    err_info: Optional[str] = Field(default=None, description="错误信息（可选）")

def fetch_url(url: str) -> str:
    """获取URL内容"""
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
            resp = sess.get(url, timeout=20, verify=False, proxies={'http': None, 'https': None})
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
                    cands.append(c)

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

def find_available_date(get_pages_func, date: Optional[str], max_back_days: int = 7) -> Tuple[str, str, str]:
    """查找可用日期"""
    import datetime
    def _today_parts():
        today = datetime.date.today()
        return f"{today.year}", f"{today.month:02d}", f"{today.day:02d}"
    
    if date:
        try:
            y, m, d = date.split('-')
            if get_pages_func(y, m, d):
                return y, m, d
        except Exception:
            pass
    y0, m0, d0 = _today_parts()
    base_date = datetime.date(int(y0), int(m0), int(d0))
    for i in range(max_back_days + 1):
        day = base_date - datetime.timedelta(days=i)
        y, m, d = f"{day.year}", f"{day.month:02d}", f"{day.day:02d}"
        try:
            if get_pages_func(y, m, d):
                return y, m, d
        except Exception:
            continue
    return y0, m0, d0

def safe_handler(origin_name: str):
    """安全处理装饰器"""
    def decorator(func):
        def wrapper(args: Args[PaperInput]) -> PaperOutput:
            logger = getattr(args, "logger", logging.getLogger(__name__))
            try:
                inp_obj = getattr(args, "input", None)
                if isinstance(inp_obj, dict):
                    max_items = int(inp_obj.get("max_items") or 10)
                    date_str = inp_obj.get("date")
                else:
                    max_items = int((getattr(inp_obj, "max_items", None) or 10))
                    date_str = getattr(inp_obj, "date", None)
                
                return func(args, max_items, date_str, origin_name, logger)
            except Exception as e:
                logger.exception(f"{origin_name} handler failed")
                return PaperOutput(news_list=None, status="ERROR", err_code="PLUGIN_ERROR", err_info=str(e))
        return wrapper
    return decorator


Metadata = {
    "name": "get_economic_news",
    "description": "获取经济日报新闻",
    "input": PaperInput.model_json_schema(),
    "output": PaperOutput.model_json_schema(),
}


def get_page_list(year: str, month: str, day: str):
    """获取经济日报指定日期的版面列表"""
    base_url = 'http://paper.ce.cn/pc'
    base_layout = f'{base_url}/layout/{year}{month}/{day}/'
    url = urljoin(base_layout, 'node_01.html')
    html = fetch_url(url)
    s = BeautifulSoup(html, 'html.parser')
    out = []
    seen = set()
    
    for a in s.find_all('a'):
        href = (a.get('href') or '').strip()
        name = a.get_text(strip=True)
        if not href or not href.endswith('.html'):
            continue
        if 'node_' not in href:
            continue
        page_url = urljoin(url, href)
        if page_url in seen:
            continue
        seen.add(page_url)
        valid_name = ''.join(ch for ch in name if ch not in r'\/:*?"<>|') or '第01版'
        out.append((page_url, valid_name))
    
    if not any(x[0].endswith('node_01.html') for x in out):
        out.insert(0, (url, '第01版'))
    return out


def get_title_list(year: str, month: str, day: str, page_url: str):
    """获取指定版面的文章链接列表"""
    html = fetch_url(page_url)
    s = BeautifulSoup(html, 'html.parser')
    links = []
    seen = set()
    
    for a in s.find_all('a'):
        href = (a.get('href') or '').strip()
        if not href.endswith('.html'):
            continue
        if 'content_' not in href:
            continue
        abs_url = urljoin(page_url, href)
        if abs_url in seen:
            continue
        seen.add(abs_url)
        links.append(abs_url)
    return links


def best_content_div(soup: BeautifulSoup):
    """智能选择最佳内容容器"""
    priority = ['#content', '#ozoom', 'div.content', 'div#zoom', 'div#articleContent', 'div.article']
    for sel in priority:
        el = soup.select_one(sel)
        if el:
            return el
    
    best = None
    best_len = 0
    for div in soup.find_all('div'):
        ps = div.find_all('p')
        if not ps:
            continue
        txt = '\n'.join(p.get_text(strip=True) for p in ps)
        if len(txt) > best_len:
            best = div
            best_len = len(txt)
    return best


def parse_article(html: str):
    """解析经济日报文章内容"""
    s = BeautifulSoup(html, 'html.parser')
    title_text = ''
    if s.h1 and s.h1.get_text(strip=True):
        title_text = s.h1.get_text(strip=True)
    elif s.h2 and s.h2.get_text(strip=True):
        title_text = s.h2.get_text(strip=True)
    elif s.title:
        title_text = s.title.get_text(strip=True)
    title_valid = ''.join(i for i in title_text if i not in r'\/:*?"<>|')
    
    h3 = s.h3.get_text(strip=True) if s.h3 else ''
    h2 = s.h2.get_text(strip=True) if s.h2 else ''
    
    container = best_content_div(s)
    content_body = ''
    if container:
        p_list = container.find_all('p')
        for p in p_list:
            content_body += p.get_text() + '\n'
    content_body = content_body.strip()
    summary = content_body.strip()
    
    content_full = ''
    content_full += (h3 + '\n') if h3 else ''
    content_full += (title_text + '\n') if title_text else ''
    if h2 and (not title_text or h2 != title_text):
        content_full += (h2 + '\n')
    content_full += content_body
    
    return content_full, title_valid, title_text, content_body, summary


@safe_handler("经济日报")
def handler(args: Args[PaperInput], max_items: int, date_str: str, origin_name: str, logger) -> PaperOutput:
    """经济日报新闻抓取处理函数"""
    y, m, d = find_available_date(get_page_list, date_str)
    news_list: List[News] = []
    
    for page_url, _ in get_page_list(y, m, d):
        if len(news_list) >= max_items:
            break
        for url in get_title_list(y, m, d, page_url):
            if len(news_list) >= max_items:
                break
            html = fetch_url(url)
            _, _, title, body, summary = parse_article(html)
            news_list.append(News(
                title=title or '', 
                url=url, 
                origin=origin_name, 
                summary=summary or body or '', 
                publish_date=f"{y}-{m}-{d}"
            ))
    
    status = 'OK' if news_list else 'EMPTY'
    return PaperOutput(
        news_list=news_list or None, 
        status=status, 
        err_code=None if news_list else 'NO_DATA', 
        err_info=None if news_list else 'No news parsed'
    )