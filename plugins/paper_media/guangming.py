"""
光明日报独立插件

每个插件文件都需要导出名为 `handler` 的函数，作为工具入口。
"""

from typing import List
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from .base import Args, PaperInput, PaperOutput, News, fetch_url, find_available_date, safe_handler


Metadata = {
    "name": "get_guangming_news",
    "description": "获取光明日报新闻",
    "input": PaperInput.model_json_schema(),
    "output": PaperOutput.model_json_schema(),
}


def get_page_list(year: str, month: str, day: str):
    """获取光明日报指定日期的版面列表"""
    base_url = 'https://epaper.gmw.cn/gmrb/html'
    date_path = f"{year}-{month}/{day}/"
    first_page = urljoin(f"{base_url}/{date_path}", 'nbs.D110000gmrb_01.htm')
    html = fetch_url(first_page)
    soup = BeautifulSoup(html, 'html5lib')
    page_container = soup.find('div', id='pageList')
    anchors = page_container.find_all('a') if page_container else soup.find_all('a')
    
    link_list = []
    seen = set()
    for a in anchors:
        href = (a.get('href') or '').strip()
        text_value = a.get_text(strip=True)
        # 只保留HTML页面，忽略PDF和其他资源
        h = href.lower()
        if (not href) or h.startswith('javascript'):
            continue
        if ('.pdf' in h) or (not h.endswith('.htm')):
            continue
        if href in seen:
            continue
        seen.add(href)
        page_url = urljoin(f"{base_url}/{date_path}", href)
        name = text_value or href
        valid_name = ''.join(i for i in name if i not in r'\/:*?"<>|')
        link_list.append((page_url, valid_name))
    return link_list


def get_title_list(year: str, month: str, day: str, page_url: str):
    """获取指定版面的文章链接列表"""
    html = fetch_url(page_url)
    soup = BeautifulSoup(html, 'html5lib')
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
            abs_url = urljoin(page_url, href)
            link_list.append(abs_url)
    return [u for u in link_list if '/content/' in u or u.lower().endswith('.htm')]


def parse_article(html: str):
    """解析光明日报文章内容"""
    soup = BeautifulSoup(html, 'html5lib')
    title = ''
    if soup.h1:
        title = soup.h1.get_text(strip=True)
    elif soup.title:
        title = soup.title.get_text(strip=True)
    title_valid = ''.join(i for i in title if i not in r'\/:*?"<>|')
    
    body = ''
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


@safe_handler("光明日报")
def handler(args: Args[PaperInput], max_items: int, date_str: str, origin_name: str, logger) -> PaperOutput:
    """光明日报新闻抓取处理函数"""
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