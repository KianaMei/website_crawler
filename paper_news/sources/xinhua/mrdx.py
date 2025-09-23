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
    r = requests.get(url, headers=headers, timeout=30, proxies={'http': None, 'https': None})
    r.raise_for_status()
    # 强制使用 UTF-8 解码中文站点，避免乱码
    r.encoding = 'utf-8'
    return r.text


def _candidate_first_pages(date_str: str) -> List[str]:
    # 尝试首页文件名的常见变体
    return [
        f'Page01DK.htm',
        f'Page01.htm',
        f'page01.htm',
        f'Page01A.htm',
        f'Page01B.htm',
    ]


def get_page_list(year: str, month: str, day: str, base_url: str = DEFAULT_BASE_URL) -> List[Tuple[str, str]]:
    """返回指定刊期的页面列表 (page_url, page_name)。

    示例日期目录: http://mrdx.cn/content/20250919/
    页面通常为 Page01DK.htm、Page02DK.htm 等，导航位于 'div.shijuedaohang' 区域。
    """
    date_dir = f"{year}{month}{day}"
    root = f"{base_url.rstrip('/')}/{date_dir}/"

    # 寻找能正常加载且包含导航的首页
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
            # 名称优先取嵌套的 h4 文本；否则取图片 alt
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
    # 兜底：最多猜测前 16 个页面
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
    """返回指定页面的文章链接列表。

    文章通常通过带有自定义属性 'daoxiang' 的 <a> 链接（相对地址如 'Articel01001NU.htm'）指向。
    """
    html = fetch_url(page_url)
    # 快速扫描包含 daoxiang 的链接
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
    # 兜底：匹配包含 'Articel' 模式的 href
    if not links:
        rels2 = re.findall(r"href=\"([^\"]*Articel[^\"]*\.htm)\"", html, flags=re.I)
        for rel in rels2:
            absu = urljoin(page_url, rel)
            if absu not in seen:
                seen.add(absu)
                links.append(absu)
    return links


def parse_article(html: str):
    """解析文章内容页，返回 (content_full, title_valid, title, body, summary)。"""
    soup = BeautifulSoup(html, 'html.parser')
    # 标题候选
    title = ''
    h2 = soup.find('h2')
    if h2 and h2.get_text(strip=True):
        title = h2.get_text(strip=True)
    elif soup.title:
        title = soup.title.get_text(strip=True)
    tvalid = ''.join(ch for ch in title if ch not in r'\/:*?"<>|')

    # 正文优先选择 #contenttext 容器
    body = ''
    content_div = soup.find(id='contenttext') or soup.find('div', class_='contenttext')
    if content_div:
        # 部分页面正文包含嵌入式 HTML；用分隔符提取纯文本
        body = content_div.get_text('\n', strip=True)
    if not body:
        # 常见兜底选择器
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
