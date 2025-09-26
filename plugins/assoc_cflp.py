"""
每个插件文件都需要导出名为 `handler` 的函数，作为工具入口。

参数:
- args: 入口函数的参数对象
- args.input: 输入参数（例如 args.input.xxx）
- args.logger: 日志记录器，由运行时注入

返回: Output
"""

from runtime import Args
from pydantic import BaseModel, Field
from typing import Optional, List, Tuple, Dict

import logging
import re
import time
import random
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


class News(BaseModel):
    title: str
    url: str
    origin: str
    summary: str
    publish_date: str


class Input(BaseModel):
    channels: Optional[List[str]] = Field(default=None, description="中物联频道：zcfg|zixun（dzsp 视为 zixun）；None=默认 ['zcfg','zixun']")
    max_pages: int = Field(default=1, ge=1, description="列表最大翻页数")
    max_items: Optional[int] = Field(default=8, description="每频道最大抓取条数")
    since_days: int = Field(default=7, ge=1, description="近 N 天时间窗口")
    strict_nowadays: bool = Field(default=False, description="严格限制在近 N 天窗口；不回补更早内容")


class Output(BaseModel):
    news_list: Optional[List[News]] = Field(default=None)
    status: str = Field(default="OK")
    err_code: Optional[str] = Field(default=None)
    err_info: Optional[str] = Field(default=None)


Metadata = {
    "name": "assoc_cflp",
    "description": "中物联（chinawuliu.com.cn）新闻/政策抓取器",
    "input": Input.model_json_schema(),
    "output": Output.model_json_schema(),
}


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


def handler(args: Args[Input]) -> Output:
    logger = (getattr(args, "logger", None) or logging.getLogger(__name__))
    inp = getattr(args, 'input', None)
    if isinstance(inp, dict):
        chs = inp.get('channels')
        mp = inp.get('max_pages')
        mi = inp.get('max_items')
        sd = inp.get('since_days')
        sn = inp.get('strict_nowadays')
    else:
        chs = getattr(inp, 'channels', None)
        mp = getattr(inp, 'max_pages', None)
        mi = getattr(inp, 'max_items', None)
        sd = getattr(inp, 'since_days', None)
        sn = getattr(inp, 'strict_nowadays', None)
    try:
        mapped: List[str] = []
        for ch in (chs or ['zcfg', 'zixun']):
            mapped.append('zixun' if ch == 'dzsp' else ch)
        # 去重并保序
        seen = set()
        channels = [c for c in mapped if not (c in seen or seen.add(c))]
        try:
            max_pages = int(mp) if mp is not None else 1
        except Exception:
            max_pages = 1
        try:
            max_items = int(mi) if mi is not None else 8
        except Exception:
            max_items = 8
        try:
            since_days = int(sd) if sd is not None else 7
        except Exception:
            since_days = 7

        # strict_nowadays 解析
        def _to_bool(v):
            if isinstance(v, bool):
                return v
            if isinstance(v, str):
                return v.strip().lower() in ('1','true','yes','y','on')
            if isinstance(v, (int, float)):
                return bool(v)
            return False
        strict_nowadays = _to_bool(sn)

        all_items: List[Dict[str, str]] = []
        any_filtered_due_to_time = False
        diag_summaries: List[str] = []
        for ch in channels:
            if ch not in CFLP_CHANNELS:
                continue
            conf = CFLP_CHANNELS[ch]
            base = conf['base']
            # 列表分页
            list_urls = [conf['first_page']]
            if conf.get('page_pattern'):
                for i in range(2, max_pages + 1):
                    list_urls.append(conf['page_pattern'].format(i))
            acc: List[Tuple[str, str, str]] = []
            # 今日字符串，用于采集阶段判断“今天”不占配额
            try:
                from datetime import datetime as _dt
                today_str = _dt.today().strftime('%Y-%m-%d')
            except Exception:
                today_str = ''
            for u in list_urls:
                html = _fetch_html(u)
                if not html:
                    break
                if ch == 'zcfg':
                    acc.extend(_parse_list_zcfg(html, base))
                else:
                    acc.extend(_parse_list_zixun_like(html, base))
                if max_items:
                    try:
                        non_today = sum(1 for _, _, d in acc if d != today_str)
                        if non_today >= max_items:
                            break
                    except Exception:
                        if len(acc) >= max_items:
                            break
            for title, url, date in acc:
                all_items.append({'title': title, 'url': url, 'date': date, 'origin': conf['origin'], 'channel': ch})

        # 按 URL 去重
        unique_items = []
        seen_urls = set()
        for item in all_items:
            if item['url'] not in seen_urls:
                unique_items.append(item)
                seen_urls.add(item['url'])
        all_items = unique_items

        # Enrich details
        enriched: List[Dict[str, str]] = []
        for it in all_items:
            summary, date_fb = _parse_detail(it['url'])
            use_date = it['date'] or (date_fb or '')
            enriched.append({**it, 'summary': summary, 'date': use_date})

                # Filter per-channel by absolute since_days; backfill older items to reach per-channel max
        from datetime import datetime, timedelta
        today = datetime.today().date()
        threshold = today - timedelta(days=since_days)

        def _parse_d(it):
            if it.get('date'):
                try:
                    return datetime.strptime(it['date'], '%Y-%m-%d').date()
                except Exception:
                    return None
            return None

        # Group by channel
        zixun_all = [it for it in enriched if it['channel'] == 'zixun']
        zcfg_all = [it for it in enriched if it['channel'] == 'zcfg']

        # Sort each group by time desc
        def _time_desc_key(it):
            d = _parse_d(it)
            return (d is None, datetime.min if d is None else -datetime.combine(d, datetime.min.time()).timestamp())

        zixun_all.sort(key=lambda it: (_parse_d(it) or datetime.min.date()), reverse=True)
        zcfg_all.sort(key=lambda it: (_parse_d(it) or datetime.min.date()), reverse=True)

        def _filter_and_fill(lst):
            recent = [it for it in lst if (_parse_d(it) or datetime.min.date()) >= threshold]
            older = [it for it in lst if it not in recent]
            if max_items:
                if len(recent) < max_items:
                    need = max_items - len(recent)
                    recent.extend(older[:need])
                return recent[:max_items]
            return recent

        zixun = _filter_and_fill(zixun_all)
        zcfg = _filter_and_fill(zcfg_all)

        if strict_nowadays:
            def _only_recent(lst):
                rec = []
                for it in lst:
                    d = _parse_d(it)
                    if d is not None and d >= threshold:
                        rec.append(it)
                if max_items:
                    return rec[:max_items]
                return rec
            zixun = _only_recent(zixun_all)
            zcfg = _only_recent(zcfg_all)
# Sort zixun by demotion keyword rank then time; zcfg first
        def rank(it):
            u = (it['url'] or '').lower()
            t = it['title'] or ''
            demote_keywords = [
                'qiyexinxi','qiye','gongsi','企业信息','企业','公司','品牌',
                'zidonghua','automation','自动化','工业自动化','机器人','工业机器人',
                'wuliu','zhuangbei','shebei','物流装备','装备','设备','泵', 'agv','叉车','移动',
                '/zixun/dzsp/','dzsp'
            ]
            s = u + ' ' + t
            return 1 if any(kw in s for kw in demote_keywords) else 0

        def sort_key(it):
            try:
                from datetime import datetime
                ts = datetime.strptime(it['date'], '%Y-%m-%d')
            except Exception:
                from datetime import datetime
                ts = datetime.min
            return (rank(it), -ts.timestamp())

        zixun.sort(key=sort_key)
        # Enforce per-channel max slice
        if max_items:
            zcfg = zcfg[:max_items]
            zixun = zixun[:max_items]
        # 按新规则重选：当天优先，否则近三天最多3条（覆盖上面的默认选择）
        try:
            def _select_group(lst):
                arr = list(lst)
                earliest = today - timedelta(days=2)
                todays = [it for it in arr if _parse_d(it) == today]
                if todays:
                    sel = todays
                else:
                    win = [it for it in arr if (_parse_d(it) or datetime.min.date()) >= earliest]
                    win.sort(key=lambda it: (_parse_d(it) or datetime.min.date()), reverse=True)
                    sel = win[:3]
                sel.sort(key=lambda it: (_parse_d(it) or datetime.min.date()), reverse=True)
                return sel
            zixun_sel = _select_group(zixun_all)
            zcfg_sel = _select_group(zcfg_all)
            if (len(zixun_all) > 0 and len(zixun_sel) == 0) or (len(zcfg_all) > 0 and len(zcfg_sel) == 0):
                any_filtered_due_to_time = True
            diag_summaries.append(f"zcfg:{len(zcfg_all)}->{len(zcfg_sel)}")
            diag_summaries.append(f"zixun:{len(zixun_all)}->{len(zixun_sel)}")
            zixun = zixun_sel
            zcfg = zcfg_sel
        except Exception:
            pass
        sorted_items = zcfg + zixun
        # 全部合并后按日期降序统一排序
        try:
            sorted_items = sorted(
                sorted_items,
                key=lambda it: (_parse_d(it) or datetime.min.date()),
                reverse=True,
            )
        except Exception:
            pass

        news_list: List[News] = []
        for it in sorted_items:
            news_list.append(News(title=it['title'], url=it['url'], origin=it['origin'], summary=it['summary'], publish_date=it['date']))
        status = 'OK' if news_list else 'EMPTY'
        if news_list:
            return Output(news_list=news_list, status=status, err_code=None, err_info=None)
        else:
            if any_filtered_due_to_time:
                return Output(news_list=None, status='EMPTY', err_code='NO_RECENT', err_info='今天无更新，且最近三天均无内容')
            detail = '; '.join(diag_summaries) if diag_summaries else 'no channels or no items parsed'
            return Output(news_list=None, status='EMPTY', err_code='NO_DATA', err_info=f'No data (parsed/selected summary: {detail})')
    except Exception as e:
        logger.exception('assoc_cflp failed')
        return Output(status='ERROR', err_code='PLUGIN_ERROR', err_info=str(e))


def _fetch_html(url: str) -> str:
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
            resp = sess.get(url, timeout=15, verify=False, proxies={'http': None, 'https': None})
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
            for c in (_enc_from_meta(data), resp.apparent_encoding and _norm(resp.apparent_encoding), _enc_from_header(), 'utf-8','gb18030'):
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
                time.sleep(delay * (1 + random.random() * 0.5))
                continue
            raise


DATE_RE = re.compile(r"(20\d{2})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})[日]?")


def _extract_date(text: str) -> Optional[str]:
    s = text or ''
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
    m2 = re.search(r"(20\d{2}-\d{1,2}-\d{1,2})", s)
    if m2:
        return m2.group(1)
    return None


def _find_content_node(soup: BeautifulSoup):
    # Prefer site-specific content containers if present
    for tag, attrs in [
        ('div', {'class': 'newText'}),
        ('div', {'class': 'rightContent'}),
        ('div', {'class': 'readcontent'}),
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


def _parse_list_zcfg(html: str, base_url: str) -> List[Tuple[str, str, str]]:
    soup = BeautifulSoup(html, 'html5lib')
    items: List[Tuple[str, str, str]] = []
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


def _parse_list_zixun_like(html: str, base_url: str) -> List[Tuple[str, str, str]]:
    soup = BeautifulSoup(html, 'html5lib')
    items: List[Tuple[str, str, str]] = []
    for li in soup.select('div.ul-list ul.new-ul > li'):
        title_a = li.select_one('p.new-title a[href]')
        if not title_a:
            continue
        title = title_a.get_text(strip=True)
        href = title_a['href'].strip()
        url = urljoin(base_url, href)
        date_text = ''
        tm_spans = li.select('p.new-time span')
        if tm_spans:
            date_text = tm_spans[-1].get_text(strip=True)
        else:
            date_text = li.get_text(" ", strip=True)
        date = _extract_date(date_text) or ''
        if title and url:
            items.append((title, url, date))
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


def _parse_detail(url: str) -> Tuple[str, Optional[str]]:
    html = _fetch_html(url)
    if not html:
        return '', None
    soup = BeautifulSoup(html, 'html5lib')
    node = _find_content_node(soup)
    for tag in node.find_all(['script', 'style', 'noscript']):
        tag.decompose()
    # Remove common non-article UI blocks if present within node
    for sel in ['header','footer','nav','aside','.share','.dianzan','.read','.leftNav','.headerL','.headerR','.crumbs','.precodebox']:
        for t in node.select(sel):
            t.decompose()
    text = node.get_text('\n', strip=True)
    # Fallback to meta description if text looks wrong or contains inline JS leftovers
    if (not text) or ('frontAppContext' in text):
        desc = soup.find('meta', attrs={'name':'description'})
        if desc and desc.get('content'):
            text = desc.get('content') or ''
    # 保持全文（仅标准化空白符）
    summary = re.sub(r"\s+", " ", text).strip()
    # Defensive: strip any stray JS variable lines if still present
    summary = re.sub(r'var\s+frontAppContext\b.*?(?:;|\n)', ' ', summary, flags=re.I)
    page_text = soup.get_text('\n', strip=True)
    date_fb = _extract_date(page_text)
    return summary, date_fb


def _summarize(text: str, length: int = 200) -> str:
    # 兼容旧接口名，返回全文（不截断）
    t = re.sub(r"\s+", " ", text).strip()
    return t








