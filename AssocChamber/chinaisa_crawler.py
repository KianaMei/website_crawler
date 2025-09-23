"""
ChinaISA (China Iron and Steel Association) crawler.

Fetches list and detail via the site's AJAX endpoints under
  https://www.chinaisa.org.cn/gxportal/xfpt/portal/

This module focuses on robustly emulating the front-end request pattern
and returning project-standard NewsResponse objects.
"""

# -*- coding: utf-8 -*-
import sys
sys.path.append('.')
from typing import List, Tuple, Optional, Dict, Any
import re
import json
from urllib.parse import urljoin, urlparse, quote

import requests
from bs4 import BeautifulSoup

from utils.tool import get_html_from_url
from model import News, NewsResponse


# Known columns (from portal index.js); mapping id -> human-readable name.
# These are safe defaults; discovery helpers can refresh dynamically if needed.
CHINAISA_COLUMNS: Dict[str, str] = {
    # 要闻 / 会员动态
    'c42511ce3f868a515b49668dd250290c80d4dc8930c7e455d0e6e14b8033eae2': '要闻',
    '268f86fdf61ac8614f09db38a2d0295253043b03e092c7ff48ab94290296125c': '会员动态',
    # 统计发布 / 行业分析
    '2e3c87064bdfc0e43d542d87fce8bcbc8fe0463d5a3da04d7e11b4c7d692194b': '统计发布',
    '1b4316d9238e09c735365896c8e4f677a3234e8363e5622ae6e79a5900a76f56': '行业分析',
    # 价格指数 / 宏观经济信息
    '17b6a9a214c94ccc28e56d4d1a2dbb5acef3e73da431ddc0a849a4dcfc487d04': '价格指数',
    '5d77b433182404193834120ceed16fe0625860fafd5fd9e71d0800c4df227060': '宏观经济信息',
    # 相关行业信息 / 国际动态
    'ae2a3c0fd4936acf75f4aab6fadd08bc6371aa65bdd50419e74b70d6f043c473': '相关行业信息',
    '1bad7c56af746a666e4a4e56e54a9508d344d7bc1498360580613590c16b6c41': '国际动态',
    # 其他（存在于 index.js，但不一定在对外 API 需要）
    '58af05dfb6b4300151760176d2aad0a04c275aaadbb1315039263f021f920dcd': '钢协动态',
    'a873c2e67b26b4a2d8313da769f6e106abc9a1ff04b7f1a50674dfa47cf91a7b': '领导讲话',
    '179cde9e2d8f7e84968dbfb9948056843a6f9e27f2aefd09bbb3ce67c501cccf': '通知公告',
}


# Baseline grouped subtabs for three main parents (discovered and fixed here for reference)
CHINAISA_SUBGROUPS: Dict[str, List[Tuple[str, str]]] = {
    # 统计发布
    '2e3c87064bdfc0e43d542d87fce8bcbc8fe0463d5a3da04d7e11b4c7d692194b': [
        ('3238889ba0fa3aabcf28f40e537d440916a361c9170a4054f9fc43517cb58c1e', '生产经营'),
        ('95ef75c752af3b6c8be479479d8b931de7418c00150720280d78c8f0da0a438c', '进出口'),
        ('619ce7b53a4291d47c19d0ee0765098ca435e252576fbe921280a63fba4bc712', '环保统计'),
    ],
    # 行业分析
    '1b4316d9238e09c735365896c8e4f677a3234e8363e5622ae6e79a5900a76f56': [
        ('a44207e193a5caa5e64102604b6933896a0025eb85c57c583b39626f33d4dafd', '市场价格分析'),
        ('05d0e136828584d2cd6e45bdc3270372764781b98546cce122d9974489b1e2f2', '板带材'),
        ('197422a82d9a09b9cc86188444574816e93186f2fde87474f8b028fc61472d35', '社会库存'),
        ('6dfc16a60056ec0f2234d45f5fd7068ec4d75f66021df5ff544102801674a59a', '钢铁原料'),
    ],
    # 价格指数
    '17b6a9a214c94ccc28e56d4d1a2dbb5acef3e73da431ddc0a849a4dcfc487d04': [
        ('63913b906a7a663f7f71961952b1ddfa845714b5982655b773a62b85dd3b064e', '综合价格指数'),
        ('fc816c75aed82b9bc25563edc9cf0a0488a2012da38cbef5258da614d6e51ba9', '地区价格'),
    ],
}


PORTAL_BASE = 'https://www.chinaisa.org.cn/gxportal/xfpt/portal/'
INDEX_BASE = 'https://www.chinaisa.org.cn/gxportal/xfgl/portal/'


_DATE_RE = re.compile(r"(20\d{2})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})[日]?")


def _extract_date(text: str) -> Optional[str]:
    s = (text or '').replace('年', '-').replace('月', '-').replace('日', '')
    m = re.search(r"(20\d{2})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{1,2})", s)
    if m:
        y, mo, d = m.groups()
        try:
            from datetime import datetime
            dt = datetime(int(y), int(mo), int(d))
            return dt.strftime('%Y-%m-%d')
        except Exception:
            return None
    m2 = re.search(r"(20\d{2}-\d{1,2}-\d{1,2})", s)
    if m2:
        return m2.group(1)
    return None


def _summarize(text: str, length: int = 200) -> str:
    t = re.sub(r"\s+", " ", text or '').strip()
    return (t[:length].rstrip() + '...') if len(t) > length else t


def _abs_url(base: str, href: str) -> str:
    try:
        return urljoin(base, href)
    except Exception:
        return href


class _PortalClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'X-Requested-With': 'XMLHttpRequest',
            'Origin': 'https://www.chinaisa.org.cn',
        })

    def post(self, endpoint: str, payload_obj: Dict[str, Any], referer: Optional[str] = None) -> Optional[Dict[str, Any]]:
        url = PORTAL_BASE + endpoint
        if referer:
            self.session.headers['Referer'] = referer
        # Build candidate variants to maximize compatibility with backend parsing
        candidates: List[Tuple[str, str]] = []  # (form_value, note)

        def _enc(v: str) -> str:
            return quote(v, safe="~()*!.\'")

        # Helper: build param with/without inner 'param' encoding
        def _variants(obj: Dict[str, Any]) -> List[str]:
            raws: List[Dict[str, Any]] = [obj]
            if 'param' in obj:
                try:
                    p = obj['param']
                    if isinstance(p, dict):
                        j = json.dumps(p, ensure_ascii=False)
                        raws.append({**obj, 'param': j})
                        raws.append({**obj, 'param': _enc(j)})
                    elif isinstance(p, str):
                        try:
                            # as JSON object
                            raws.append({**obj, 'param': json.loads(p)})
                        except Exception:
                            pass
                        raws.append({**obj, 'param': _enc(p)})
                except Exception:
                    pass
            # stringify + optionally encodeURI
            results: List[str] = []
            for ro in raws:
                s = json.dumps(ro, ensure_ascii=False)
                results.append(s)
                results.append(_enc(s))
            return results

        for form_value in _variants(payload_obj):
            candidates.append((form_value, 'outer-json-variant'))

        # Try requests
        last_text = None
        for form_value, _ in candidates:
            try:
                resp = self.session.post(url, data={'params': form_value}, timeout=15)
                resp.raise_for_status()
                txt = resp.text.strip()
                last_text = txt
                # Some endpoints return JSON string; parse
                obj = json.loads(txt)
                # Heuristic OK: either explicit code==0, or presence of expected fields
                if isinstance(obj, dict):
                    if obj.get('code') in (0, '0', None) or any(k in obj for k in ('articleListHtml', 'article_title', 'href', 'src')):
                        return obj
            except Exception:
                continue
        # Fallback failed
        return None


class ChinaISACrawler:
    """Crawler for ChinaISA portal.

    Parameters mirror other crawlers in this project for consistency.
    """

    def __init__(
        self,
        column_ids: Optional[List[str]] = None,
        page_no: int = 1,
        page_size: int = 20,
        max_items: Optional[int] = 100,
        include_subtabs: bool = True,
        since_days: Optional[int] = None,
        max_pages: int = 5,
        prefer_http: bool = False,
    ):
        # default to 8 main columns commonly used
        default_cols = [
            'c42511ce3f868a515b49668dd250290c80d4dc8930c7e455d0e6e14b8033eae2',
            '268f86fdf61ac8614f09db38a2d0295253043b03e092c7ff48ab94290296125c',
            '2e3c87064bdfc0e43d542d87fce8bcbc8fe0463d5a3da04d7e11b4c7d692194b',
            '1b4316d9238e09c735365896c8e4f677a3234e8363e5622ae6e79a5900a76f56',
            '17b6a9a214c94ccc28e56d4d1a2dbb5acef3e73da431ddc0a849a4dcfc487d04',
            '5d77b433182404193834120ceed16fe0625860fafd5fd9e71d0800c4df227060',
            'ae2a3c0fd4936acf75f4aab6fadd08bc6371aa65bdd50419e74b70d6f043c473',
            '1bad7c56af746a666e4a4e56e54a9508d344d7bc1498360580613590c16b6c41',
        ]
        self.column_ids = column_ids or default_cols
        self.page_no = max(1, page_no)
        self.page_size = max(1, min(page_size, 100))
        self.max_items = max_items
        self.include_subtabs = include_subtabs
        self.since_days = max(1, since_days) if since_days else None
        self.max_pages = max(1, max_pages)
        self.prefer_http = prefer_http
        self.client = _PortalClient()

    # -------- list/detail helpers --------
    def _fetch_column_data(self, column_id: str, page_no: Optional[int] = None, page_size: Optional[int] = None) -> Optional[Dict[str, Any]]:
        referer = f"{INDEX_BASE}list.html?columnId={column_id}"
        # First call may omit param (front-end initial load)
        payload = {"columnId": column_id}
        obj = self.client.post('getColumnList', payload, referer=referer)
        if obj and isinstance(obj, dict) and obj.get('articleListHtml'):
            return obj
        # With paging param
        if page_no is not None and page_size is not None:
            inner = {"pageNo": page_no, "pageSize": page_size}
            payload = {"columnId": column_id, "param": inner}
            obj = self.client.post('getColumnList', payload, referer=referer)
            if obj and isinstance(obj, dict) and obj.get('articleListHtml'):
                return obj
        return None

    def _parse_list_html(self, html_fragment: str) -> List[Tuple[str, str, str]]:
        soup = BeautifulSoup(html_fragment or '', 'html.parser')
        items: List[Tuple[str, str, str]] = []
        # Primary: ul.list > li > a + span.times
        for li in soup.select('ul.list li'):
            a = li.find('a', href=True)
            if not a:
                continue
            title = a.get_text(strip=True)
            href = a['href'].strip()
            date_text = ''
            tm = li.find('span', class_='times')
            if tm:
                date_text = tm.get_text(strip=True)
            else:
                # fallback: any bracketed date or digits
                date_text = li.get_text(" ", strip=True)
            date = _extract_date(date_text) or ''
            if title and href:
                items.append((title, href, date))
        # Fallback: parse any anchors in fragment
        if not items:
            for a in soup.select('a[href]'):
                href = a['href'].strip()
                if not href or 'javascript:' in href:
                    continue
                title = a.get_text(strip=True)
                date = _extract_date(title) or ''
                if title:
                    items.append((title, href, date))
        return items

    def _fetch_detail_summary(self, url: str) -> Tuple[str, Optional[str]]:
        # Attempt API first if URL encodes articleId/columnId
        try:
            u = urlparse(url)
            qs = {}
            if u.query:
                for kv in u.query.split('&'):
                    if '=' in kv:
                        k, v = kv.split('=', 1)
                        qs[k] = v
            aid = qs.get('articleId')
            cid = qs.get('columnId')
            if aid and cid:
                payload = {"articleId": aid, "columnId": cid, "type": ""}
                referer = f"{INDEX_BASE}content.html?articleId={aid}&columnId={cid}"
                obj = self.client.post('viewArticleById', payload, referer=referer)
                if obj and isinstance(obj, dict) and obj.get('article_content'):
                    content_html = obj['article_content']
                    # Normalize embedded legacy paths as content.js would
                    content_html = content_html.replace(
                        "http://www.chinaisa.org.cn:80/gxportal/EC/DM/ECDM0104.jsp?filePath=\\192.168.10.202file/AppFiles/gxportalUploadFiles/File/",
                        "http://www.chinaisa.org.cn/gxportalFile/",
                    )
                    soup = BeautifulSoup(content_html, 'html.parser')
                    text = soup.get_text('\n', strip=True)
                    # Title/date may be outside article_content; try extracting from nav/text fallback
                    date_fb = _extract_date(text)
                    return _summarize(text), date_fb
        except Exception:
            pass
        # Fallback: GET content.html and parse container
        html = get_html_from_url(url)
        if not html:
            return '', None
        soup = BeautifulSoup(html, 'html.parser')
        node = soup.find('div', id='article_content') or soup
        text = node.get_text('\n', strip=True)
        date_fb = _extract_date(soup.get_text('\n', strip=True))
        return _summarize(text), date_fb

    # -------- public APIs --------
    def _discover_subtabs_for_column(self, column_id: str) -> List[Tuple[str, str]]:
        """Return list of (sub_id, sub_name) for a given parent column via columnListHtml."""
        data = self._fetch_column_data(column_id, page_no=1, page_size=10)
        subtabs: List[Tuple[str, str]] = []
        if not data or 'columnListHtml' not in data:
            return subtabs
        soup = BeautifulSoup(data['columnListHtml'] or '', 'html.parser')
        for a in soup.select('a[href*="list.html?columnId="]'):
            href = a.get('href', '')
            text = a.get_text(strip=True)
            m = re.search(r'columnId=([0-9a-f]{64})', href)
            if m:
                sub_id = m.group(1)
                if sub_id != column_id:
                    subtabs.append((sub_id, text or ''))
        # de-duplicate while keeping order
        seen = set(); uniq: List[Tuple[str, str]] = []
        for sid, name in subtabs:
            if sid in seen:
                continue
            seen.add(sid); uniq.append((sid, name))
        return uniq

    def get_news(self) -> NewsResponse:
        try:
            news_list: List[News] = []
            fetched = 0
            # Optionally expand with subtabs for specific parents
            expand_targets = {
                # 统计发布, 行业分析, 价格指数
                '2e3c87064bdfc0e43d542d87fce8bcbc8fe0463d5a3da04d7e11b4c7d692194b',
                '1b4316d9238e09c735365896c8e4f677a3234e8363e5622ae6e79a5900a76f56',
                '17b6a9a214c94ccc28e56d4d1a2dbb5acef3e73da431ddc0a849a4dcfc487d04',
            }
            work_ids: List[str] = []
            for cid in self.column_ids:
                work_ids.append(cid)
                if self.include_subtabs and cid in expand_targets:
                    for sid, _ in self._discover_subtabs_for_column(cid):
                        if sid not in work_ids:
                            work_ids.append(sid)

            for cid in work_ids:
                page = self.page_no
                while page < self.page_no + self.max_pages:
                    data = self._fetch_column_data(cid, page_no=page, page_size=self.page_size)
                    if not data:
                        break
                    rows = self._parse_list_html(data.get('articleListHtml') or '')
                    if not rows:
                        break
                    for title, href, date in rows:
                        if self.max_items and fetched >= self.max_items:
                            break
                        # Build absolute article URL relative to list page base
                        absu = _abs_url(INDEX_BASE, href)
                        summary, date_fb = self._fetch_detail_summary(absu)
                        use_date = date or (date_fb or '')
                        origin_name = '中国钢铁工业协会'
                        news_list.append(News(title=title, url=absu, origin=origin_name, summary=summary, publish_date=use_date))
                        fetched += 1
                    if self.max_items and fetched >= self.max_items:
                        break
                    page += 1
                if self.max_items and fetched >= self.max_items:
                    break
            status = 'OK' if news_list else 'EMPTY'
            return NewsResponse(news_list=news_list or None, status=status,
                                err_code=None if news_list else 'NO_DATA',
                                err_info=None if news_list else 'No news parsed')
        except Exception as e:
            return NewsResponse(status='ERROR', err_code='CRAWL_UNEXPECTED_ERROR', err_info=str(e))

    # Utilities useful for diagnostics
    def discover_all_columns(self) -> List[Tuple[str, str, str]]:
        res: List[Tuple[str, str, str]] = []
        js = get_html_from_url(urljoin(INDEX_BASE, 'index.js'))
        if js:
            # Pattern: articleList("<columnId>") //注释
            for m in re.finditer(r"articleList\(\"([0-9a-f]{64})\",?\s*\"?(.*?)\"?\)\s*;\s*//([^\n\r]*)", js):
                cid = m.group(1)
                comment = (m.group(3) or '').strip()
                name = None
                # Try to extract name inside comment or fallback map
                if comment:
                    # Remove trailing注释格式中的中文冒号
                    name = comment.replace('：', ':').split('//')[-1].split(':')[-1].strip()
                name = name or CHINAISA_COLUMNS.get(cid, '')
                if cid:
                    res.append((cid, name or '', 'index.js'))
        # Add known mapping if missing
        for cid, nm in CHINAISA_COLUMNS.items():
            if not any(x[0] == cid for x in res):
                res.append((cid, nm, 'static'))
        return res

    def get_sections(self, include_subtabs: bool = True) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for cid, nm in CHINAISA_COLUMNS.items():
            entry: Dict[str, Any] = {'name': nm, 'subtabs': []}
            baseline = CHINAISA_SUBGROUPS.get(cid, [])
            if baseline:
                entry['baseline_subtabs'] = [{'id': sid, 'name': sname} for sid, sname in baseline]
            if include_subtabs:
                live = self._discover_subtabs_for_column(cid)
                if live:
                    entry['subtabs'] = [{'id': sid, 'name': sname} for sid, sname in live]
                    if baseline:
                        base_ids = {sid for sid, _ in baseline}
                        live_ids = {sid for sid, _ in live}
                        entry['added'] = [sid for sid in live_ids - base_ids]
                        entry['missing'] = [sid for sid in base_ids - live_ids]
            out[cid] = entry
        return out

    def probe_once(self, column_id: str, page_no: int = 1, page_size: int = 10) -> Dict[str, Any]:
        trace: Dict[str, Any] = {
            'column_id': column_id,
            'page_no': page_no,
            'page_size': page_size,
            'steps': [],
        }
        referer = f"{INDEX_BASE}list.html?columnId={column_id}"
        # Try without param
        obj1 = self.client.post('getColumnList', {"columnId": column_id}, referer=referer)
        trace['steps'].append({'endpoint': 'getColumnList', 'params': {'columnId': column_id}, 'ok': bool(obj1), 'keys': list(obj1.keys()) if isinstance(obj1, dict) else None})
        # Try with param
        obj2 = self.client.post('getColumnList', {"columnId": column_id, "param": {"pageNo": page_no, "pageSize": page_size}}, referer=referer)
        trace['steps'].append({'endpoint': 'getColumnList', 'params': {'columnId': column_id, 'param': {'pageNo': page_no, 'pageSize': page_size}}, 'ok': bool(obj2), 'keys': list(obj2.keys()) if isinstance(obj2, dict) else None})
        # Basic parse preview
        if obj2 and isinstance(obj2, dict) and obj2.get('articleListHtml'):
            rows = self._parse_list_html(obj2['articleListHtml'])
            trace['preview'] = rows[:3]
        return trace


if __name__ == '__main__':
    cr = ChinaISACrawler(max_items=20, max_pages=2, page_size=10)
    r = cr.get_news()
    print(r.model_dump())
