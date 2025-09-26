"""
每个插件文件都需要导出名为 `handler` 的函数，作为工具入口。

参数:
- args: 入口函数的参数对象
- args.input: 输入参数（例如 args.input.xxx）
- args.logger: 日志记录器，由运行时注入

提示: 请在 Metadata 中补充 input/output，有助于 LLM 正确识别并调用工具。

返回:
返回的数据必须与声明的输出参数结构一致。
"""

from runtime import Args
from pydantic import BaseModel, Field
from typing import Optional, List

import logging
import requests
from bs4 import BeautifulSoup, Tag
from urllib.parse import urlparse, urlunparse
import time
import random
import re


DEFAULT_URL = "https://news.aibase.com/zh/daily"


class News(BaseModel):
    title: str
    url: str
    origin: str
    summary: str
    publish_date: str


class Input(BaseModel):
    url: Optional[str] = Field(default=DEFAULT_URL, description="AI Daily 首页地址")


class Output(BaseModel):
    news_list: Optional[List[News]] = Field(default=None, description="新闻列表")
    status: str = Field(default="OK", description="响应状态标记")
    err_code: Optional[str] = Field(default=None, description="错误码（可选）")
    err_info: Optional[str] = Field(default=None, description="错误信息（可选）")


Metadata = {
    "name": "get_ai_daily",
    "description": "从 aibase.com 抓取 AI Daily 新闻",
    "input": Input.model_json_schema(),
    "output": Output.model_json_schema(),
}


def handler(args: Args[Input]) -> Output:
    logger = getattr(args, "logger", logging.getLogger(__name__))
    url = args.input.url or DEFAULT_URL
    try:
        # 第一步：从首页找到日更文章链接
        index_html = _fetch_html(url)
        soup = BeautifulSoup(index_html, 'html5lib')
        container = soup.find('div', class_="grid grid-cols-1 md:grid-cols-1 md:gap-[16px] gap-[32px] w-full pb-[40px]")
        if not container:
            return Output(news_list=None, status="ERROR", err_code="INDEX_NOT_FOUND", err_info="index container not found")
        a = container.find('a')
        if not a or not a.get('href'):
            return Output(news_list=None, status="ERROR", err_code="INDEX_LINK_NOT_FOUND", err_info="no daily link")
        base = _base_url(url)
        target_url = base + a.get('href')

        # 第二步：解析日更文章页面
        html = _fetch_html(target_url)
        soup2 = BeautifulSoup(html, 'html5lib')
        class_name = 'overflow-hidden space-y-[20px] text-[15px] leading-[25px] break-words mainColor post-content text-wrap'
        div = soup2.find('div', class_=class_name)
        if not div:
            return Output(news_list=None, status="ERROR", err_code="CONTENT_NOT_FOUND", err_info="post-content div missing")
        p_tags = div.find_all('p')
        title = ''
        texts: List[str] = []
        items: List[News] = []
        for idx, p in enumerate(p_tags):
            if idx in (0, 1):
                continue
            direct_children = [ch for ch in p.children if isinstance(ch, Tag)]
            if direct_children and direct_children[0].name == 'strong':
                strong_tag = p.find('strong')
                # skip image-only strong
                if strong_tag:
                    sc = [ch for ch in strong_tag.children if isinstance(ch, Tag)]
                    if sc and sc[0].name == 'img':
                        continue
                if texts:
                    summary = ''.join(texts)
                    texts = []
                    today_str = _today()
                    items.append(News(title=title, url=target_url, origin="Aibase", summary=summary, publish_date=today_str))
                title = strong_tag.get_text(strip=True) if strong_tag else ''
            else:
                text = p.get_text(strip=True)
                if text:
                    texts.append(text)
            if idx == len(p_tags) - 1 and (title or texts):
                summary = ''.join(texts)
                today_str = _today()
                items.append(News(title=title, url=target_url, origin="Aibase", summary=summary, publish_date=today_str))

        status = 'OK' if items else 'EMPTY'
        return Output(news_list=items or None, status=status, err_code=None if items else 'NO_DATA', err_info=None if items else 'No news parsed')
    except Exception as e:
        logger.exception("ai_daily handler failed")
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


def _base_url(u: str) -> str:
    p = urlparse(u)
    return urlunparse((p.scheme, p.netloc, '', '', '', ''))


def _today() -> str:
    from datetime import datetime
    return datetime.strftime(datetime.today(), r"%Y-%m-%d")
