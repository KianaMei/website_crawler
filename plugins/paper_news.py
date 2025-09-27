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
import datetime
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
import time
import random


class News(BaseModel):
    title: str
    url: str
    origin: str
    summary: str
    publish_date: str


class Input(BaseModel):
    source: str = Field(default="all", description="人民|光明|经济|求是|新华|经参|all")
    max_items: int = Field(default=10, ge=1, le=50, description="最多抓取条数")
    since_days: int = Field(default=3, ge=1, le=365, description="近 N 天窗口")
    date: Optional[str] = Field(default=None, description="指定日期（YYYY-MM-DD）")


class Output(BaseModel):
    news_list: Optional[List[News]] = Field(default=None, description="新闻列表")
    status: str = Field(default="OK", description="响应状态标记")
    err_code: Optional[str] = Field(default=None, description="错误码（可选）")
    err_info: Optional[str] = Field(default=None, description="错误信息（可选）")


Metadata = {
    "name": "get_paper_news",
    "description": "汇总主流纸媒来源并返回结果",
    "input": Input.model_json_schema(),
    "output": Output.model_json_schema(),
}


def handler(args: Args[Input]) -> Output:
    """纸媒聚合插件（人民日报/光明日报/经济日报/求是/新华每日电讯/经济参考报）"""
    logger = getattr(args, "logger", logging.getLogger(__name__))

    # 容忍缺失的 args.input 或字段；默认 source='all'
    inp_obj = getattr(args, "input", None)
    if isinstance(inp_obj, dict):
        source_val = (inp_obj.get("source") or "all").strip()
        max_items = int(inp_obj.get("max_items") or 10)
        date_str = inp_obj.get("date")
    else:
        source_val = (getattr(inp_obj, "source", None) or "all").strip()
        max_items = int((getattr(inp_obj, "max_items", None) or 10))
        date_str = getattr(inp_obj, "date", None)

    try:
        news_list: List[News] = []

        ORIGIN_MAP = {
            'peopledaily': '人民日报',
            'guangming': '光明日报',
            'economic': '经济日报',
            'qiushi': '求是',
            'xinhua': '新华每日电讯',
            'jjckb': '经济参考报',
        }

        # decide sources
        sel = source_val.lower() if source_val else 'all'
        selected = list(ORIGIN_MAP.keys()) if sel in ('all', '*') else [sel]

        for src in selected:
            per_count = 0
            if src == 'peopledaily':
                y, m, d = _find_available_date(_rmrb_get_page_list, date_str)
                for page_url, _ in _rmrb_get_page_list(y, m, d):
                    for url in _rmrb_get_title_list(y, m, d, page_url):
                        if per_count >= max_items:
                            break
                        html = _fetch_url(url)
                        _, _, title, body, summary = _rmrb_parse_article(html)
                        news_list.append(News(title=title or '', url=url, origin=ORIGIN_MAP[src], summary=summary or body or '', publish_date=f"{y}-{m}-{d}"))
                        per_count += 1
                    if per_count >= max_items:
                        break
            elif src == 'guangming':
                y, m, d = _find_available_date(_gmrb_get_page_list, date_str)
                for page_url, _ in _gmrb_get_page_list(y, m, d):
                    for url in _gmrb_get_title_list(y, m, d, page_url):
                        if per_count >= max_items:
                            break
                        html = _fetch_url(url)
                        _, _, title, body, summary = _gmrb_parse_article(html)
                        news_list.append(News(title=title or '', url=url, origin=ORIGIN_MAP[src], summary=summary or body or '', publish_date=f"{y}-{m}-{d}"))
                        per_count += 1
                    if per_count >= max_items:
                        break
            elif src == 'economic':
                y, m, d = _find_available_date(_jjrb_get_page_list, date_str)
                for page_url, _ in _jjrb_get_page_list(y, m, d):
                    for url in _jjrb_get_title_list(y, m, d, page_url):
                        if per_count >= max_items:
                            break
                        html = _fetch_url(url)
                        _, _, title, body, summary = _jjrb_parse_article(html)
                        news_list.append(News(title=title or '', url=url, origin=ORIGIN_MAP[src], summary=summary or body or '', publish_date=f"{y}-{m}-{d}"))
                        per_count += 1
                    if per_count >= max_items:
                        break
            elif src == 'xinhua':
                y, m, d = _find_available_date(_mrdx_get_page_list, date_str)
                for page_url, _ in _mrdx_get_page_list(y, m, d):
                    for url in _mrdx_get_title_list(y, m, d, page_url):
                        if per_count >= max_items:
                            break
                        html = _fetch_url(url)
                        _, _, title, body, summary = _mrdx_parse_article(html)
                        news_list.append(News(title=title or '', url=url, origin=ORIGIN_MAP[src], summary=summary or body or '', publish_date=f"{y}-{m}-{d}"))
                        per_count += 1
                    if per_count >= max_items:
                        break
            elif src == 'jjckb':
                y, m, d = _find_available_date(_jjckb_get_page_list, date_str)
                ad_count = 0  # 记录过滤的广告数量
                for page_url, _ in _jjckb_get_page_list(y, m, d):
                    for url in _jjckb_get_title_list(y, m, d, page_url):
                        if per_count >= max_items:
                            break
                        html = _fetch_url(url)
                        _, _, title, body, summary = _jjckb_parse_article(html)
                        
                        # 广告过滤检查
                        if _jjckb_is_advertisement(title or '', body or ''):
                            ad_count += 1
                            logger.info(f"过滤广告内容: {title} (正文长度: {len(body or '')})")
                            continue
                        
                        # 只保留非广告内容
                        if title or body:  # 确保有实际内容
                            news_list.append(News(title=title or '', url=url, origin=ORIGIN_MAP[src], summary=summary or body or '', publish_date=f"{y}-{m}-{d}"))
                            per_count += 1
                    if per_count >= max_items:
                        break
                if ad_count > 0:
                    logger.info(f"jjckb共过滤掉 {ad_count} 条广告内容")
            elif src == 'qiushi':
                part = _qiushi_collect(date_str, max_items, ORIGIN_MAP[src])
                news_list.extend(part[:max_items])
            else:
                return Output(news_list=None, status="ERROR", err_code="INVALID_SOURCE", err_info=f"Unsupported source: {src}")

        status = 'OK' if news_list else 'EMPTY'
        return Output(news_list=news_list or None, status=status, err_code=None if news_list else 'NO_DATA', err_info=None if news_list else 'No news parsed')
    except Exception as e:
        logger.exception("paper_news handler failed")
        return Output(news_list=None, status="ERROR", err_code="PLUGIN_ERROR", err_info=str(e))


# ------------------------ Common helpers ------------------------

def _fetch_url(url: str) -> str:
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


def _today_parts():
    today = datetime.date.today()
    return f"{today.year}", f"{today.month:02d}", f"{today.day:02d}"


def _find_available_date(get_pages_func, date: Optional[str], max_back_days: int = 7) -> Tuple[str, str, str]:
    # If date provided, try it first
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


# ------------------------ People Daily (rmrb) ------------------------

def _rmrb_get_page_list(year: str, month: str, day: str):
    base_url = 'http://paper.people.com.cn/rmrb/pc'
    base_layout = f'{base_url}/layout/{year}{month}/{day}/'
    url = urljoin(base_layout, 'node_01.html')
    html = _fetch_url(url)
    s = BeautifulSoup(html, 'html5lib')
    temp = s.find('div', id='pageList')
    if temp:
        page_list = temp.ul.find_all('div', class_='right_title-name')
    else:
        swiper = s.find('div', class_='swiper-container')
        page_list = [] if not swiper else swiper.find_all('div', class_='swiper-slide')
    out = []
    for page in page_list:
        a = page.find('a')
        if not a:
            continue
        link = a.get('href', '')
        name = a.get_text(strip=True)
        valid_name = ''.join(i for i in name if i not in r'\/:*?"<>|')
        page_url = urljoin(base_layout, link)
        out.append((page_url, valid_name))
    return out


def _rmrb_get_title_list(year: str, month: str, day: str, page_url: str):
    html = _fetch_url(page_url)
    s = BeautifulSoup(html, 'html5lib')
    temp = s.find('div', id='titleList')
    if temp:
        title_list = temp.ul.find_all('li')
    else:
        news_list = s.find('ul', class_='news-list')
        title_list = [] if not news_list else news_list.find_all('li')
    link_list = []
    content_base = f"{'http://paper.people.com.cn/rmrb/pc'.rstrip('/')}/content/{year}{month}/{day}/"
    for title in title_list:
        for a in title.find_all('a'):
            link = a.get('href', '')
            if 'content' in link:
                abs_url = urljoin(content_base, link)
                link_list.append(abs_url)
    return link_list


def _rmrb_parse_article(html: str):
    s = BeautifulSoup(html, 'html5lib')
    title_text = (s.h1.get_text(strip=True) if s.h1 else '')
    title_valid = ''.join(i for i in title_text if i not in r'\/:*?"<>|')
    h3 = s.h3.get_text(strip=True) if s.h3 else ''
    h2 = s.h2.get_text(strip=True) if s.h2 else ''
    container = s.find('div', id='ozoom')
    content_body = ''
    if container:
        p_list = container.find_all('p')
        for p in p_list:
            content_body += p.get_text(strip=True) + '\n'
    else:
        content_body = '\n'.join(p.get_text(strip=True) for p in s.find_all('p'))
    summary = content_body.strip()
    content_full = ''
    if h3:
        content_full += h3 + '\n'
    content_full += (title_text + '\n') if title_text else ''
    if h2:
        content_full += h2 + '\n'
    content_full += content_body
    return content_full, title_valid, title_text, content_body, summary


# ------------------------ Guangming Daily (gmrb) ------------------------

def _gmrb_get_page_list(year: str, month: str, day: str):
    base_url = 'https://epaper.gmw.cn/gmrb/html'
    date_path = f"{year}-{month}/{day}/"
    first_page = urljoin(f"{base_url}/{date_path}", 'nbs.D110000gmrb_01.htm')
    html = _fetch_url(first_page)
    soup = BeautifulSoup(html, 'html5lib')
    page_container = soup.find('div', id='pageList')
    anchors = page_container.find_all('a') if page_container else soup.find_all('a')
    link_list = []
    seen = set()
    for a in anchors:
        href = (a.get('href') or '').strip()
        text_value = a.get_text(strip=True)
        # Only keep HTML pages; ignore PDFs and other resources
        h = href.lower()
        if (not href) or h.startswith('javascript'):
            continue
        if ('.pdf' in h) or (not h.endswith('.htm')):
            continue
        if href in seen:
            continue
        seen.add(href)
        page_url = urljoin(f"{base_url}/{date_path}", href)
        name = text_value or href
        valid_name = ''.join(i for i in name if i not in r'\/:*?"<>|')
        link_list.append((page_url, valid_name))
    return link_list


def _gmrb_get_title_list(year: str, month: str, day: str, page_url: str):
    html = _fetch_url(page_url)
    soup = BeautifulSoup(html, 'html5lib')
    temp = soup.find('div', id='titleList')
    if temp:
        items = temp.ul.find_all('li') if temp.ul else []
    else:
        items = soup.find_all('li')
    link_list = []
    for li in items:
        for a in li.find_all('a'):
            href = (a.get('href') or '').strip()
            if not href or href.lower().startswith('javascript'):
                continue
            abs_url = urljoin(page_url, href)
            link_list.append(abs_url)
    return [u for u in link_list if '/content/' in u or u.lower().endswith('.htm')]


def _gmrb_parse_article(html: str):
    soup = BeautifulSoup(html, 'html5lib')
    title = ''
    if soup.h1:
        title = soup.h1.get_text(strip=True)
    elif soup.title:
        title = soup.title.get_text(strip=True)
    title_valid = ''.join(i for i in title if i not in r'\/:*?"<>|')
    body = ''
    for sel in ['#ozoom', '#content', 'div#content', '.content', 'div.article', '#mdf', '#detail']:
        el = soup.select_one(sel)
        if el:
            ps = [p.get_text(strip=True) for p in el.find_all('p') if p.get_text(strip=True)]
            if ps:
                body = '\n'.join(ps)
                break
    if not body:
        best = None
        best_len = 0
        for div in soup.find_all('div'):
            ps = div.find_all('p')
            if ps:
                txt = '\n'.join(p.get_text(strip=True) for p in ps)
                if len(txt) > best_len:
                    best = div
                    best_len = len(txt)
        if best:
            body = '\n'.join(p.get_text(strip=True) for p in best.find_all('p') if p.get_text(strip=True))
    content_full = (title + '\n' + body) if title else body
    summary = body.strip()
    return content_full, title_valid, title, body, summary


# ------------------------ Economic Daily (jjrb) ------------------------

def _jjrb_get_page_list(year: str, month: str, day: str):
    base_url = 'http://paper.ce.cn/pc'
    base_layout = f'{base_url}/layout/{year}{month}/{day}/'
    url = urljoin(base_layout, 'node_01.html')
    html = _fetch_url(url)
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


def _jjrb_get_title_list(year: str, month: str, day: str, page_url: str):
    html = _fetch_url(page_url)
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


def _jjrb_parse_article(html: str):
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
    container = _best_content_div(s)
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


def _best_content_div(soup: BeautifulSoup):
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


# ------------------------ Qiushi ------------------------

def _qiushi_collect(date: Optional[str], max_items: int, origin: str) -> List[News]:
    ROOT_INDEX_URL = 'https://www.qstheory.cn/qs/mulu.htm'

    def fetch_url(url: str) -> str:
        headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
            'referer': 'https://www.qstheory.cn/'
        }
        r = requests.get(url, headers=headers, timeout=30, proxies={'http': None, 'https': None})
        r.raise_for_status()
        r.encoding = r.apparent_encoding
        return r.text

    def _to_https(u: str) -> str:
        return ('https://' + u.split('://', 1)[1]) if u.startswith('http://') else u

    def _normalize(u: str) -> str:
        u = _to_https(u)
        return u.replace('://qstheory.cn', '://www.qstheory.cn')

    def get_issue_candidates_from_root(root_url: str = ROOT_INDEX_URL):
        html = fetch_url(root_url)
        s = BeautifulSoup(html, 'html.parser')
        items: List[Tuple[str, str, str]] = []
        seen = set()
        for a in s.find_all('a', href=True):
            href = a['href']
            m = re.search(r'/(\d{8})/[a-z0-9]{32}/c\.html$', href)
            if not m:
                continue
            absu = _normalize(urljoin(root_url, href))
            if absu in seen:
                continue
            seen.add(absu)
            date_str = m.group(1)
            name = a.get_text(strip=True) or f"期刊 {date_str}"
            items.append((name, absu, date_str))
        items.sort(key=lambda x: x[2], reverse=True)
        return items

    def get_year_list(root_url: str = ROOT_INDEX_URL):
        html = fetch_url(root_url)
        s = BeautifulSoup(html, 'html.parser')
        links: List[Tuple[str, str]] = []
        seen = set()
        for a in s.find_all('a', href=True):
            href = a['href']
            txt = a.get_text(strip=True)
            if re.search(r'(\d{8}/[a-z0-9]{32}/c\.html)$', href) or re.search(r'/dukan/qs/\d{4}-\d{2}/01/c_\d+\.htm$', href):
                absu = _normalize(urljoin(root_url, href))
                if absu in seen:
                    continue
                seen.add(absu)
                if not txt:
                    m = re.search(r'(\d{4})', href)
                    txt = f"{m.group(1)}年" if m else '年'
                links.append((txt, absu))
        def year_key(item):
            m = re.search(r'(\d{4})', item[1])
            return int(m.group(1)) if m else 0
        links.sort(key=year_key, reverse=True)
        return links

    def get_issue_list(year_url: str):
        html = fetch_url(year_url)
        s = BeautifulSoup(html, 'html.parser')
        issues: List[Tuple[str, str, str]] = []
        seen = set()
        for a in s.find_all('a', href=True):
            href = a['href']
            m = re.search(r'/(\d{8})/[a-z0-9]{32}/c\.html$', href)
            if not m:
                continue
            txt = a.get_text(strip=True)
            if not (('期' in txt) or ('目录' in txt) or ('刊' in txt)):
                continue
            absu = _normalize(urljoin(year_url, href))
            if absu == year_url or absu in seen:
                continue
            seen.add(absu)
            date_str = m.group(1)
            name = txt or f"期刊 {date_str}"
            issues.append((name, absu, date_str))
        issues.sort(key=lambda x: x[2])
        return issues

    def get_article_list(issue_url: str):
        html = fetch_url(issue_url)
        s = BeautifulSoup(html, 'html.parser')
        art_links: List[str] = []
        seen = set()
        for a in s.find_all('a', href=True):
            href = a['href']
            absu = ''
            if re.search(r'/\d{8}/[a-z0-9]{32}/c\.html$', href):
                absu = _normalize(urljoin(issue_url, href))
            elif re.search(r'/dukan/qs/\d{4}-\d{2}/\d{2}/c_\d+\.htm$', href):
                absu = _normalize(urljoin(issue_url, href))
            if not absu:
                continue
            if absu in seen:
                continue
            seen.add(absu)
            art_links.append(absu)
        return art_links

    # choose issue
    chosen = None
    target_idate = None
    if date:
        try:
            y, m, d = date.split('-')
            target_idate = f"{y}{m}{d}"
        except Exception:
            target_idate = None
    for name, iurl, idate in get_issue_candidates_from_root(ROOT_INDEX_URL):
        if target_idate and idate == target_idate:
            chosen = (name, iurl, idate)
            break
        if not target_idate:
            chosen = (name, iurl, idate)
            break
    if not chosen:
        years = get_year_list(ROOT_INDEX_URL)
        if years:
            yname, yurl = None, None
            preferred = [t for t in years if '/dukan/qs/' in t[1]]
            if preferred:
                yname, yurl = preferred[0]
            else:
                yname, yurl = years[0]
            issues = get_issue_list(yurl)
            if issues:
                for iname, iurl, idate in reversed(issues):
                    if target_idate and idate == target_idate:
                        chosen = (iname, iurl, idate)
                        break
                    if not target_idate:
                        chosen = (iname, iurl, idate)
                        break
                if not chosen:
                    chosen = issues[-1]
    if not chosen:
        return []
    iname, iurl, idate = chosen
    links = get_article_list(iurl)
    out: List[News] = []
    date_str = f"{idate[:4]}-{idate[4:6]}-{idate[6:]}"
    for url in links:
        html = fetch_url(url)
        # parse article (simple)
        s = BeautifulSoup(html, 'html.parser')
        title = s.h1.get_text(strip=True) if s.h1 else (s.title.get_text(strip=True) if s.title else '')
        body = ''
        for sel in ['#Content','div#content','.content','div.article','#mdf','#detail','.left_t','.lft_Article','.lft_artc_cont','#ozoom']:
            el = s.select_one(sel)
            if el:
                ps = [p.get_text(strip=True) for p in el.find_all('p') if p.get_text(strip=True)]
                if ps:
                    body = '\n'.join(ps)
                    break
        out.append(News(title=title or '', url=url, origin=origin, summary=body or '', publish_date=date_str))
        if len(out) >= max_items:
            break
    return out


# ------------------------ Xinhua Daily Telegraph (mrdx) ------------------------

def _mrdx_get_page_list(year: str, month: str, day: str):
    base_url = 'http://mrdx.cn/content'
    date_dir = f"{year}{month}{day}"
    root = f"{base_url.rstrip('/')}/{date_dir}/"
    # find first page
    first_html = ''
    first_url = ''
    for fname in ['Page01DK.htm','Page01.htm','page01.htm','Page01A.htm','Page01B.htm']:
        url = urljoin(root, fname)
        try:
            html = _fetch_url(url)
        except Exception:
            continue
        if 'shijuedaohang' in html or 'pageto' in html:
            first_html = html
            first_url = url
            break
    if not first_html:
        return []
    soup = BeautifulSoup(first_html, 'html.parser')
    nav = soup.find('div', class_='shijuedaohang')
    items = []
    if nav:
        for a in nav.find_all('a', href=True):
            href = a['href'].strip()
            if not href or href.lower().startswith('javascript'):
                continue
            page_url = urljoin(first_url, href)
            name = ''
            h4 = a.find('h4')
            if h4 and h4.get_text(strip=True):
                name = h4.get_text(strip=True)
            else:
                img = a.find('img')
                if img and (img.get('alt') or '').strip():
                    name = img.get('alt').strip()
            name = name or href
            valid_name = ''.join(ch for ch in name if ch not in r'\/:*?"<>|')
            items.append((page_url, valid_name))
    if not items:
        for i in range(1, 17):
            fname = f"Page{i:02d}DK.htm"
            test_url = urljoin(root, fname)
            try:
                _ = _fetch_url(test_url)
                items.append((test_url, f"Page {i:02d}"))
            except Exception:
                break
    return items


def _mrdx_get_title_list(year: str, month: str, day: str, page_url: str):
    html = _fetch_url(page_url)
    rels = re.findall(r"daoxiang=\"([^\"]+)\"", html)
    links = []
    seen = set()
    for rel in rels:
        if not rel.lower().endswith('.htm'):
            continue
        absu = urljoin(page_url, rel)
        if absu in seen:
            continue
        seen.add(absu)
        links.append(absu)
    if not links:
        rels2 = re.findall(r"href=\"([^\"]*Articel[^\"]*\.htm)\"", html, flags=re.I)
        for rel in rels2:
            absu = urljoin(page_url, rel)
            if absu not in seen:
                seen.add(absu)
                links.append(absu)
    return links


def _mrdx_parse_article(html: str):
    soup = BeautifulSoup(html, 'html5lib')
    title = ''
    h2 = soup.find('h2')
    if h2 and h2.get_text(strip=True):
        title = h2.get_text(strip=True)
    elif soup.title:
        title = soup.title.get_text(strip=True)
    tvalid = ''.join(ch for ch in title if ch not in r'\/:*?"<>|')
    body = ''
    content_div = soup.find(id='contenttext') or soup.find('div', class_='contenttext')
    if content_div:
        # remove style/script/noscript inside content block
        for t in content_div.find_all(['style', 'script', 'noscript']):
            t.decompose()
        body = content_div.get_text('\n', strip=True)
    if not body:
        for sel in ['#ozoom', '#content', 'div.content', 'div.article', '#mdf', '#detail']:
            el = soup.select_one(sel)
            if el:
                # remove noisy tags in fallback container too
                for t in el.find_all(['style', 'script', 'noscript']):
                    t.decompose()
                ps = [p.get_text(strip=True) for p in el.find_all('p') if p.get_text(strip=True)]
                if ps:
                    body = '\n'.join(ps)
                    break
    # cleanup CSS-like noise and float title markers that sometimes leak as text
    body = _clean_mrdx_body(body)
    content_full = (title + '\n' + body) if title else body
    summary = body[:800]
    return content_full, tvalid, title, body, summary


def _clean_mrdx_body(text: str) -> str:
    if not text:
        return text
    # remove FloatTitle markers
    cleaned = re.sub(r"<\s*FloatTitleB\s*>|<\s*FloatTitleE\s*>", "", text)
    # drop CSS-like lines (e.g., BODY { FONT-FAMILY: ... }) and font declarations
    out_lines: List[str] = []
    css_line = re.compile(r"^[A-Za-z][A-Za-z0-9#\.\s:-]*\{[^}]+\}$")
    for ln in cleaned.splitlines():
        ln_stripped = ln.strip()
        if not ln_stripped:
            continue
        if 'FONT-FAMILY' in ln_stripped.upper() or 'FONT-SIZE' in ln_stripped.upper():
            continue
        if css_line.match(ln_stripped):
            continue
        out_lines.append(ln_stripped)
    result = '\n'.join(out_lines)
    # collapse excessive blank lines created by filtering
    result = re.sub(r"\n{2,}", "\n", result)
    return result


# ------------------------ Economic Information Daily (jjckb) ------------------------

def _jjckb_get_page_list(year: str, month: str, day: str):
    root = f"{'http://dz.jjckb.cn/www/pages/webpage2009/html'.rstrip('/')}/{year}-{month}/{day}/"
    start_url, html = _jjckb_pick_first_node(root)
    if not html:
        return []
    soup = BeautifulSoup(html, 'html5lib')
    items = []
    for a in soup.find_all('a', id='pageLink', href=True):
        href = a['href'].strip()
        name = a.get_text(strip=True) or href
        absu = urljoin(start_url, href)
        valid_name = ''.join(ch for ch in name if ch not in r'\/:*?"<>|')
        items.append((absu, valid_name))
    if not items:
        seen = set()
        for a in soup.find_all('a', href=True):
            href = a['href'].strip()
            if not re.search(r'node_\d+\.htm$', href):
                continue
            absu = urljoin(start_url, href)
            if absu in seen:
                continue
            seen.add(absu)
            name = a.get_text(strip=True) or href
            valid_name = ''.join(ch for ch in name if ch not in r'\/:*?"<>|')
            items.append((absu, valid_name))
    if start_url and not any(u == start_url for u, _ in items):
        items.insert(0, (start_url, 'A01'))
    return items


def _jjckb_pick_first_node(root: str) -> Tuple[str, str]:
    for name in ['node_2.htm', 'node_1.htm', 'node_3.htm']:
        url = urljoin(root, name)
        try:
            html = _fetch_url(url)
            if 'pageLink' in html or 'ul02_l' in html or 'MAP NAME="pagepicmap"' in html:
                return url, html
        except Exception:
            continue
    for i in range(1, 12):
        url = urljoin(root, f'node_{i}.htm')
        try:
            html = _fetch_url(url)
            if 'pageLink' in html or 'ul02_l' in html:
                return url, html
        except Exception:
            pass
    return '', ''


def _jjckb_get_title_list(year: str, month: str, day: str, page_url: str):
    html = _fetch_url(page_url)
    soup = BeautifulSoup(html, 'html.parser')
    links = []
    seen = set()
    for li in soup.select('ul.ul02_l li'):
        a = li.find('a', href=True)
        if not a:
            continue
        href = a['href'].strip()
        if not href or not href.endswith('.htm'):
            continue
        absu = urljoin(page_url, href)
        if absu in seen:
            continue
        seen.add(absu)
        links.append(absu)
    if not links:
        for area in soup.find_all('area', href=True):
            href = area['href'].strip()
            if not href or not href.endswith('.htm'):
                continue
            absu = urljoin(page_url, href)
            if absu in seen:
                continue
            seen.add(absu)
            links.append(absu)
    if not links:
        for a in soup.find_all('a', href=True):
            href = a['href'].strip()
            if not re.search(r'content_\d+\.htm$', href):
                continue
            absu = urljoin(page_url, href)
            if absu in seen:
                continue
            seen.add(absu)
            links.append(absu)
    return links


def _jjckb_is_advertisement(title: str, body: str) -> bool:
    """检测是否为广告内容"""
    if not title or not body:
        return True
    
    # 1. 标题过短且正文很少（典型广告特征）
    if len(title) <= 8 and len(body) <= 50:
        return True
    
    # 2. 标题只包含公司名等广告关键词
    ad_patterns = [
        r'^[\w\s]*(?:科技|电子|有限公司|股份|集团|企业|公司)[\w\s]*$',  # 公司名格式
        r'^[\w\s]*(?:招聘|诚聘|招募)[\w\s]*$',  # 招聘广告  
        r'^[\w\s]*(?:转让|出售|求购|合作)[\w\s]*$',  # 交易广告
        r'^[\w\s]*(?:声明|启事|通告|公告)[\w\s]*$',  # 各种公告
    ]
    
    for pattern in ad_patterns:
        if re.match(pattern, title.strip()):
            # 如果匹配广告模式且正文很短，判定为广告
            if len(body) <= 200:
                return True
    
    # 3. 正文内容质量检测
    if len(body) > 0:
        # 计算中文字符比例
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', body))
        if chinese_chars < 20:  # 中文字符太少
            return True
        
        # 检测是否包含实质性新闻内容
        news_keywords = ['报道', '记者', '消息', '新闻', '据悉', '了解到', '表示', '认为', '指出', '强调', '透露']
        if not any(keyword in body for keyword in news_keywords):
            # 没有新闻关键词且内容很短
            if len(body) <= 100:
                return True
    
    return False


def _jjckb_parse_article(html: str):
    soup = BeautifulSoup(html, 'html.parser')
    raw = soup.decode()
    m = re.search(r'<founder-title>(.*?)</founder-title>', raw, flags=re.I | re.S)
    title = ''
    if m:
        title = BeautifulSoup(m.group(1), 'html.parser').get_text(strip=True)
    if not title:
        for tag in ['h1', 'h2', 'h3', 'title']:
            t = soup.find(tag)
            if t and t.get_text(strip=True):
                title = t.get_text(strip=True)
                break
    title_valid = ''.join(ch for ch in title if ch not in r'\/:*?"<>|')
    body = ''
    fcontent = soup.find('founder-content')
    if fcontent:
        ps = [p.get_text(strip=True) for p in fcontent.find_all('p') if p.get_text(strip=True)]
        body = '\n'.join(ps)
    if not body:
        for sel in ['#content', '#ozoom', 'div.content', 'div.article', 'td.black14', '#mdf', '#detail']:
            el = soup.select_one(sel)
            if el:
                ps = [p.get_text(strip=True) for p in el.find_all('p') if p.get_text(strip=True)]
                if ps:
                    body = '\n'.join(ps)
                    break
    content_full = (title + '\n' + body) if title else body
    summary = body[:800]
    return content_full, title_valid, title, body, summary
