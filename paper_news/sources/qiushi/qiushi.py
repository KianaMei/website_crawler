import re
from typing import List, Tuple
import requests
import bs4
from urllib.parse import urljoin

ROOT_INDEX_URL = 'https://www.qstheory.cn/qs/mulu.htm'


def fetch_url(url: str) -> str:
    headers = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/68.0.3440.106 Safari/537.36',
        'referer': 'https://www.qstheory.cn/'
    }
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    r.encoding = r.apparent_encoding
    return r.text


def _to_https(u: str) -> str:
    return ('https://' + u.split('://', 1)[1]) if u.startswith('http://') else u


def _normalize(u: str) -> str:
    u = _to_https(u)
    return u.replace('://qstheory.cn', '://www.qstheory.cn')


def get_year_list(root_url: str = ROOT_INDEX_URL) -> List[Tuple[str, str]]:
    html = fetch_url(root_url)
    s = bs4.BeautifulSoup(html, 'html.parser')
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
                txt = f"{m.group(1)}年" if m else '期'
            links.append((txt, absu))
    def year_key(item):
        m = re.search(r'(\d{4})', item[1])
        return int(m.group(1)) if m else 0
    links.sort(key=year_key, reverse=True)
    return links


def get_issue_list(year_url: str) -> List[Tuple[str, str, str]]:
    html = fetch_url(year_url)
    s = bs4.BeautifulSoup(html, 'html.parser')
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
        name = txt or f"求是 {date_str}"
        issues.append((name, absu, date_str))
    issues.sort(key=lambda x: x[2])
    return issues


def get_article_list(issue_url: str) -> List[str]:
    html = fetch_url(issue_url)
    s = bs4.BeautifulSoup(html, 'html.parser')
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


def is_issue_directory(url: str) -> bool:
    try:
        html = fetch_url(url)
    except Exception:
        return False
    s = bs4.BeautifulSoup(html, 'html.parser')
    cnt = 0
    for a in s.find_all('a', href=True):
        h = a['href']
        if re.search(r'/\d{8}/[a-z0-9]{32}/c\.html$', h) or re.search(r'/dukan/qs/\d{4}-\d{2}/\d{2}/c_\d+\.htm$', h):
            cnt += 1
            if cnt >= 5:
                return True
    return False


def parse_article(html: str):
    s = bs4.BeautifulSoup(html, 'html.parser')
    title = ''
    if s.h1 and s.h1.get_text(strip=True):
        title = s.h1.get_text(strip=True)
    elif s.h2 and s.h2.get_text(strip=True):
        title = s.h2.get_text(strip=True)
    elif s.title:
        title = s.title.get_text(strip=True)
    tvalid = ''.join(ch for ch in title if ch not in r'\/:*?"<>|')

    body = ''
    for sel in ['#Content','div#content','.content','div.article','#mdf','#detail','.left_t','.lft_Article','.lft_artc_cont','#ozoom']:
        el = s.select_one(sel)
        if el:
            ps = [p.get_text(strip=True) for p in el.find_all('p') if p.get_text(strip=True)]
            if ps:
                body = '\n'.join(ps)
                break
    if not body:
        best = None
        best_len = 0
        for div in s.find_all('div'):
            ps = div.find_all('p')
            if ps:
                txt = '\n'.join(p.get_text(strip=True) for p in ps)
                if len(txt) > best_len:
                    best = div
                    best_len = len(txt)
        if best:
            body = '\n'.join(p.get_text(strip=True) for p in best.find_all('p') if p.get_text(strip=True))
    content_full = (title + '\n' + body) if title else body
    return content_full, tvalid, title, body, body[:800]

def get_issue_candidates_from_root(root_url: str = ROOT_INDEX_URL) -> List[Tuple[str, str, str]]:
    """Return list of (name, url, yyyymmdd) candidates directly listed on the root index."""
    html = fetch_url(root_url)
    s = bs4.BeautifulSoup(html, 'html.parser')
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
        name = a.get_text(strip=True) or f"求是 {date_str}"
        items.append((name, absu, date_str))
    # sort by date desc
    items.sort(key=lambda x: x[2], reverse=True)
    return items
