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
    try:
        print(f"[jjckb_crawler] Fetching URL: {url}", flush=True)
        r = requests.get(url, headers=headers, timeout=10, proxies={'http': None, 'https': None})
        print(f"[jjckb_crawler] Fetched URL: {url} with status {r.status_code}", flush=True)
        r.raise_for_status()
        if not r.encoding:
            r.encoding = r.apparent_encoding
        else:
            # trust site header but fix if needed
            r.encoding = r.apparent_encoding
        return r.text
    except Exception as e:
        print(f"[jjckb_crawler] Failed to fetch {url}: {e}", flush=True)
        return ''


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
    """返回指定刊期的页面列表 (page_url, page_name)。

    Parse the '版面导航' section (anchors with id=pageLink) from any available node page.
    """
    root = _date_root(year, month, day, base_url)
    start_url, html = _pick_first_node(root)
    if not html:
        return []
    soup = BeautifulSoup(html, 'html.parser')
    items: List[Tuple[str, str]] = []
    # 版本 1：专用导航表
    for a in soup.find_all('a', id='pageLink', href=True):
        href = a['href'].strip()
        name = a.get_text(strip=True) or href
        absu = urljoin(start_url, href)
        valid_name = ''.join(ch for ch in name if ch not in r'\/:*?"<>|')
        items.append((absu, valid_name))
    # 兜底：任意 node_*.htm 链接
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
    # 确保至少包含起始页面 start_url
    if start_url and not any(u == start_url for u, _ in items):
        items.insert(0, (start_url, 'A01'))
    return items


def get_title_list(year: str, month: str, day: str, page_url: str, base_url: str = DEFAULT_BASE_URL) -> List[str]:
    """返回 node_*.htm 页面中的文章链接列表。"""
    html = fetch_url(page_url)
    soup = BeautifulSoup(html, 'html.parser')
    links: List[str] = []
    seen = set()
    # 优先：ul.ul02_l 下的列表
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
    # 次选：图片映射区域
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
    # 最终兜底：匹配 content_*.htm 的链接
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


def is_advertisement(title: str, body: str) -> bool:
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


def parse_article(html: str):
    """解析文章内容，返回 (content_full, title_valid, title, body, summary)。"""
    soup = BeautifulSoup(html, 'html.parser')
    raw = soup.decode()
    # 标题来源：enpproperty founder-title，或 h1/h2/title
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

    # 正文：优先 <founder-content> 段落，或常见容器
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
