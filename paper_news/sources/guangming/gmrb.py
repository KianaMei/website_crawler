import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

DEFAULT_BASE_URL = 'https://epaper.gmw.cn/gmrb/html'


def fetch_url(url: str) -> str:
    headers = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/68.0.3440.106 Safari/537.36',
    }
    r = requests.get(url, headers=headers, timeout=30, proxies={'http': None, 'https': None})
    r.raise_for_status()
    r.encoding = r.apparent_encoding
    return r.text


def get_page_list(year: str, month: str, day: str, base_url: str = DEFAULT_BASE_URL):
    base_url = base_url.rstrip('/')
    date_path = f"{year}-{month}/{day}/"
    first_page = urljoin(f"{base_url}/{date_path}", 'nbs.D110000gmrb_01.htm')
    html = fetch_url(first_page)
    soup = BeautifulSoup(html, 'html.parser')
    page_container = soup.find('div', id='pageList')
    anchors = page_container.find_all('a') if page_container else soup.find_all('a')
    link_list = []
    seen = set()
    for a in anchors:
        href = (a.get('href') or '').strip()
        text_value = a.get_text(strip=True)
        if not href or href.lower().startswith('javascript'):
            continue
        if href in seen:
            continue
        seen.add(href)
        page_url = urljoin(f"{base_url}/{date_path}", href)
        name = text_value or href
        valid_name = ''.join(i for i in name if i not in r'\/:*?"<>|')
        link_list.append((page_url, valid_name))
    return link_list


def get_title_list(year: str, month: str, day: str, page_url: str, base_url: str = DEFAULT_BASE_URL):
    html = fetch_url(page_url)
    soup = BeautifulSoup(html, 'html.parser')
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
            # 规范化相对链接为绝对链接
            abs_url = urljoin(page_url, href)
            link_list.append(abs_url)
    # 仅保留内容页链接
    filtered = [u for u in link_list if '/content/' in u or u.lower().endswith('.htm')]
    return filtered


def parse_article(html: str):
    soup = BeautifulSoup(html, 'html.parser')
    title = ''
    if soup.h1:
        title = soup.h1.get_text(strip=True)
    elif soup.title:
        title = soup.title.get_text(strip=True)
    title_valid = ''.join(i for i in title if i not in r'\/:*?"<>|')
    body = ''
    # 尝试常见的正文容器选择器（id/class）
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
