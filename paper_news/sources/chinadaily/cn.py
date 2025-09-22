import re
import datetime
from typing import List
import requests
import bs4
from urllib.parse import urljoin

DEFAULT_HOME = 'https://www.chinadaily.com.cn/'
SESSION = requests.Session()

HEADERS = {
    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
    'referer': DEFAULT_HOME,
    'accept-language': 'en-US,en;q=0.9,zh-CN;q=0.8',
}

CHANNEL_START_URLS = {
    'china': [
        'https://www.chinadaily.com.cn/china/',
        'https://www.chinadaily.com.cn/china/governmentandpolicy',
        'https://www.chinadaily.com.cn/china/society',
    ],
    'business': [
        'https://www.chinadaily.com.cn/business/',
        'https://www.chinadaily.com.cn/business/chinawatch',
        'https://www.chinadaily.com.cn/business/tech',
        'https://www.chinadaily.com.cn/business/economy',
        'https://www.chinadaily.com.cn/business/companies',
        'https://www.chinadaily.com.cn/business/markets',
    ],
}

ARTICLE_PATTERNS = [
    re.compile(r'(?:https?:)?//[\\w.-]*chinadaily\\.com\\.cn/a/\\d{6}/\\d{2}/WS[0-9A-Za-z]+\\.html', re.I),
    re.compile(r'(?:https?:)?//[\\w.-]*chinadaily\\.com\\.cn/a/\\d{4}-\\d{2}/\\d{2}/WS[0-9A-Za-z]+\\.html', re.I),
    re.compile(r'/a/\\d{6}/\\d{2}/WS[0-9A-Za-z]+\\.html', re.I),
    re.compile(r'/a/\\d{4}-\\d{2}/\\d{2}/WS[0-9A-Za-z]+\\.html', re.I),
    re.compile(r'(?:https?:)?//[\\w.-]*chinadaily\\.com\\.cn/\\d{4}-\\d{2}/\\d{2}/content_\\d+\\.htm', re.I),
    re.compile(r'/\\d{4}-\\d{2}/\\d{2}/content_\\d+\\.htm', re.I),
]


def fetch_url(url: str) -> str:
    r = SESSION.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    r.encoding = r.apparent_encoding
    return r.text


def to_abs(base_url: str, href: str) -> str:
    if not href:
        return ''
    if href.startswith('//'):
        return 'https:' + href
    return urljoin(base_url, href)


def is_article_url(href: str) -> bool:
    if not href:
        return False
    for p in ARTICLE_PATTERNS:
        if p.search(href):
            return True
    return False


def extract_links_from_html(base_url: str, html: str) -> List[str]:
    soup = bs4.BeautifulSoup(html, 'html.parser')
    out: List[str] = []
    seen = set()
    for a in soup.find_all('a', href=True):
        h = a['href']
        if ('WS' in h) or ('content_' in h):
            if is_article_url(h):
                absu = to_abs(base_url, h)
                if absu not in seen:
                    seen.add(absu)
                    out.append(absu)
    for pat in ARTICLE_PATTERNS:
        for m in pat.finditer(html):
            absu = to_abs(base_url, m.group(0))
            if absu not in seen:
                seen.add(absu)
                out.append(absu)
    return out


def parse_pub_date_from_url(url: str) -> str:
    m = re.search(r'/a/(\\d{6})/(\\d{2})/', url)
    if m:
        yymm, dd = m.groups()
        y = '20' + yymm[:2]
        mo = yymm[2:4]
        d = dd
        try:
            dt = datetime.date(int(y), int(mo), int(d))
            return dt.strftime('%Y-%m-%d')
        except Exception:
            pass
    m = re.search(r'/(\\d{4})-(\\d{2})/(\\d{2})/content_\\d+\\.htm', url)
    if m:
        y, mo, d = m.groups()
        try:
            dt = datetime.date(int(y), int(mo), int(d))
            return dt.strftime('%Y-%m-%d')
        except Exception:
            pass
    return ''


def parse_article(html: str, fallback_date: str = ''):
    s = bs4.BeautifulSoup(html, 'html.parser')
    title = ''
    og = s.find('meta', attrs={'property': 'og:title'})
    if og and og.get('content'):
        title = og['content'].strip()
    if not title and s.h1:
        title = s.h1.get_text(strip=True)
    if not title and s.title:
        title = s.title.get_text(strip=True)
    tvalid = ''.join(ch for ch in title if ch not in r'\/:*?"<>|')

    pub = ''
    for name in ['pubdate','publishdate','date','article:published_time']:
        m = s.find('meta', attrs={'name': name}) or s.find('meta', attrs={'property': name})
        if m and m.get('content'):
            pub = m['content'].strip(); break
    if not pub:
        # find date in visible text
        m = re.search(r'(20\\d{2})[-/](\\d{1,2})[-/](\\d{1,2})', s.get_text(' ', strip=True))
        if m:
            y, mo, d = m.groups(); pub = f"{y}-{int(mo):02d}-{int(d):02d}"
    if not pub:
        pub = fallback_date or datetime.date.today().strftime('%Y-%m-%d')

    body = ''
    for sel in ['#Content','div#content','.content','div.article','#mdf','#detail','.left_t','.lft_Article','.lft_artc_cont','#ozoom']:
        el = s.select_one(sel)
        if el:
            ps = [p.get_text(strip=True) for p in el.find_all('p') if p.get_text(strip=True)]
            if ps:
                body = '\n'.join(ps); break
    if not body:
        best = None; best_len = 0
        for div in s.find_all('div'):
            ps = div.find_all('p')
            if ps:
                txt = '\n'.join(p.get_text(strip=True) for p in ps)
                if len(txt) > best_len:
                    best = div; best_len = len(txt)
        if best:
            body = '\n'.join(p.get_text(strip=True) for p in best.find_all('p') if p.get_text(strip=True))

    content_full = (title + '\n' + body) if title else body
    return content_full, tvalid, title, body, body[:800], pub


def collect_recent_links(channels: List[str], max_count: int = 40) -> List[str]:
    start_urls: List[str] = []
    for ch in channels:
        start_urls.extend(CHANNEL_START_URLS.get(ch, []))
    start_urls = list(dict.fromkeys(start_urls))

    all_links: List[str] = []
    seen = set()
    for su in start_urls:
        try:
            html = fetch_url(su)
            found = extract_links_from_html(su, html)
            for u in found:
                if u not in seen:
                    seen.add(u)
                    all_links.append(u)
        except Exception:
            continue
    return list(dict.fromkeys(all_links))[:max_count]
