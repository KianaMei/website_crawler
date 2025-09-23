"""
CFLP news/policy crawler (chinawuliu.com.cn).

Code/comment strings are English; user-facing strings are localized at API.
"""

# -*- coding: utf-8 -*-
from typing import List, Tuple, Optional, Dict
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from utils.tool import get_html_from_url
from model import News, NewsResponse


# Channels for China Federation of Logistics & Purchasing (chinawuliu.com.cn)
# - zcfg: Policies & Regulations landing
# - zixun: News landing (includes subpaths such as dzsp etc.)
CFLP_CHANNELS: Dict[str, Dict[str, str]] = {
    'zcfg': {
        'name': 'Policy',
        'base': 'http://www.chinawuliu.com.cn/zcfg/',
        'first_page': 'http://www.chinawuliu.com.cn/zcfg/',
        'page_pattern': 'http://www.chinawuliu.com.cn/zcfg/index_{}.html',
        'origin': '中国物流与采购联合会',
    },
    'zixun': {
        'name': 'News',
        'base': 'http://www.chinawuliu.com.cn/zixun/',
        'first_page': 'http://www.chinawuliu.com.cn/zixun/',
        'page_pattern': 'http://www.chinawuliu.com.cn/zixun/index_{}.html',
        'origin': '中国物流与采购联合会',
    },
}

# Accept dates like 2025-03-20, 2025/03/20, 2025.03.20, also with Chinese 年/月/日
DATE_RE = re.compile(r"(20\d{2})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})[日]?")


def _extract_date(text: str) -> Optional[str]:
    s = text or ''
    # normalize Chinese separators to '-' for easier matching
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
    # also attempt to strip time part like '2025-03-20 14:55:07'
    m2 = re.search(r"(20\d{2}-\d{1,2}-\d{1,2})", s)
    if m2:
        return m2.group(1)
    return None


def _find_content_node(soup: BeautifulSoup):
    # Try common article content containers used across sites
    for tag, attrs in [
        ('div', {'id': 'zoom'}),
        ('div', {'class': 'content'}),
        ('div', {'class': 'article'}),
        ('div', {'class': 'article-content'}),
        ('div', {'class': 'detail-main'}),
        ('div', {'class': 'content-txt'}),
        ('div', {'class': 'TRS_Editor'}),
        ('article', {}),
    ]:
        node = soup.find(tag, attrs=attrs)
        if node:
            return node
    return soup


def _summarize(text: str, length: int = 200) -> str:
    t = re.sub(r"\s+", " ", text).strip()
    return (t[:length].rstrip() + '...') if len(t) > length else t


class CFLPNewsCrawler:
    """Crawler for China Federation of Logistics & Purchasing (chinawuliu.com.cn)

    Supports channels: zcfg, zixun, dzsp
    Returns project-standard NewsResponse.
    """

    def __init__(self, channels: Optional[List[str]] = None, max_pages: int = 1, max_items: Optional[int] = 10, since_days: int = 7):
        # default focus: policies + news; treat any legacy 'dzsp' as 'zixun'
        chs = channels or ['zcfg', 'zixun']
        # compatibility mapping: dzsp -> zixun
        mapped: List[str] = []
        for ch in chs:
            mapped.append('zixun' if ch == 'dzsp' else ch)
        # de-duplicate while preserving order
        seen = set()
        self.channels = [c for c in mapped if not (c in seen or seen.add(c))]
        for ch in self.channels:
            if ch not in CFLP_CHANNELS:
                raise ValueError(f"Unsupported channel: {ch}")
        self.max_pages = max_pages
        self.max_items = max_items
        self.since_days = max(1, since_days)

    # -------- list page parsers --------
    def _parse_list_zcfg(self, html: str, base_url: str) -> List[Tuple[str, str, str]]:
        """Parse zcfg landing page aggregated lists."""
        soup = BeautifulSoup(html, 'html.parser')
        items: List[Tuple[str, str, str]] = []
        # Typical structure: ul.list-box > li > a + span.time
        for li in soup.select('ul.list-box li'):
            a = li.find('a', href=True)
            if not a:
                continue
            title = a.get_text(strip=True)
            href = a['href'].strip()
            url = urljoin(base_url, href)
            time_span = li.find('span', class_='time')
            date = _extract_date(time_span.get_text(strip=True) if time_span else li.get_text(" ", strip=True)) or ''
            if title and url:
                items.append((title, url, date))
        # Fallback: common list containers
        if not items:
            for li in soup.select('li'):
                a = li.find('a', href=True)
                if not a:
                    continue
                title = a.get_text(strip=True)
                href = a['href'].strip()
                url = urljoin(base_url, href)
                date = _extract_date(li.get_text(" ", strip=True)) or ''
                if title and url and 'javascript:' not in href:
                    items.append((title, url, date))
        return items

    def _parse_list_zixun_like(self, html: str, base_url: str) -> List[Tuple[str, str, str]]:
        """Parse zixun/dzsp style list page with ul.new-ul entries."""
        soup = BeautifulSoup(html, 'html.parser')
        items: List[Tuple[str, str, str]] = []
        # Primary (some historical templates):
        for li in soup.select('div.ul-list ul.new-ul > li'):
            title_a = li.select_one('p.new-title a[href]')
            if not title_a:
                continue
            title = title_a.get_text(strip=True)
            href = title_a['href'].strip()
            url = urljoin(base_url, href)
            # time like: <p class="new-time"><span class="new-unit">来源</span><span>2025-03-20 14:55:07</span></p>
            date_text = ''
            tm_spans = li.select('p.new-time span')
            if tm_spans:
                date_text = tm_spans[-1].get_text(strip=True)
            else:
                date_text = li.get_text(" ", strip=True)
            date = _extract_date(date_text) or ''
            if title and url:
                items.append((title, url, date))
        # Newer/current list layout mirrors zcfg: ul.list-box > li
        if not items:
            for li in soup.select('ul.list-box li'):
                a = li.find('a', href=True)
                if not a:
                    continue
                title = a.get_text(strip=True)
                href = a['href'].strip()
                url = urljoin(base_url, href)
                tm = li.find('span', class_='time')
                date_text = tm.get_text(strip=True) if tm else li.get_text(" ", strip=True)
                date = _extract_date(date_text) or ''
                if title and url:
                    items.append((title, url, date))
        # Fallback: generic anchors under list
        if not items:
            for a in soup.select('a[href]'):
                href = a['href'].strip()
                if not href or 'javascript:' in href:
                    continue
                title = a.get_text(strip=True)
                url = urljoin(base_url, href)
                if title and url and '/zixun/' in url:
                    items.append((title, url, _extract_date(title) or ''))
        return items

    def _parse_detail(self, url: str) -> Tuple[str, Optional[str]]:
        html = get_html_from_url(url)
        if not html:
            return '', None
        soup = BeautifulSoup(html, 'html.parser')
        node = _find_content_node(soup)
        text = node.get_text('\n', strip=True)
        summary = _summarize(text)
        # date fallback: look for common date patterns in page text
        # try meta, time labels, or anywhere in the page
        page_text = soup.get_text('\n', strip=True)
        date_fb = _extract_date(page_text)
        return summary, date_fb

    def _iter_list_pages(self, conf: Dict[str, str]):
        # yields list page URLs according to max_pages
        first = conf.get('first_page')
        pattern = conf.get('page_pattern')
        if not first:
            return
        yield first
        if not pattern:
            return
        for i in range(2, self.max_pages + 1):
            yield pattern.format(i)

    def _fetch_channel(self, ch_key: str) -> List[Tuple[str, str, str]]:
        conf = CFLP_CHANNELS[ch_key]
        base = conf['base']
        acc: List[Tuple[str, str, str]] = []
        for url in self._iter_list_pages(conf):
            html = get_html_from_url(url)
            if not html:
                break
            if ch_key == 'zcfg':
                items = self._parse_list_zcfg(html, base)
            else:
                items = self._parse_list_zixun_like(html, base)
            if not items:
                break
            acc.extend(items)
            if self.max_items and len(acc) >= self.max_items * 2: # fetch more to filter
                break
        return acc

    def _category_rank(self, url: str, title: str) -> int:
        """Rank for zixun demotion: 0 = normal (front), 1 = demoted (tail)."""
        u = (url or '').lower()
        t = title or ''
        demote_keywords = [
            # 企业信息
            'qiyexinxi', 'qiye', 'gongsi', '企业信息', '企业', '公司', '品牌',
            # 产业自动化
            'zidonghua', 'automation', '自动化', '产业自动化', '智能制造', '工业互联网',
            # 物流装备
            'wuliu', 'zhuangbei', 'shebei', '物流装备', '装备', '设备', '叉车', 'agv', '机器人', '仓储',
            # 历史遗留：将 dzsp 子路径也视为资讯类的一部分
            '/zixun/dzsp/', 'dzsp'
        ]
        s = u + ' ' + t
        return 1 if any(kw in s for kw in demote_keywords) else 0

    def get_news(self) -> NewsResponse:
        try:
            from datetime import datetime, timedelta
            
            all_items = []
            for ch in self.channels:
                conf = CFLP_CHANNELS[ch]
                origin = '中国物流与采购联合会'
                items = self._fetch_channel(ch)
                for title, url, date in items:
                    all_items.append({'title': title, 'url': url, 'date': date, 'origin': origin, 'channel': ch})

            # Enrich items with details
            enriched_items = []
            for item in all_items:
                summary, date_fb = self._parse_detail(item['url'])
                use_date = item['date'] or date_fb or ''
                enriched_items.append({**item, 'summary': summary, 'date': use_date})

            # Find the latest date among all fetched items
            latest_date = None
            for item in enriched_items:
                if item['date']:
                    try:
                        d = datetime.strptime(item['date'], '%Y-%m-%d').date()
                        if latest_date is None or d > latest_date:
                            latest_date = d
                    except ValueError:
                        continue

            # If a latest date is found, filter based on it
            filtered_items = []
            if latest_date:
                threshold = latest_date - timedelta(days=self.since_days)
                for item in enriched_items:
                    if item['date']:
                        try:
                            d = datetime.strptime(item['date'], '%Y-%m-%d').date()
                            if d >= threshold:
                                filtered_items.append(item)
                        except ValueError:
                            pass
                    else:
                         # Keep items with no date if no date filter is applied
                         pass
            else: # If no dates found, return all items
                filtered_items = enriched_items


            # Sort zixun items and combine
            news_list: List[News] = []
            zixun_items = [item for item in filtered_items if item['channel'] == 'zixun']
            zcfg_items = [item for item in filtered_items if item['channel'] == 'zcfg']

            def sort_key(item):
                rank = self._category_rank(item['url'], item['title'])
                try:
                    ts = datetime.strptime(item['date'], '%Y-%m-%d')
                except (ValueError, TypeError):
                    ts = datetime.min
                return (rank, -ts.timestamp())

            zixun_items.sort(key=sort_key)

            # Combine lists, zcfg first
            sorted_items = zcfg_items + zixun_items
            
            for item in sorted_items:
                if self.max_items and len(news_list) >= self.max_items:
                    break
                news_list.append(News(
                    title=item['title'],
                    url=item['url'],
                    origin=item['origin'],
                    summary=item['summary'],
                    publish_date=item['date']
                ))

            status = 'OK' if news_list else 'EMPTY'
            return NewsResponse(news_list=news_list or None, status=status,
                                err_code=None if news_list else 'NO_DATA',
                                err_info=None if news_list else 'No news parsed')
        except Exception as e:
            return NewsResponse(status='ERROR', err_code='CRAWL_UNEXPECTED_ERROR', err_info=str(e))


if __name__ == '__main__':
    # Default: focus on Policy + News (dzsp treated as zixun internally)
    crawler = CFLPNewsCrawler(channels=['zcfg', 'zixun'], max_pages=2, max_items=8, since_days=7)
    resp = crawler.get_news()
    print(resp.model_dump())
