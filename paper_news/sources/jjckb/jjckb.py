import re
from typing import List, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


DEFAULT_BASE_URL = 'http://dz.jjckb.cn/www/pages/webpage2009/html'


def fetch_url(url: str) -> str:
    headers = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/68.0.3440.106 Safari/537.36',
        'referer': 'http://dz.jjckb.cn/'
    }
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    if not r.encoding:
        r.encoding = r.apparent_encoding
    else:
        # trust site header but fix if needed
        r.encoding = r.apparent_encoding
    return r.text


def _date_root(year: str, month: str, day: str, base_url: str = DEFAULT_BASE_URL) -> str:
    return f"{base_url.rstrip('/')}/{year}-{month}/{day}/"


def _pick_first_node(root: str) -> Tuple[str, str]:
    # try common node pages
    for name in [
        'node_2.htm',
        'node_1.htm',
        'node_3.htm',
    ]:
        url = urljoin(root, name)
        try:
            html = fetch_url(url)
            if 'pageLink' in html or 'ul02_l' in html or 'MAP NAME="pagepicmap"' in html:
                return url, html
        except Exception:
            continue
    # brute-force a bit more
    for i in range(1, 12):
        url = urljoin(root, f'node_{i}.htm')
        try:
            html = fetch_url(url)
            if 'pageLink' in html or 'ul02_l' in html:
                return url, html
        except Exception:
            pass
    return '', ''


def get_page_list(year: str, month: str, day: str, base_url: str = DEFAULT_BASE_URL) -> List[Tuple[str, str]]:
    """Return list of (page_url, page_name) for the issue date.

    Parse the '版面导航' section (anchors with id=pageLink) from any available node page.
    """
    root = _date_root(year, month, day, base_url)
    start_url, html = _pick_first_node(root)
    if not html:
        return []
    soup = BeautifulSoup(html, 'html.parser')
    items: List[Tuple[str, str]] = []
    # version 1: dedicated nav table
    for a in soup.find_all('a', id='pageLink', href=True):
        href = a['href'].strip()
        name = a.get_text(strip=True) or href
        absu = urljoin(start_url, href)
        valid_name = ''.join(ch for ch in name if ch not in r'\/:*?"<>|')
        items.append((absu, valid_name))
    # fallback: any node_*.htm anchors
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
    # ensure at least the start_url is included
    if start_url and not any(u == start_url for u, _ in items):
        items.insert(0, (start_url, 'A01'))
    return items


def get_title_list(year: str, month: str, day: str, page_url: str, base_url: str = DEFAULT_BASE_URL) -> List[str]:
    """Return list of article URLs from a page (node_*.htm)."""
    html = fetch_url(page_url)
    soup = BeautifulSoup(html, 'html.parser')
    links: List[str] = []
    seen = set()
    # primary: list under ul.ul02_l
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
    # secondary: image map areas
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
    # final safety: any href matching content_*.htm
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


def parse_article(html: str):
    """Parse article to (content_full, title_valid, title, body, summary)."""
    soup = BeautifulSoup(html, 'html.parser')
    raw = soup.decode()
    # title from enpproperty founder-title, or h1/h2/title
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

    # body from <founder-content> paragraphs, or common containers
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

