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
from typing import Optional, List, Dict

import logging
import asyncio
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from playwright.async_api import async_playwright


DEFAULT_URL = "https://www.mofcom.gov.cn/"


class News(BaseModel):
    title: str
    url: str
    origin: str
    summary: str
    publish_date: str


class Input(BaseModel):
    url: Optional[str] = Field(default=DEFAULT_URL, description="商务部 首页地址")


class Output(BaseModel):
    news_list: Optional[List[News]] = Field(default=None, description="新闻列表")
    status: str = Field(default="OK", description="响应状态标记")
    err_code: Optional[str] = Field(default=None, description="错误码（可选）")
    err_info: Optional[str] = Field(default=None, description="错误信息（可选）")


Metadata = {
    "name": "get_gov_commerce",
    "description": "使用 Playwright 异步抓取商务部新闻并返回结果",
    "input": Input.model_json_schema(),
    "output": Output.model_json_schema(),
}


def _run_async(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        new_loop = asyncio.new_event_loop()
        try:
            return new_loop.run_until_complete(coro)
        finally:
            new_loop.close()
    else:
        return asyncio.run(coro)


def handler(args: Args[Input]) -> Output:
    """商务部新闻（Playwright 异步）插件"""
    logger = getattr(args, "logger", logging.getLogger(__name__))
    url = args.input.url or DEFAULT_URL
    try:
        res = _run_async(_get_news(url))
        items = [
            News(title=n['title'], url=n['url'], origin='商务部', summary=n['summary'], publish_date=n['publish_date'])
            for n in res
        ]
        status = 'OK' if items else 'EMPTY'
        return Output(news_list=items or None, status=status, err_code=None if items else 'NO_DATA', err_info=None if items else 'No news parsed')
    except Exception as e:
        logger.exception("gov_commerce handler failed")
        return Output(news_list=None, status="ERROR", err_code="PLUGIN_ERROR", err_info=str(e))


async def _get_news(base_url: str):
    async def _get_news_url_dict(child_url: str) -> Dict[str, str]:
        url = urljoin(base_url, child_url)
        few_days = _few_days(4)
        news_url_dict: Dict[str, str] = {}
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            try:
                await page.goto(url, wait_until="networkidle")
                ul_selector = "ul.txtList_01"
                await page.wait_for_selector(ul_selector, timeout=10000)
                li_elements = await page.query_selector_all(f"{ul_selector} > li")
                for li in li_elements:
                    a_tag = await li.query_selector("a")
                    span_tag = await li.query_selector("> span")
                    if not a_tag or not span_tag:
                        continue
                    href = await a_tag.get_attribute("href") or None
                    title = await a_tag.get_attribute("title") or None
                    date_text = await span_tag.text_content()
                    date = (date_text or '').strip().strip('[]')
                    if date not in few_days:
                        continue
                    final_url = urljoin(base_url, href or '')
                    news_url_dict[f"{title};{date}"] = final_url
                return news_url_dict
            finally:
                await browser.close()

    merged: Dict[str, str] = {}
    for child in (r'xwfb/ldrhd/index.html', r'xwfb/bldhd/index.html'):
        d = await _get_news_url_dict(child)
        merged.update(d)

    out = []
    for title_date, link in merged.items():
        html = _fetch_html(link)
        soup = BeautifulSoup(html, 'html5lib')
        div = soup.find('div', class_='art-con art-con-bottonmLine')
        if not div:
            continue
        p_tags = div.find_all('p')
        text = ''.join(p.get_text(strip=True) for p in p_tags)
        title_part, publish_date = title_date.split(';', 1)
        out.append({
            'title': title_part or '',
            'url': link,
            'summary': text or '',
            'publish_date': publish_date,
        })
        if len(out) >= 50:
            break
    return out


def _fetch_html(url: str) -> str:
    headers = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
    }
    r = requests.get(url, headers=headers, timeout=30, proxies={'http': None, 'https': None}, verify=False)
    r.raise_for_status()
    if not r.encoding:
        r.encoding = r.apparent_encoding
    return r.text


def _few_days(n: int):
    from datetime import datetime, timedelta
    base = datetime.today()
    return [(base - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(0, n)]
