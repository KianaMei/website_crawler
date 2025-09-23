"""NDRC 新闻抓取（统一返回 NewsResponse）。"""
from typing import List, Dict, Optional, Tuple
import re
from urllib.parse import urljoin
from datetime import datetime

from bs4 import BeautifulSoup

from utils.tool import get_html_from_url
from model import News, NewsResponse


# 国家发改委分类配置（键为简写；name 为中文展示名）
POLICY_CATEGORIES: Dict[str, Dict[str, str]] = {
    'fzggwl': {
        'name': '发展改革委',
        'category_path': '/xxgk/zcfb/fzggwl',
        'first_page': 'https://www.ndrc.gov.cn/xxgk/zcfb/fzggwl/index.html',
        'page_pattern': 'https://www.ndrc.gov.cn/xxgk/zcfb/fzggwl/index_{}.html',
    },
    'ghxwj': {
        'name': '规范性文件',
        'category_path': '/xxgk/zcfb/ghxwj',
        'first_page': 'https://www.ndrc.gov.cn/xxgk/zcfb/ghxwj/index.html',
        'page_pattern': 'https://www.ndrc.gov.cn/xxgk/zcfb/ghxwj/index_{}.html',
    },
    'ghwb': {
        'name': '规划文本',
        'category_path': '/xxgk/zcfb/ghwb',
        'first_page': 'https://www.ndrc.gov.cn/xxgk/zcfb/ghwb/index.html',
        'page_pattern': 'https://www.ndrc.gov.cn/xxgk/zcfb/ghwb/index_{}.html',
    },
    'gg': {
        'name': '公告',
        'category_path': '/xxgk/zcfb/gg',
        'first_page': 'https://www.ndrc.gov.cn/xxgk/zcfb/gg/index.html',
        'page_pattern': 'https://www.ndrc.gov.cn/xxgk/zcfb/gg/index_{}.html',
    },
    'tz': {
        'name': '通知',
        'category_path': '/xxgk/zcfb/tz',
        'first_page': 'https://www.ndrc.gov.cn/xxgk/zcfb/tz/index.html',
        'page_pattern': 'https://www.ndrc.gov.cn/xxgk/zcfb/tz/index_{}.html',
    },
}

DATE_RE = re.compile(r"(20\d{2})[-/.年]\s?(\d{1,2})[-/.月]\s?(\d{1,2})[日]?")


def _safe_join_url(href: str, category_path: str) -> str:
    if href.startswith('http://') or href.startswith('https://'):
        return href
    href = href.lstrip('./')
    base = 'https://www.ndrc.gov.cn'
    if category_path and not href.startswith('/'):
        return f"{base}{category_path}/{href}"
    return urljoin(base, href)


def _extract_date(text: str) -> Optional[str]:
    m = DATE_RE.search(text)
    if m:
        y, mo, d = m.groups()
        try:
            dt = datetime(int(y), int(mo), int(d))
            return dt.strftime('%Y-%m-%d')
        except Exception:
            return None
    # fallback: 2024-12-31 pattern
    m2 = re.search(r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if m2:
        y, mo, d = m2.groups()
        try:
            dt = datetime(int(y), int(mo), int(d))
            return dt.strftime('%Y-%m-%d')
        except Exception:
            return None
    return None


def _find_content_node(soup: BeautifulSoup):
    for tag, attrs in [
        ('div', {'class': 'article_con'}),
        ('div', {'class': 'TRS_Editor'}),
        ('div', {'class': 'content'}),
        ('div', {'class': 'article-content'}),
        ('div', {'class': 'main-content'}),
        ('div', {'id': 'zoom'}),
        ('article', {}),
    ]:
        node = soup.find(tag, attrs=attrs)
        if node:
            return node
    return soup


def _summarize(text: str, length: int = 180) -> str:
    t = re.sub(r"\s+", " ", text).strip()
    if len(t) > length:
        return t[:length].rstrip() + '...'
    return t


class NDRCNewsCrawler:
    """Return NewsResponse for selected NDRC categories (project-standard output)."""

    def __init__(self, categories: Optional[List[str]] = None, max_pages: int = 1, max_items: Optional[int] = 10):
        self.categories = categories or list(POLICY_CATEGORIES.keys())
        self.max_pages = max_pages
        self.max_items = max_items

    def _parse_list(self, html: str, cat_key: str) -> List[Tuple[str, str, str]]:
        """Return list of (title, url, date) from a list page.
        Only keep li items that contain a date span to avoid picking up nav links.
        """
        soup = BeautifulSoup(html.encode('utf-8'), 'html.parser')
        items: List[Tuple[str, str, str]] = []
        for li in soup.find_all('li'):
            a = li.find('a', href=True)
            date_span = li.find('span')
            if not a or not date_span:
                continue
            title = (a.get('title') or a.get_text(strip=True) or '').strip()
            href = a['href'].strip()
            url = _safe_join_url(href, POLICY_CATEGORIES[cat_key]['category_path'])
            date_text = date_span.get_text(strip=True)
            date = _extract_date(date_text) or ''
            if title and url:
                items.append((title, url, date))
        return items

    def _parse_detail_summary(self, url: str) -> str:
        html = get_html_from_url(url)
        if not html:
            return ''
        soup = BeautifulSoup(html.encode('utf-8'), 'html.parser')
        node = _find_content_node(soup)
        text = node.get_text('\n', strip=True)
        return _summarize(text)

    def _fetch_category(self, cat_key: str) -> List[Tuple[str, str, str]]:
        conf = POLICY_CATEGORIES.get(cat_key)
        if not conf:
            return []
        page = 1
        acc: List[Tuple[str, str, str]] = []
        while True:
            url = conf['first_page'] if page == 1 else conf['page_pattern'].format(page - 1)
            html = get_html_from_url(url)
            if not html:
                break
            items = self._parse_list(html, cat_key)
            if not items:
                break
            acc.extend(items)
            if self.max_items and len(acc) >= self.max_items:
                acc = acc[: self.max_items]
                break
            if page >= self.max_pages:
                break
            page += 1
        return acc

    def get_news(self) -> NewsResponse:
        news_list: List[News] = []
        for cat_key in self.categories:
            conf = POLICY_CATEGORIES.get(cat_key)
            if not conf:
                continue
            for title, url, date in self._fetch_category(cat_key):
                summary = self._parse_detail_summary(url)
                n = News(title=title, url=url, origin='国家发改委', summary=summary, publish_date=date or '')
                news_list.append(n)
        status = 'OK' if news_list else 'EMPTY'
        return NewsResponse(news_list=news_list or None, status=status, err_code=None if news_list else 'NO_DATA', err_info=None if news_list else 'No news parsed')
