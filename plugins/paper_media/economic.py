"""
经济日报独立插件

每个插件文件都需要导出名为 `handler` 的函数，作为工具入口。
"""

from typing import List
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from .base import Args, PaperInput, PaperOutput, News, fetch_url, find_available_date, safe_handler


Metadata = {
    "name": "get_economic_news",
    "description": "获取经济日报新闻",
    "input": PaperInput.model_json_schema(),
    "output": PaperOutput.model_json_schema(),
}


def get_page_list(year: str, month: str, day: str):
    """获取经济日报指定日期的版面列表"""
    base_url = 'http://paper.ce.cn/pc'
    base_layout = f'{base_url}/layout/{year}{month}/{day}/'
    url = urljoin(base_layout, 'node_01.html')
    html = fetch_url(url)
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


def get_title_list(year: str, month: str, day: str, page_url: str):
    """获取指定版面的文章链接列表"""
    html = fetch_url(page_url)
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


def best_content_div(soup: BeautifulSoup):
    """智能选择最佳内容容器"""
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


def parse_article(html: str):
    """解析经济日报文章内容"""
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
    
    container = best_content_div(s)
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


@safe_handler("经济日报")
def handler(args: Args[PaperInput], max_items: int, date_str: str, origin_name: str, logger) -> PaperOutput:
    """经济日报新闻抓取处理函数"""
    y, m, d = find_available_date(get_page_list, date_str)
    news_list: List[News] = []
    
    for page_url, _ in get_page_list(y, m, d):
        if len(news_list) >= max_items:
            break
        for url in get_title_list(y, m, d, page_url):
            if len(news_list) >= max_items:
                break
            html = fetch_url(url)
            _, _, title, body, summary = parse_article(html)
            news_list.append(News(
                title=title or '', 
                url=url, 
                origin=origin_name, 
                summary=summary or body or '', 
                publish_date=f"{y}-{m}-{d}"
            ))
    
    status = 'OK' if news_list else 'EMPTY'
    return PaperOutput(
        news_list=news_list or None, 
        status=status, 
        err_code=None if news_list else 'NO_DATA', 
        err_info=None if news_list else 'No news parsed'
    )