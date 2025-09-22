"""
ChinaISA（中国钢铁工业协会）抓取。

通过站点 AJAX 接口：
  https://www.chinaisa.org.cn/gxportal/xfpt/portal/

模拟前端请求并返回项目统一的 NewsResponse。
"""

# -*- coding: utf-8 -*-
from typing import List, Tuple, Optional, Dict, Any
import re
import json
from urllib.parse import urljoin, urlparse, quote

import requests
from bs4 import BeautifulSoup

from utils.tool import get_html_from_url
from model import News, NewsResponse


# 已知栏目（来自 portal index.js）；id -> 可读名称
CHINAISA_COLUMNS: Dict[str, str] = {
    # 要闻 / 会员动态
    'c42511ce3f868a515b49668dd250290c80d4dc8930c7e455d0e6e14b8033eae2': '要闻',
    '268f86fdf61ac8614f09db38a2d0295253043b03e092c7ff48ab94290296125c': '会员动态',
    # 统计分析 / 行业信息
    '2e3c87064bdfc0e43d542d87fce8bcbc8fe0463d5a3da04d7e11b4c7d692194b': '统计分析',
    '1b4316d9238e09c735365896c8e4f677a3234e8363e5622ae6e79a5900a76f56': '行业信息',
    # 价格指数 / 原料信息
    '17b6a9a214c94ccc28e56d4d1a2dbb5acef3e73da431ddc0a849a4dcfc487d04': '价格指数',
    '5d77b433182404193834120ceed16fe0625860fafd5fd9e71d0800c4df227060': '原料信息',
    # 优特钢信息 / 国际动态
    'ae2a3c0fd4936acf75f4aab6fadd08bc6371aa65bdd50419e74b70d6f043c473': '优特钢信息',
    '1bad7c56af746a666e4a4e56e54a9508d344d7bc1498360580613590c16b6c41': '国际动态',
    # 协会动态 / 领导讲话 / 通知公告（存在于 index.js 的另一 API 里）
    '58af05dfb6b4300151760176d2aad0a04c275aaadbb1315039263f021f920dcd': '协会动态',
    'a873c2e67b26b4a2d8313da769f6e106abc9a1ff04b7f1a50674dfa47cf91a7b': '领导讲话',
    '179cde9e2d8f7e84968dbfb9948056843a6f9e27f2aefd09bbb3ce67c501cccf': '通知公告',
}


# 三个主栏目（统计分析/行业信息/价格指数）的基线子栏目
CHINAISA_SUBGROUPS: Dict[str, List[Tuple[str, str]]] = {
    # 统计分析
    '2e3c87064bdfc0e43d542d87fce8bcbc8fe0463d5a3da04d7e11b4c7d692194b': [
        ('3238889ba0fa3aabcf28f40e537d440916a361c9170a4054f9fc43517cb58c1e', '生产经营'),
        ('95ef75c752af3b6c8be479479d8b931de7418c00150720280d78c8f0da0a438c', '进出口'),
        ('619ce7b53a4291d47c19d0ee0765098ca435e252576fbe921280a63fba4bc712', '运行统计'),
    ],
    # 行业信息
    '1b4316d9238e09c735365896c8e4f677a3234e8363e5622ae6e79a5900a76f56': [
        ('a44207e193a5caa5e64102604b6933896a0025eb85c57c583b39626f33d4dafd', '市场价格信息'),
        ('05d0e136828584d2cd6e45bdc3270372764781b98546cce122d9974489b1e2f2', '期货'),
        ('197422a82d9a09b9cc86188444574816e93186f2fde87474f8b028fc61472d35', '钢材'),
        ('6dfc16a60056ec0f2234d45f5fd7068ec4d75f66021df5ff544102801674a59a', '铁矿石原料'),
    ],
    # 价格指数
    '17b6a9a214c94ccc28e56d4d1a2dbb5acef3e73da431ddc0a849a4dcfc487d04': [
        ('63913b906a7a663f7f71961952b1ddfa845714b5982655b773a62b85dd3b064e', '综合价格指数'),
        ('fc816c75aed82b9bc25563edc9cf0a0488a2012da38cbef5258da614d6e51ba9', '钢材价格'),
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
        self.page_no = page_no
        self.page_size = page_size
        self.max_items = max_items
        self.include_subtabs = include_subtabs
        self.since_days = since_days
        self.max_pages = max_pages
        self.prefer_http = prefer_http
