"""
每个插件文件都需要导出名为 `handler` 的函数，作为工具入口。

参数:
- args: 入口函数的参数对象
- args.input: 输入参数（例如 args.input.xxx）
- args.logger: 日志记录器，由运行时注入

返回:
返回的数据必须与声明的输出参数结构一致。
"""

from runtime import Args
from pydantic import BaseModel, Field
from typing import Optional, List, Tuple, Dict, Any

import logging
import json
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin


class News(BaseModel):
    title: str
    url: str
    origin: str
    summary: str
    publish_date: str


class Input(BaseModel):
    column_ids: Optional[List[str]] = Field(default=None, description="要抓取的栏目 ID 列表")
    page_no: int = Field(default=1, ge=1, description="起始页码（>=1）")
    page_size: int = Field(default=20, ge=1, description="每页条数")
    max_items: Optional[int] = Field(default=100, ge=1, description="最大抓取条数（仅非当天计入全局上限）")
    include_subtabs: bool = Field(default=True, description="是否包含子栏目")
    max_pages: int = Field(default=5, ge=1, description="每个栏目最大翻页数")


class Output(BaseModel):
    news_list: Optional[List[News]] = Field(default=None, description="新闻列表")
    status: str = Field(default="OK", description="响应状态标记")
    err_code: Optional[str] = Field(default=None, description="错误码（可选）")
    err_info: Optional[str] = Field(default=None, description="错误信息（可选）")


Metadata = {
    "name": "get_assoc_chinaisa",
    "description": "通过门户 API 抓取中国钢铁工业协会新闻并返回结果。",
    "input": Input.model_json_schema(),
    "output": Output.model_json_schema(),
}


def handler(args: Args[Input]) -> Output:
    logger = (getattr(args, "logger", None) or logging.getLogger(__name__))
    inp = getattr(args, 'input', None)
    try:
        # 规范化输入
        if isinstance(inp, dict):
            column_ids = inp.get('column_ids') or DEFAULT_COLUMN_IDS
            page_no = int(inp.get('page_no') or 1)
            page_size = int(inp.get('page_size') or 20)
            max_items = int(inp.get('max_items') or 100)
            include_subtabs = bool(inp.get('include_subtabs') if inp.get('include_subtabs') is not None else True)
            max_pages = int(inp.get('max_pages') or 5)
        elif inp is None:
            column_ids = DEFAULT_COLUMN_IDS
            page_no = 1
            page_size = 20
            max_items = 100
            include_subtabs = True
            max_pages = 5
        else:
            column_ids = getattr(inp, 'column_ids', None) or DEFAULT_COLUMN_IDS
            page_no = int(getattr(inp, 'page_no', 1) or 1)
            page_size = int(getattr(inp, 'page_size', 20) or 20)
            mi = getattr(inp, 'max_items', 100)
            max_items = int(mi) if mi is not None else 100
            inc = getattr(inp, 'include_subtabs', True)
            include_subtabs = bool(True if inc is None else inc)
            max_pages = int(getattr(inp, 'max_pages', 5) or 5)

        client = _PortalClient()
        items: List[News] = []

        work_ids: List[str] = list(column_ids)
        if include_subtabs:
            for cid in list(column_ids):
                if cid in EXPAND_PARENTS:
                    work_ids.extend(_discover_subtabs_for_column(client, cid))
        # 去重（按栏目 ID 保序）
        seen_ids = set(); uniq_ids: List[str] = []
        for cid in work_ids:
            if cid not in seen_ids:
                seen_ids.add(cid); uniq_ids.append(cid)

        # 时间与诊断
        from datetime import datetime, timedelta, date as _date
        today = datetime.today().date()
        today_str = today.strftime('%Y-%m-%d')
        any_filtered_due_to_time = False
        diag_summaries: List[str] = []
        non_today_total = 0  # only count non-today against global max_items

        for cid in uniq_ids:
            start_idx = len(items)
            page = page_no
            while page < page_no + max_pages:
                data = _fetch_column_data(client, cid, page_no=page, page_size=page_size)
                if not data:
                    break
                rows = _parse_list_html(data.get('articleListHtml') or '')
                if not rows:
                    break
                for title, href, date in rows:
                    is_today = (date == today_str)
                    if is_today or (len(items) < max_items):
                        absu = urljoin(INDEX_BASE, href)
                        summary = _fetch_detail_summary_via_api(absu, client) or _fetch_detail_summary(absu)
                        items.append(News(title=title, url=absu, origin=ORIGIN_NAME, summary=summary, publish_date=date or ''))
                        if not is_today:
                            non_today_total += 1
                if max_items and non_today_total >= max_items:
                    break
                page += 1

            # 栏目内筛选：若有当天则仅取当天；否则近三天内按新到旧最多 3 条
            try:
                earliest = today - timedelta(days=2)
                def _to_date(s: str):
                    try:
                        y, m, d = s.split('-')
                        return _date(int(y), int(m), int(d))
                    except Exception:
                        return None
                bucket = items[start_idx:]
                todays = [n for n in bucket if _to_date(n.publish_date or '') == today]
                if todays:
                    selected = todays
                else:
                    windows = [n for n in bucket if (lambda d: d and (earliest <= d <= today))(_to_date(n.publish_date or ''))]
                    windows.sort(key=lambda n: (_to_date(n.publish_date or '') or earliest), reverse=True)
                    selected = windows[:3]
                if len(bucket) > 0 and len(selected) == 0:
                    any_filtered_due_to_time = True
                items[start_idx:] = selected
                diag_summaries.append(f"{cid}:{len(bucket)}->{len(selected)}")
            except Exception:
                pass

            if max_items and non_today_total >= max_items:
                break

        # 按发布日期倒序排序
        try:
            items = sorted(
                items,
                key=lambda n: (datetime.strptime(n.publish_date or '', '%Y-%m-%d') if (n.publish_date or '').strip() else datetime.min),
                reverse=True,
            )
        except Exception:
            pass

        # 去重（按 URL 保序）
        uniq_items: List[News] = []
        seen_urls: set[str] = set()
        for n in items:
            if n.url not in seen_urls:
                uniq_items.append(n)
                seen_urls.add(n.url)

        status = 'OK' if uniq_items else 'EMPTY'
        if uniq_items:
            return Output(news_list=uniq_items, status=status, err_code=None, err_info=None)
        else:
            if any_filtered_due_to_time:
                return Output(news_list=None, status='EMPTY', err_code='NO_RECENT', err_info='今天无更新，且最近三天均无内容')
            detail = '; '.join(diag_summaries) if diag_summaries else '未配置栏目或未解析到列表项'
            return Output(news_list=None, status='EMPTY', err_code='NO_DATA', err_info=f'无数据（解析/筛选摘要: {detail})')
    except Exception as e:
        logger.exception("assoc_chinaisa handler failed")
        return Output(news_list=None, status="ERROR", err_code="PLUGIN_ERROR", err_info=str(e))


ORIGIN_NAME = '中国钢铁工业协会'
PORTAL_BASE = 'https://www.chinaisa.org.cn/gxportal/xfpt/portal/'
INDEX_BASE = 'https://www.chinaisa.org.cn/gxportal/xfgl/portal/'

# 常用父栏目（需要展开子栏目）
EXPAND_PARENTS = {
    '2e3c87064bdfc0e43d542d87fce8bcbc8fe0463d5a3da04d7e11b4c7d692194b',
    '1b4316d9238e09c735365896c8e4f677a3234e8363e5622ae6e79a5900a76f56',
    '17b6a9a214c94ccc28e56d4d1a2dbb5acef3e73da431ddc0a849a4dcfc487d04',
}

# 默认栏目（当调用方未提供时）
DEFAULT_COLUMN_IDS = [
    'c42511ce3f868a515b49668dd250290c80d4dc8930c7e455d0e6e14b8033eae2',
    '268f86fdf61ac8614f09db38a2d0295253043b03e092c7ff48ab94290296125c',
    '2e3c87064bdfc0e43d542d87fce8bcbc8fe0463d5a3da04d7e11b4c7d692194b',
]


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
        self.session.trust_env = False
        self.session.verify = False

    def post(self, endpoint: str, payload_obj: Dict[str, Any], referer: Optional[str] = None) -> Optional[Dict[str, Any]]:
        url = PORTAL_BASE + endpoint
        if referer:
            self.session.headers['Referer'] = referer
        # 为兼容后端，尝试多种表单编码方式提交 JSON
        def _enc(v: str) -> str:
            try:
                from urllib.parse import quote
                return quote(v, safe="~()*!.\'")
            except Exception:
                return v

        raws: List[Dict[str, Any]] = [payload_obj]
        if 'param' in payload_obj:
            p = payload_obj['param']
            if isinstance(p, dict):
                j = json.dumps(p, ensure_ascii=False)
                raws.append({**payload_obj, 'param': j})
                raws.append({**payload_obj, 'param': _enc(j)})
            elif isinstance(p, str):
                raws.append({**payload_obj, 'param': _enc(p)})

        candidates: List[str] = []
        for ro in raws:
            s = json.dumps(ro, ensure_ascii=False)
            candidates.append(s)
            candidates.append(_enc(s))

        for form_value in candidates:
            try:
                resp = self.session.post(url, data={'params': form_value}, timeout=15)
                resp.raise_for_status()
                txt = (resp.text or '').strip()
                obj = json.loads(txt)
                if isinstance(obj, dict) and (obj.get('code') in (0, '0', None) or any(k in obj for k in ('articleListHtml', 'article_title', 'href', 'src'))):
                    return obj
            except Exception:
                continue
        return None


def _fetch_column_data(client: _PortalClient, column_id: str, page_no: int, page_size: int) -> Optional[Dict[str, Any]]:
    referer = f"{INDEX_BASE}list.html?columnId={column_id}"
    payload = {"columnId": column_id}
    obj = client.post('getColumnList', payload, referer=referer)
    if obj and isinstance(obj, dict) and obj.get('articleListHtml'):
        return obj
    payload = {"columnId": column_id, "param": {"pageNo": page_no, "pageSize": page_size}}
    obj = client.post('getColumnList', payload, referer=referer)
    if obj and isinstance(obj, dict) and obj.get('articleListHtml'):
        return obj
    return None


def _parse_list_html(html_fragment: str) -> List[Tuple[str, str, str]]:
    soup = BeautifulSoup(html_fragment or '', 'html5lib')
    items: List[Tuple[str, str, str]] = []
    for li in soup.select('ul.list li'):
        a = li.find('a', href=True)
        if not a:
            continue
        title = a.get_text(strip=True)
        href = a['href'].strip()
        tm = li.find('span', class_='times')
        date_text = tm.get_text(strip=True) if tm else li.get_text(" ", strip=True)
        date = _extract_date(date_text) or ''
        if title and href:
            items.append((title, href, date))
    if items:
        return items
    for a in soup.find_all('a', href=True):
        title = a.get_text(strip=True)
        href = a['href'].strip()
        if title and href:
            items.append((title, href, ''))
    return items


def _discover_subtabs_for_column(client: _PortalClient, column_id: str) -> List[str]:
    """从栏目列表页面发现子标签的 columnId。

    实现思路（与 AssocChamber/chinaisa_crawler.py 保持一致）：
    - 调用 getColumnList 获取 'columnListHtml'
    - 解析链接中形如 'list.html?columnId=...'
    - 抽取 64 位十六进制 ID，并去重（保序）
    """
    try:
        data = _fetch_column_data(client, column_id, page_no=1, page_size=10)
    except Exception:
        data = None
    out: List[str] = []
    if not data or 'columnListHtml' not in data:
        return out
    try:
        soup = BeautifulSoup(data.get('columnListHtml') or '', 'html5lib')
        for a in soup.select('a[href*="list.html?columnId="]'):
            href = a.get('href', '')
            m = re.search(r'columnId=([0-9a-f]{64})', href)
            if m:
                sid = m.group(1)
                if sid and sid != column_id:
                    out.append(sid)
    except Exception:
        pass
    # 去重并保序
    seen: set[str] = set()
    uniq: List[str] = []
    for sid in out:
        if sid not in seen:
            seen.add(sid)
            uniq.append(sid)
    return uniq


def _extract_date(text: str) -> Optional[str]:
    m = re.search(r"(20\d{2})\s*[-/.��]\s*(\d{1,2})\s*[-/.��]\s*(\d{1,2})[��]?", text or '')
    if m:
        y, mo, d = m.groups()
        try:
            return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
        except Exception:
            return None
    m2 = re.search(r"(20\d{2}-\d{1,2}-\d{1,2})", text or '')
    if m2:
        return m2.group(1)
    return None


def _fetch_detail_summary(url: str) -> str:
    html = _robust_fetch_html(url)
    soup = BeautifulSoup(html or '', 'html5lib')
    # 更贴合协会站点的正文容器优先级
    # 更贴合协会站点的正文容器优先级
    candidates = [
        '.detail-main', '.article_detail', '.article-detail',
        '.article_con', '.TRS_Editor', '.content', '.article-content', '.main-content',
        '#zoom', 'article'
    ]
    node = None
    for sel in candidates:
        node = soup.select_one(sel)
        if node:
            break
    node = node or soup
    for t in node.find_all(['script', 'style', 'noscript']):
        t.decompose()
    text = node.get_text('\n', strip=True)
    t = re.sub(r"\s+", " ", text).strip()
    return t


def _fetch_detail_summary_via_api(url: str, client: Optional['_PortalClient'] = None) -> Optional[str]:
    """通过门户 API `viewArticleById` 获取详情内容。

    成功时返回提要文本；失败时返回 None 以便回退到页面抓取。
    """
    try:
        from urllib.parse import urlparse, parse_qs
        pu = urlparse(url)
        if not (pu.netloc.endswith('chinaisa.org.cn') and pu.path.endswith('/content.html')):
            return None
        qs = parse_qs(pu.query)
        article_id = (qs.get('articleId') or [''])[0]
        column_id = (qs.get('columnId') or [''])[0]
        if not article_id:
            return None
        cli = client or _PortalClient()
        payload = {"articleId": article_id, "columnId": column_id, "type": ''}
        obj = cli.post('viewArticleById', payload_obj=payload, referer=url)
        if not (isinstance(obj, dict) and (obj.get('article_content') or obj.get('article_title'))):
            return None
        html = obj.get('article_content') or ''
        soup = BeautifulSoup(html, 'html5lib')
        node = soup.select_one('.article_main') or soup
        for t in node.find_all(['script', 'style', 'noscript']):
            t.decompose()
        text = node.get_text('\n', strip=True)
        t = re.sub(r"\s+", " ", text).strip()
        return t
    except Exception:
        return None


def _robust_fetch_html(url: str) -> str:
    DEFAULT_HEADERS = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
        'Accept-Language': 'zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }
    retries = 3
    delay = 1.0
    sess = requests.Session()
    sess.headers.update(DEFAULT_HEADERS)
    sess.trust_env = False
    for attempt in range(retries):
        try:
            resp = sess.get(url, timeout=20, verify=False, proxies={'http': None, 'https': None})
            resp.raise_for_status()
            ct = resp.headers.get('content-type', '') or ''
            data = resp.content

            def _norm(cs: str) -> str:
                cs = (cs or '').strip().strip('"\'').lower()
                return 'gb18030' if cs in ('gb2312','gb-2312','gbk') else ('utf-8' if cs in ('utf8','utf-8') else (cs or 'utf-8'))

            def _enc_from_meta(b: bytes) -> Optional[str]:
                m = re.search(br'charset\s*=\s*["\']?([a-zA-Z0-9_\-]+)', b[:4096], re.IGNORECASE)
                if m:
                    try:
                        return _norm(m.group(1).decode('ascii', errors='ignore'))
                    except Exception:
                        return None
                return None

            def _enc_from_header() -> Optional[str]:
                m = re.search(r'charset=([^;\s]+)', ct, re.IGNORECASE)
                if m:
                    return _norm(m.group(1))
                return _norm(resp.encoding) if resp.encoding else None

            cands: List[str] = []
            for c in (_enc_from_meta(data), resp.apparent_encoding and _norm(resp.apparent_encoding), _enc_from_header(), 'utf-8', 'gb18030'):
                if c and c not in cands:
                    cands.append(c)  # type: ignore[arg-type]

            best_txt = None
            best_bad = 10**9
            for ec in cands:
                try:
                    txt = data.decode(ec, errors='replace')
                    bad = txt.count('\ufffd')
                    if bad < best_bad:
                        best_txt = txt
                        best_bad = bad
                        if bad == 0:
                            break
                except Exception:
                    continue
            return best_txt or data.decode('utf-8', errors='ignore')
        except requests.RequestException:
            if attempt < retries - 1:
                import time as _t
                _t.sleep(delay * (1 + 0.5))
                continue
            raise


