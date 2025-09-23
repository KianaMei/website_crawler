import os
from typing import List, Tuple
import requests
import bs4
from urllib.parse import urljoin

# 与原始脚本行为保持一致
DEFAULT_BASE_URL = 'http://paper.ce.cn/pc'


def fetch_url(url: str) -> str:
    headers = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/68.0.3440.106 Safari/537.36',
    }
    r = requests.get(url, headers=headers, timeout=30, proxies={'http': None, 'https': None})
    r.raise_for_status()
    r.encoding = r.apparent_encoding
    return r.text


def get_page_list(year: str, month: str, day: str, base_url: str = DEFAULT_BASE_URL) -> List[Tuple[str, str]]:
    """返回指定刊期的页面列表 (page_url, page_name)。"""
    base_url = base_url.rstrip('/')
    base_layout = f'{base_url}/layout/{year}{month}/{day}/'
    url = urljoin(base_layout, 'node_01.html')

    html = fetch_url(url)
    bsobj = bs4.BeautifulSoup(html, 'html.parser')

    link_list: List[Tuple[str, str]] = []
    seen = set()
    for a in bsobj.find_all('a'):
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
        valid_name = ''.join(ch for ch in name if ch not in r'\/:*?"<>|') or '版面'
        link_list.append((page_url, valid_name))

    if not any(x[0].endswith('node_01.html') for x in link_list):
        link_list.insert(0, (url, '第01版'))

    return link_list


def _best_content_div(bsobj: bs4.BeautifulSoup):
    priority = ['#content', '#ozoom', 'div.content', 'div#zoom', 'div#articleContent', 'div.article']
    for sel in priority:
        el = bsobj.select_one(sel)
        if el:
            return el
    best = None
    best_len = 0
    for div in bsobj.find_all('div'):
        ps = div.find_all('p')
        if not ps:
            continue
        txt = '\n'.join(p.get_text(strip=True) for p in ps)
        if len(txt) > best_len:
            best = div
            best_len = len(txt)
    return best


def parse_article(html: str):
    bsobj = bs4.BeautifulSoup(html, 'html.parser')

    title_text = ''
    if bsobj.h1 and bsobj.h1.get_text(strip=True):
        title_text = bsobj.h1.get_text(strip=True)
    elif bsobj.h2 and bsobj.h2.get_text(strip=True):
        title_text = bsobj.h2.get_text(strip=True)
    elif bsobj.title:
        title_text = bsobj.title.get_text(strip=True)
    title_valid = ''.join(i for i in title_text if i not in r'\/:*?"<>|')

    h3 = bsobj.h3.get_text(strip=True) if bsobj.h3 else ''
    h2 = bsobj.h2.get_text(strip=True) if bsobj.h2 else ''

    container = _best_content_div(bsobj)
    content_body = ''
    if container:
        p_list = container.find_all('p')
        for p in p_list:
            content_body += p.get_text() + '\n'
    content_body = content_body.strip() + ('\n' if content_body and not content_body.endswith('\n') else '')

    summary = content_body.strip()

    content_full = ''
    content_full += (h3 + '\n') if h3 else ''
    content_full += (title_text + '\n') if title_text else ''
    if h2 and (not title_text or h2 != title_text):
        content_full += (h2 + '\n')
    content_full += content_body

    return content_full, title_valid, title_text, content_body, summary


def get_title_list(year: str, month: str, day: str, page_url: str, base_url: str = DEFAULT_BASE_URL) -> List[str]:
    html = fetch_url(page_url)
    bsobj = bs4.BeautifulSoup(html, 'html.parser')
    link_list: List[str] = []
    seen = set()
    for a in bsobj.find_all('a'):
        href = (a.get('href') or '').strip()
        if not href.endswith('.html'):
            continue
        if 'content_' not in href:
            continue
        abs_url = urljoin(page_url, href)
        if abs_url in seen:
            continue
        seen.add(abs_url)
        link_list.append(abs_url)
    return link_list
