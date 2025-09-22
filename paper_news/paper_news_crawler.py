import datetime
from typing import List, Tuple

from model import News, NewsResponse  # type: ignore
from .sources.peopledaily import rmrb as mod_rmrb
from .sources.guangming import gmrb as mod_gmrb
from .sources.economic import jjrb as mod_jjrb
from .sources.qiushi import qiushi as mod_qiushi
from .sources.xinhua import mrdx as mod_mrdx
from .sources.jjckb import jjckb as mod_jjckb

SUPPORTED_SOURCES = {
    'peopledaily': '人民日报',
    'guangming': '光明日报',
    'economic': '经济日报',
    'qiushi': '求是',
}
SUPPORTED_SOURCES['xinhua'] = '新华每日电讯'
SUPPORTED_SOURCES['jjckb'] = '经济参考报'


class PaperNewsCrawler:
    """
    Aggregate wrapper to fetch paper news from multiple official newspapers.
    source: one of peopledaily|guangming|economic|chinadaily|qiushi
    max_items: limit number of articles returned.
    since_days: only used by chinadaily to filter recent days (default 3)
    """

    def __init__(self, source: str = 'peopledaily', max_items: int = 10, since_days: int = 3, date: str | None = None):
        self.source = source.lower()
        self.max_items = max(1, min(max_items, 50))
        self.since_days = max(1, min(since_days, 365))
        self.date = date  # YYYY-MM-DD or None

    def _today_parts(self):
        today = datetime.date.today()
        return f"{today.year}", f"{today.month:02d}", f"{today.day:02d}"

    def _find_available_date(self, get_pages_func, max_back_days: int = 7) -> Tuple[str, str, str]:
        # If user specified a date, try that first
        if self.date:
            try:
                y, m, d = self.date.split('-')
                pages = get_pages_func(y, m, d)
                if pages:
                    return y, m, d
            except Exception:
                pass
        y0, m0, d0 = self._today_parts()
        base_date = datetime.date(int(y0), int(m0), int(d0))
        for i in range(max_back_days + 1):
            day = base_date - datetime.timedelta(days=i)
            y, m, d = f"{day.year}", f"{day.month:02d}", f"{day.day:02d}"
            try:
                pages = get_pages_func(y, m, d)
                if pages:
                    return y, m, d
            except Exception:
                pass
        return y0, m0, d0

    def _build_news(self, title: str, url: str, origin: str, summary: str, publish_date: str) -> News:
        return News(title=title or '', url=url or '', origin=origin, summary=(summary or ''), publish_date=publish_date)

    def get_news(self) -> NewsResponse:
        if self.source not in SUPPORTED_SOURCES:
            return NewsResponse(news_list=None, status='ERROR', err_code='INVALID_SOURCE', err_info=f"Unsupported source: {self.source}")

        origin = SUPPORTED_SOURCES[self.source]

        try:
            if self.source == 'peopledaily':
                y, m, d = self._find_available_date(mod_rmrb.get_page_list)
                pages = mod_rmrb.get_page_list(y, m, d)
                news_list: List[News] = []
                for page_url, _ in pages:
                    if len(news_list) >= self.max_items:
                        break
                    urls = mod_rmrb.get_title_list(y, m, d, page_url)
                    for url in urls:
                        if len(news_list) >= self.max_items:
                            break
                        html = mod_rmrb.fetch_url(url)
                        _, _, title, content_body, summary = mod_rmrb.parse_article(html)
                        news_list.append(self._build_news(title, url, origin, summary or content_body, f"{y}-{m}-{d}"))
                return NewsResponse(news_list=news_list)

            if self.source == 'guangming':
                y, m, d = self._find_available_date(mod_gmrb.get_page_list)
                pages = mod_gmrb.get_page_list(y, m, d)
                news_list: List[News] = []
                for page_url, _ in pages:
                    if len(news_list) >= self.max_items:
                        break
                    urls = mod_gmrb.get_title_list(y, m, d, page_url)
                    for url in urls:
                        if len(news_list) >= self.max_items:
                            break
                        html = mod_gmrb.fetch_url(url)
                        _, _, title, content_body, summary = mod_gmrb.parse_article(html)
                        news_list.append(self._build_news(title, url, origin, summary or content_body, f"{y}-{m}-{d}"))
                return NewsResponse(news_list=news_list)

            if self.source == 'economic':
                y, m, d = self._find_available_date(mod_jjrb.get_page_list)
                pages = mod_jjrb.get_page_list(y, m, d)
                news_list: List[News] = []
                for page_url, _ in pages:
                    if len(news_list) >= self.max_items:
                        break
                    urls = mod_jjrb.get_title_list(y, m, d, page_url)
                    for url in urls:
                        if len(news_list) >= self.max_items:
                            break
                        html = mod_jjrb.fetch_url(url)
                        _, _, title, content_body, summary = mod_jjrb.parse_article(html)
                        news_list.append(self._build_news(title, url, origin, summary or content_body, f"{y}-{m}-{d}"))
                return NewsResponse(news_list=news_list)
            if self.source == 'qiushi':
                # 1) Try latest issue directly from root index
                candidates = mod_qiushi.get_issue_candidates_from_root(mod_qiushi.ROOT_INDEX_URL)
                chosen = None
                # If user provided date, prefer that issue (yyyymmdd)
                target_idate = None
                if self.date:
                    try:
                        y, m, d = self.date.split('-')
                        target_idate = f"{y}{m}{d}"
                    except Exception:
                        target_idate = None
                for name, iurl, idate in candidates:
                    if target_idate and idate == target_idate and mod_qiushi.is_issue_directory(iurl):
                        chosen = (name, iurl, idate)
                        break
                    if not target_idate and mod_qiushi.is_issue_directory(iurl):
                        chosen = (name, iurl, idate)
                        break
                # 2) Fallback to year directory under /dukan/qs/
                if not chosen:
                    years = mod_qiushi.get_year_list(mod_qiushi.ROOT_INDEX_URL)
                    if not years:
                        return NewsResponse(news_list=[])
                    preferred = [t for t in years if '/dukan/qs/' in t[1]]
                    if preferred:
                        yname, yurl = preferred[0]
                    else:
                        yname, yurl = years[0]
                    issues = mod_qiushi.get_issue_list(yurl)
                    if issues:
                        for iname, iurl, idate in reversed(issues):
                            if target_idate and idate == target_idate and mod_qiushi.is_issue_directory(iurl):
                                chosen = (iname, iurl, idate)
                                break
                            if not target_idate and mod_qiushi.is_issue_directory(iurl):
                                chosen = (iname, iurl, idate)
                                break
                        if not chosen:
                            chosen = issues[-1]
                if not chosen:
                    return NewsResponse(news_list=[])
                iname, iurl, idate = chosen
                links = mod_qiushi.get_article_list(iurl)
                news_list: List[News] = []
                date_str = f"{idate[:4]}-{idate[4:6]}-{idate[6:]}"
                for url in links:
                    html = mod_qiushi.fetch_url(url)
                    _, _, title, body, summary = mod_qiushi.parse_article(html)
                    from model import News as _News  # local alias
                    news_list.append(_News(title=title or '', url=url, origin=origin, summary=body or '', publish_date=date_str))
                return NewsResponse(news_list=news_list)

            if self.source == 'xinhua':
                y, m, d = self._find_available_date(mod_mrdx.get_page_list)
                pages = mod_mrdx.get_page_list(y, m, d)
                news_list: List[News] = []
                for page_url, _ in pages:
                    if len(news_list) >= self.max_items:
                        break
                    urls = mod_mrdx.get_title_list(y, m, d, page_url)
                    for url in urls:
                        if len(news_list) >= self.max_items:
                            break
                        html = mod_mrdx.fetch_url(url)
                        _, _, title, content_body, summary = mod_mrdx.parse_article(html)
                        news_list.append(self._build_news(title, url, origin, summary or content_body, f"{y}-{m}-{d}"))
                return NewsResponse(news_list=news_list)

            if self.source == 'jjckb':
                y, m, d = self._find_available_date(mod_jjckb.get_page_list)
                pages = mod_jjckb.get_page_list(y, m, d)
                news_list: List[News] = []
                for page_url, _ in pages:
                    if len(news_list) >= self.max_items:
                        break
                    urls = mod_jjckb.get_title_list(y, m, d, page_url)
                    for url in urls:
                        if len(news_list) >= self.max_items:
                            break
                        html = mod_jjckb.fetch_url(url)
                        _, _, title, content_body, summary = mod_jjckb.parse_article(html)
                        news_list.append(self._build_news(title, url, origin, summary or content_body, f"{y}-{m}-{d}"))
                return NewsResponse(news_list=news_list)

            return NewsResponse(news_list=None, status='ERROR', err_code='NOT_IMPLEMENTED', err_info='Unknown source handler')
        except Exception as e:
            return NewsResponse(news_list=None, status='ERROR', err_code='EXCEPTION', err_info=str(e))








