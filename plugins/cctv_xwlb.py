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
from typing import Optional, List

import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import time
import random
import re


DEFAULT_URL = "https://tv.cctv.com/lm/xwlb/index.shtml"


class News(BaseModel):
    title: str
    url: str
    origin: str
    summary: str
    publish_date: str


class Input(BaseModel):
    url: Optional[str] = Field(default=DEFAULT_URL, description="央视新闻联播 首页地址")


class Output(BaseModel):
    news_list: Optional[List[News]] = Field(default=None, description="新闻列表")
    status: str = Field(default="OK", description="响应状态标记")
    err_code: Optional[str] = Field(default=None, description="错误码（可选）")
    err_info: Optional[str] = Field(default=None, description="错误信息（可选）")


Metadata = {
    "name": "get_cctv_xwlb",
    "description": "抓取央视新闻联播首页及详情",
    "input": Input.model_json_schema(),
    "output": Output.model_json_schema(),
}


def handler(args: Args[Input]) -> Output:
    logger = getattr(args, "logger", logging.getLogger(__name__))
    url = args.input.url or DEFAULT_URL
    try:
        html = _fetch_html(url)
        soup = BeautifulSoup(html, 'html5lib')
        ul = soup.find('ul', id='content')
        if not ul:
            return Output(news_list=None, status='ERROR', err_code='INDEX_NOT_FOUND', err_info='ul#content missing')
        li_tags = ul.find_all('li')
        news_dict = {}
        for idx, li in enumerate(li_tags):
            if idx == 0:
                continue
            a = li.find('a')
            if not a:
                continue
            href = a.get('href') or ''
            title_attr = a.get('title') or ''
            title = title_attr[4:] if len(title_attr) > 4 else (a.get_text(strip=True) or '')
            if href and title:
                news_dict[title] = href
        items: List[News] = []
        for title, href in news_dict.items():
            child_html = _fetch_html(href)
            s2 = BeautifulSoup(child_html, 'html5lib')
            content_div = s2.find('div', class_='content_area')
            if not content_div:
                continue
            p_tags = content_div.find_all('p')
            summary = ''.join(p.get_text(strip=True) for p in p_tags)
            ystr = (datetime.today() - timedelta(days=1)).strftime('%Y-%m-%d')
            items.append(News(title=title, url=href, origin='新闻联播', summary=summary, publish_date=ystr))
        status = 'OK' if items else 'EMPTY'
        return Output(news_list=items or None, status=status, err_code=None if items else 'NO_DATA', err_info=None if items else 'No news parsed')
    except Exception as e:
        logger.exception("cctv_xwlb handler failed")
        return Output(news_list=None, status="ERROR", err_code="PLUGIN_ERROR", err_info=str(e))


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
