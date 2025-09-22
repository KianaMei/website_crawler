import re
import requests
import bs4
import xml.etree.ElementTree as ET
from typing import List

SESSION = requests.Session()
DEFAULT_RSS = 'https://www.chinadaily.com.cn/rss/china_rss.xml'
SEL_CONTENT = ['#Content','div#content','.content','div.article','#mdf','#detail','.left_t','.lft_Article','.lft_artc_cont']


def fetch(url: str) -> str:
    r = SESSION.get(url, headers={'user-agent':'Mozilla/5.0'}, timeout=30)
    r.raise_for_status(); r.encoding = r.apparent_encoding
    return r.text


def is_article(u: str) -> bool:
    PATS = [
        re.compile(r'^https?://[\\w.-]*chinadaily\\.com\\.cn/a/\\d{4}-\\d{2}/\\d{2}/WS[0-9a-f]+\\.html$', re.I),
        re.compile(r'^https?://[\\w.-]*chinadaily\\.com\\.cn/\\d{4}-\\d{2}/\\d{2}/content_\\d+\\.htm$', re.I),
        re.compile(r'^https?://[\\w.-]*chinadaily\\.com\\.cn/a/\\d{8}/WS[0-9a-f]+\\.html$', re.I),
        re.compile(r'^https?://[\\w.-]*chinadaily\\.com\\.cn/a/\\d{6}/\\d{2}/WS[0-9a-f]+\\.html$', re.I),
    ]
    return any(p.search(u) for p in PATS)


def parse_rss(feed: str = DEFAULT_RSS, maxn: int = 15) -> List[str]:
    xml = fetch(feed)
    links: List[str] = []
    try:
        root = ET.fromstring(xml)
        for item in root.iterfind('.//item'):
            url = ''
            link_el = item.find('link')
            if link_el is not None and link_el.text:
                url = link_el.text.strip()
            if (not url):
                guid_el = item.find('guid')
                if guid_el is not None and guid_el.text:
                    url = guid_el.text.strip()
            if url and is_article(url):
                links.append(url)
                if len(links) >= maxn:
                    break
    except Exception:
        pass
    return links


def parse_article(html: str):
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
    for name in ['pubdate','publishdate','date']:
        m = s.find('meta', attrs={'name': name})
        if m and m.get('content'):
            pub = m['content'].strip(); break
    if not pub:
        m = re.search(r'(20\\d{2})[-/](\\d{1,2})[-/](\\d{1,2})', s.get_text(' ', strip=True))
        if m:
            y, mo, d = m.groups(); pub = f"{y}-{int(mo):02d}-{int(d):02d}"
    body = ''
    for sel in SEL_CONTENT:
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