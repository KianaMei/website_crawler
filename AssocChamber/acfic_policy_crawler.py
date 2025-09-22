"""
ACFIC policy crawler.

Code/comment strings are English; user-facing strings are localized at API.
"""

# -*- coding: utf-8 -*-
from typing import List, Tuple, Optional, Dict
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from utils.tool import get_html_from_url
from model import News, NewsResponse


# ACFIC channels configuration (Central/Ministries/Local/ACFIC/Interpretation)
ACFIC_CHANNELS: Dict[str, Dict[str, str]] = {
    'zy': {
        'name': 'Central',
        'base': 'https://www.acfic.org.cn/zcsd/zy/',
        'first_page': 'https://www.acfic.org.cn/zcsd/zy/index.html',
        'page_pattern': 'https://www.acfic.org.cn/zcsd/zy/index_{}.html',  # {} => 1,2,...
        'origin': 'ACFIC-Central',
    },
    'bw': {
        'name': 'Ministries',
        'base': 'https://www.acfic.org.cn/zcsd/bw/',
        'first_page': 'https://www.acfic.org.cn/zcsd/bw/index.html',
        'page_pattern': 'https://www.acfic.org.cn/zcsd/bw/index_{}.html',
        'origin': 'ACFIC-Ministries',
    },
    'df': {
        'name': 'Local',
        'base': 'https://www.acfic.org.cn/zcsd/df/',
        'first_page': 'https://www.acfic.org.cn/zcsd/df/index.html',
        'page_pattern': 'https://www.acfic.org.cn/zcsd/df/index_{}.html',
        'origin': 'ACFIC-Local',
    },
    'qggsl': {
        'name': 'ACFIC',
        'base': 'https://www.acfic.org.cn/zcsd/qggsl/',
        'first_page': 'https://www.acfic.org.cn/zcsd/qggsl/index.html',
        'page_pattern': 'https://www.acfic.org.cn/zcsd/qggsl/index_{}.html',
        'origin': 'ACFIC',
    },
    'jd': {
        'name': 'Interpretation',
        'base': 'https://www.acfic.org.cn/zcsd/jd/',
        'first_page': 'https://www.acfic.org.cn/zcsd/jd/index.html',
        'page_pattern': 'https://www.acfic.org.cn/zcsd/jd/index_{}.html',
        'origin': 'ACFIC-Interpretation',
    },
}


def _extract_date(text: str) -> Optional[str]:
    """Extract date string (YYYY-MM-DD) from mixed Chinese/ASCII formats."""
    s = (text or '').strip()
    # normalize Chinese separators
    s = s.replace('年', '-').replace('月', '-').replace('日', '')
    m = re.search(r"(20\d{2})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{1,2})", s)
    if m:
        y, mo, d = m.groups()
        try:
            from datetime import datetime
            dt = datetime(int(y), int(mo), int(d))
            return dt.strftime('%Y-%m-%d')
        except Exception:
            return None
    # fallback: just the YYYY-MM-DD in long strings
    m2 = re.search(r"(20\d{2}-\d{1,2}-\d{1,2})", s)
    if m2:
        return m2.group(1)
    return None


def _find_content_node(soup: BeautifulSoup):
    for tag, attrs in [
        ('div', {'class': 'TRS_Editor'}),
        ('div', {'class': 'zhengwen'}),
        ('div', {'class': 'article'}),
        ('div', {'class': 'content'}),
        ('div', {'id': 'zoom'}),
        ('article', {}),
    ]:
        node = soup.find(tag, attrs=attrs)
        if node:
            return node
    return soup


def _summarize(text: str, length: int = 200) -> str:
    t = re.sub(r"\s+", " ", text).strip()
    if len(t) > length:
        return t[:length].rstrip() + '...'
    return t


class ACFICPolicyCrawler:
    """Crawler for ACFIC policy channels.

    Returns project-standard NewsResponse.
    """

    def __init__(self, channels: Optional[List[str]] = None, max_pages: int = 1, max_items: Optional[int] = 5):
        # default: all channels
        self.channels = channels or list(ACFIC_CHANNELS.keys())
        for ch in self.channels:
            if ch not in ACFIC_CHANNELS:
                raise ValueError(f"Unsupported channel: {ch}")
        self.max_pages = max_pages
        self.max_items = max_items

    def _parse_list(self, html: str, base_url: str) -> List[Tuple[str, str, str]]:
        """Parse list page. Return [(title, url, date)]."""
        soup = BeautifulSoup(html, 'html.parser')
        container = soup.find('div', class_='right_qlgz') or soup
        items: List[Tuple[str, str, str]] = []
        for ul in container.find_all('ul'):
            for li in ul.find_all('li'):
                a = li.find('a', href=True)
                if not a:
                    continue
                # title sits in first span; date in span.time
                title_span = a.find('span')
                date_span = a.find('span', class_='time')
                title = (title_span.get_text(strip=True) if title_span else a.get_text(strip=True) or '').strip()
                href = a['href'].strip()
                url = urljoin(base_url, href)
                date_text = date_span.get_text(strip=True) if date_span else li.get_text(" ", strip=True)
                date = _extract_date(date_text) or ''
                if title and url:
                    items.append((title, url, date))
        return items

    def _parse_detail_summary(self, url: str) -> str:
        html = get_html_from_url(url)
        if not html:
            return ''
        soup = BeautifulSoup(html, 'html.parser')
        node = _find_content_node(soup)
        text = node.get_text('\n', strip=True)
        return _summarize(text)

    def _fetch_channel(self, ch_key: str) -> List[Tuple[str, str, str]]:
        conf = ACFIC_CHANNELS[ch_key]
        base = conf['base']
        page = 1
        acc: List[Tuple[str, str, str]] = []
        while True:
            url = conf['first_page'] if page == 1 else conf['page_pattern'].format(page - 1)
            html = get_html_from_url(url)
            if not html:
                break
            items = self._parse_list(html, base)
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
        for ch in self.channels:
            conf = ACFIC_CHANNELS[ch]
            origin = conf['origin']
            for title, url, date in self._fetch_channel(ch):
                summary = self._parse_detail_summary(url)
                news_list.append(News(title=title, url=url, origin=origin, summary=summary, publish_date=date or ''))
        status = 'OK' if news_list else 'EMPTY'
        return NewsResponse(news_list=news_list or None, status=status,
                            err_code=None if news_list else 'NO_DATA',
                            err_info=None if news_list else 'No policies parsed')


if __name__ == '__main__':
    crawler = ACFICPolicyCrawler(max_pages=1, max_items=5)
    resp = crawler.get_news()
    print(resp.model_dump())
