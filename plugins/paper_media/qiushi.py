"""
求是独立插件

每个插件文件都需要导出名为 `handler` 的函数，作为工具入口。
"""

from runtime import Args
from typing import List, Tuple, Optional
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import requests

# 独立模块，包含所有必要的依赖
from pydantic import BaseModel, Field
from typing import Optional, List, Tuple
import logging
import re
import datetime
import requests
import time
import random


class News(BaseModel):
    title: str
    url: str
    origin: str
    summary: str
    publish_date: str


class PaperInput(BaseModel):
    max_items: Optional[int] = Field(default=None, description="最大抓取条数，None 表示不限制")
    since_days: int = Field(default=3, ge=1, le=365, description="近 N 天窗口")
    date: Optional[str] = Field(default=None, description="指定日期（YYYY-MM-DD）")


class PaperOutput(BaseModel):
    news_list: Optional[List[News]] = Field(default=None, description="新闻列表")
    status: str = Field(default="OK", description="响应状态标记")
    err_code: Optional[str] = Field(default=None, description="错误码（可选）")
    err_info: Optional[str] = Field(default=None, description="错误信息（可选）")


def safe_handler(origin_name: str):
    """装饰器：为纸媒处理函数提供统一的错误处理"""
    def decorator(handler_func):
        def wrapper(args: Args[PaperInput]) -> PaperOutput:
            logger = getattr(args, "logger", logging.getLogger(__name__))
            
            # 容忍缺失的 args.input 或字段
            inp_obj = getattr(args, "input", None)
            if isinstance(inp_obj, dict):
                raw_max = inp_obj.get("max_items")
                date_str = inp_obj.get("date")
            else:
                raw_max = getattr(inp_obj, "max_items", None)
                date_str = getattr(inp_obj, "date", None)

            def _to_max(m):
                try:
                    if m is None:
                        return None
                    ms = str(m).strip().lower()
                    if ms in ("", "none", "null"):
                        return None
                    v = int(m)
                    return v if v > 0 else None
                except Exception:
                    return None

            max_items = _to_max(raw_max)
            
            try:
                return handler_func(args, max_items, date_str, origin_name, logger)
            except Exception as e:
                logger.exception(f"{origin_name} handler failed")
                return PaperOutput(
                    news_list=None, 
                    status="ERROR", 
                    err_code="PLUGIN_ERROR", 
                    err_info=str(e)
                )
        return wrapper
    return decorator


Metadata = {
    "name": "get_qiushi_news",
    "description": "获取求是新闻",
    "input": PaperInput.model_json_schema(),
    "output": PaperOutput.model_json_schema(),
}


ROOT_INDEX_URL = 'https://www.qstheory.cn/qs/mulu.htm'


def fetch_url(url: str) -> str:
    """求是专用的URL抓取函数"""
    headers = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
        'referer': 'https://www.qstheory.cn/'
    }
    r = requests.get(url, headers=headers, timeout=30, proxies={'http': None, 'https': None})
    r.raise_for_status()
    r.encoding = r.apparent_encoding
    return r.text


def to_https(u: str) -> str:
    """转换为HTTPS URL"""
    return ('https://' + u.split('://', 1)[1]) if u.startswith('http://') else u


def normalize_url(u: str) -> str:
    """标准化求是URL"""
    u = to_https(u)
    return u.replace('://qstheory.cn', '://www.qstheory.cn')


def get_issue_candidates_from_root(root_url: str = ROOT_INDEX_URL):
    """从根页面获取期刊候选列表"""
    html = fetch_url(root_url)
    s = BeautifulSoup(html, 'html.parser')
    items: List[Tuple[str, str, str]] = []
    seen = set()
    
    for a in s.find_all('a', href=True):
        href = a['href']
        m = re.search(r'/(\d{8})/[a-z0-9]{32}/c\.html$', href)
        if not m:
            continue
        absu = normalize_url(urljoin(root_url, href))
        if absu in seen:
            continue
        seen.add(absu)
        date_str = m.group(1)
        name = a.get_text(strip=True) or f"期刊 {date_str}"
        items.append((name, absu, date_str))
    
    items.sort(key=lambda x: x[2], reverse=True)
    return items


def get_year_list(root_url: str = ROOT_INDEX_URL):
    """获取年度列表"""
    html = fetch_url(root_url)
    s = BeautifulSoup(html, 'html.parser')
    links: List[Tuple[str, str]] = []
    seen = set()
    
    for a in s.find_all('a', href=True):
        href = a['href']
        txt = a.get_text(strip=True)
        if re.search(r'(\d{8}/[a-z0-9]{32}/c\.html)$', href) or re.search(r'/dukan/qs/\d{4}-\d{2}/01/c_\d+\.htm$', href):
            absu = normalize_url(urljoin(root_url, href))
            if absu in seen:
                continue
            seen.add(absu)
            if not txt:
                m = re.search(r'(\d{4})', href)
                txt = f"{m.group(1)}年" if m else '年'
            links.append((txt, absu))
    
    def year_key(item):
        m = re.search(r'(\d{4})', item[1])
        return int(m.group(1)) if m else 0
    
    links.sort(key=year_key, reverse=True)
    return links


def get_issue_list(year_url: str):
    """获取指定年度的期刊列表"""
    html = fetch_url(year_url)
    s = BeautifulSoup(html, 'html.parser')
    issues: List[Tuple[str, str, str]] = []
    seen = set()
    
    for a in s.find_all('a', href=True):
        href = a['href']
        m = re.search(r'/(\d{8})/[a-z0-9]{32}/c\.html$', href)
        if not m:
            continue
        txt = a.get_text(strip=True)
        if not (('期' in txt) or ('目录' in txt) or ('刊' in txt)):
            continue
        absu = normalize_url(urljoin(year_url, href))
        if absu == year_url or absu in seen:
            continue
        seen.add(absu)
        date_str = m.group(1)
        name = txt or f"期刊 {date_str}"
        issues.append((name, absu, date_str))
    
    issues.sort(key=lambda x: x[2])
    return issues


def get_article_list(issue_url: str):
    """获取指定期刊的文章列表"""
    html = fetch_url(issue_url)
    s = BeautifulSoup(html, 'html.parser')
    art_links: List[str] = []
    seen = set()
    
    for a in s.find_all('a', href=True):
        href = a['href']
        absu = ''
        if re.search(r'/\d{8}/[a-z0-9]{32}/c\.html$', href):
            absu = normalize_url(urljoin(issue_url, href))
        elif re.search(r'/dukan/qs/\d{4}-\d{2}/\d{2}/c_\d+\.htm$', href):
            absu = normalize_url(urljoin(issue_url, href))
        if not absu:
            continue
        if absu in seen:
            continue
        seen.add(absu)
        art_links.append(absu)
    return art_links


def collect_qiushi_news(date: Optional[str], max_items: Optional[int], origin: str) -> List[News]:
    """收集求是新闻"""
    # 选择期刊
    chosen = None
    target_idate = None
    if date:
        try:
            y, m, d = date.split('-')
            target_idate = f"{y}{m}{d}"
        except Exception:
            target_idate = None
    
    for name, iurl, idate in get_issue_candidates_from_root(ROOT_INDEX_URL):
        if target_idate and idate == target_idate:
            chosen = (name, iurl, idate)
            break
        if not target_idate:
            chosen = (name, iurl, idate)
            break
    
    if not chosen:
        years = get_year_list(ROOT_INDEX_URL)
        if years:
            yname, yurl = None, None
            preferred = [t for t in years if '/dukan/qs/' in t[1]]
            if preferred:
                yname, yurl = preferred[0]
            else:
                yname, yurl = years[0]
            issues = get_issue_list(yurl)
            if issues:
                for iname, iurl, idate in reversed(issues):
                    if target_idate and idate == target_idate:
                        chosen = (iname, iurl, idate)
                        break
                    if not target_idate:
                        chosen = (iname, iurl, idate)
                        break
                if not chosen:
                    chosen = issues[-1]
    
    if not chosen:
        return []
    
    iname, iurl, idate = chosen
    links = get_article_list(iurl)
    out: List[News] = []
    date_str = f"{idate[:4]}-{idate[4:6]}-{idate[6:]}"
    
    for url in links:
        html = fetch_url(url)
        # 解析文章（简单解析）
        s = BeautifulSoup(html, 'html.parser')
        title = s.h1.get_text(strip=True) if s.h1 else (s.title.get_text(strip=True) if s.title else '')
        body = ''
        for sel in ['#Content','div#content','.content','div.article','#mdf','#detail','.left_t','.lft_Article','.lft_artc_cont','#ozoom']:
            el = s.select_one(sel)
            if el:
                ps = [p.get_text(strip=True) for p in el.find_all('p') if p.get_text(strip=True)]
                if ps:
                    body = '\n'.join(ps)
                    break
        out.append(News(title=title or '', url=url, origin=origin, summary=body or '', publish_date=date_str))
        if max_items is not None and len(out) >= max_items:
            break
    return out


@safe_handler("求是")
def handler(args: Args[PaperInput], max_items: Optional[int], date_str: str, origin_name: str, logger) -> PaperOutput:
    """求是新闻抓取处理函数"""
    news_list = collect_qiushi_news(date_str, max_items, origin_name)
    
    status = 'OK' if news_list else 'EMPTY'
    return PaperOutput(
        news_list=news_list or None, 
        status=status, 
        err_code=None if news_list else 'NO_DATA', 
        err_info=None if news_list else 'No news parsed'
    )