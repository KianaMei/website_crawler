import re
from typing import List, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


DEFAULT_BASE_URL = 'http://mrdx.cn/content'


def fetch_url(url: str) -> str:
    headers = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/68.0.3440.106 Safari/537.36',
        'referer': 'http://mrdx.cn/'
    }
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    # trust site-reported encoding; fallback to apparent if missing
    if not r.encoding:
        r.encoding = r.apparent_encoding
    return r.text


def _candidate_first_pages(date_str: str) -> List[str]:
    # Try common variants for the first page filename
    return [
        f'Page01DK.htm',
        f'Page01.htm',
        f'page01.htm',
        f'Page01A.htm',
        f'Page01B.htm',
    ]


def get_page_list(year: str, month: str, day: str, base_url: str = DEFAULT_BASE_URL) -> List[Tuple[str, str]]:
    """Return list of (page_url, page_name) for the issue date.

    Example date dir: http://mrdx.cn/content/20250919/
    Pages usually like Page01DK.htm, Page02DK.htm, ... with thumbnails and headings in 'div.shijuedaohang'.
    """
    date_dir = f"{year}{month}{day}"
    root = f"{base_url.rstrip('/')}/{date_dir}/"

    # find a first page that loads and contains navigation
    first_html = ''
    first_url = ''
    for fname in _candidate_first_pages(date_dir):
        url = urljoin(root, fname)
        try:
            html = fetch_url(url)
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
            # name from nested h4 or alt
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
    # Fallback: guess up to 16 pages
    if not items:
        for i in range(1, 17):
            fname = f"Page{i:02d}DK.htm"
            test_url = urljoin(root, fname)
            try:
                _ = fetch_url(test_url)
                items.append((test_url, f"Page {i:02d}"))
            except Exception:
                break
    return items


def get_title_list(year: str, month: str, day: str, page_url: str, base_url: str = DEFAULT_BASE_URL) -> List[str]:
    """Return list of article URLs for a given page URL.

    Articles are linked via anchors with custom attribute 'daoxiang' (relative URL like 'Articel01001NU.htm').
    """
    html = fetch_url(page_url)
    # Quick scan for daoxiang links
    rels = re.findall(r"daoxiang=\"([^\"]+)\"", html)
    links: List[str] = []
    seen = set()
    for rel in rels:
        if not rel.lower().endswith('.htm'):
            continue
        absu = urljoin(page_url, rel)
        if absu in seen:
            continue
        seen.add(absu)
        links.append(absu)
    # Fallback: any hrefs with 'Articel' pattern
    if not links:
        rels2 = re.findall(r"href=\"([^\"]*Articel[^\"]*\.htm)\"", html, flags=re.I)
        for rel in rels2:
            absu = urljoin(page_url, rel)
            if absu not in seen:
                seen.add(absu)
                links.append(absu)
    return links


def parse_article(html: str):
    """Parse article content page to (content_full, title_valid, title, body, summary)."""
    soup = BeautifulSoup(html, 'html.parser')
    # Title candidates
    title = ''
    h2 = soup.find('h2')
    if h2 and h2.get_text(strip=True):
        title = h2.get_text(strip=True)
    elif soup.title:
        title = soup.title.get_text(strip=True)
    tvalid = ''.join(ch for ch in title if ch not in r'\/:*?"<>|')

    # Body: prefer #contenttext container
    body = ''
    content_div = soup.find(id='contenttext') or soup.find('div', class_='contenttext')
    if content_div:
        # Sometimes the content is embedded HTML; get text with separators
        body = content_div.get_text('\n', strip=True)
    if not body:
        # Try common fallbacks
        for sel in ['#ozoom', '#content', 'div.content', 'div.article', '#mdf', '#detail']:
            el = soup.select_one(sel)
            if el:
                ps = [p.get_text(strip=True) for p in el.find_all('p') if p.get_text(strip=True)]
                if ps:
                    body = '\n'.join(ps)
                    break
    content_full = (title + '\n' + body) if title else body
    summary = body[:800]
    return content_full, tvalid, title, body, summary

