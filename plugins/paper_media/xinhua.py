"""
新华每日电讯抓取插件

每个插件文件都需要导出名为 `handler` 的函数，作为工具入口。
"""

import datetime
import logging
import random
import re
import time
from typing import Callable, List, Optional, Set, Tuple

import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field
from urllib.parse import urljoin

from runtime import Args


class News(BaseModel):
    title: str
    url: str
    origin: str
    summary: str
    publish_date: str


class PaperInput(BaseModel):
    max_items: int = Field(default=10, ge=1, le=50, description="最大抓取数量")
    since_days: int = Field(default=3, ge=1, le=365, description="回溯天数，仅保留以兼容历史参数")
    date: Optional[str] = Field(default=None, description="目标日期，格式为 YYYY-MM-DD")


class PaperOutput(BaseModel):
    news_list: Optional[List[News]] = Field(default=None, description="新闻列表")
    status: str = Field(default="OK", description="响应状态")
    err_code: Optional[str] = Field(default=None, description="错误码（如有）")
    err_info: Optional[str] = Field(default=None, description="错误信息（如有）")


Metadata = {
    "name": "get_xinhua_news",
    "description": "抓取新华每日电讯文章",
    "input": PaperInput.model_json_schema(),
    "output": PaperOutput.model_json_schema(),
}


def fetch_url(url: str) -> str:
    """统一抓取网页内容，处理常见编码差异。"""
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    session = requests.Session()
    session.headers.update(headers)
    session.trust_env = False

    retries = 3
    delay = 1.0

    for attempt in range(retries):
        try:
            resp = session.get(url, timeout=20, verify=False, proxies={"http": None, "https": None})
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            raw = resp.content

            def _normalize(name: Optional[str]) -> Optional[str]:
                if not name:
                    return None
                cleaned = name.strip().strip("\"'").lower()
                if cleaned in {"gb2312", "gb-2312", "gbk"}:
                    return "gb18030"
                if cleaned in {"utf8", "utf-8"}:
                    return "utf-8"
                return cleaned or None

            def _from_meta(data: bytes) -> Optional[str]:
                match = re.search(br"charset\s*=\s*['\"]?([a-zA-Z0-9_\-]+)", data[:4096], re.IGNORECASE)
                if match:
                    try:
                        return _normalize(match.group(1).decode("ascii", errors="ignore"))
                    except Exception:
                        return None
                return None

            def _from_header() -> Optional[str]:
                match = re.search(r"charset=([^;\s]+)", content_type, re.IGNORECASE)
                if match:
                    return _normalize(match.group(1))
                return _normalize(resp.encoding)

            candidates: List[str] = []
            for encoding in (_from_meta(raw), resp.apparent_encoding and _normalize(resp.apparent_encoding), _from_header(), "utf-8", "gb18030"):
                if encoding and encoding not in candidates:
                    candidates.append(encoding)

            best_text = None
            lowest_replacement = 10 ** 9
            for encoding in candidates:
                try:
                    text = raw.decode(encoding, errors="replace")
                except Exception:
                    continue
                bad = text.count("\ufffd")
                if bad < lowest_replacement:
                    best_text = text
                    lowest_replacement = bad
                    if bad == 0:
                        break
            if best_text is not None:
                return best_text
            return raw.decode("utf-8", errors="ignore")
        except requests.RequestException:
            if attempt < retries - 1:
                time.sleep(delay * (1 + random.random() * 0.5))
                continue
            raise


def today_parts() -> Tuple[str, str, str]:
    """返回今天的年月日字符串，方便拼接路径。"""
    today = datetime.date.today()
    return f"{today.year}", f"{today.month:02d}", f"{today.day:02d}"


def find_available_date(get_pages_func: Callable[[str, str, str], List[Tuple[str, str]]], date: Optional[str], max_back_days: int = 7) -> Tuple[str, str, str]:
    """选择一个存在版面的日期，优先使用用户指定日期，其次向前回溯。"""
    if date:
        try:
            y, m, d = date.split("-")
            if get_pages_func(y, m, d):
                return y, m, d
        except Exception:
            pass

    y0, m0, d0 = today_parts()
    base = datetime.date(int(y0), int(m0), int(d0))
    for offset in range(max_back_days + 1):
        day = base - datetime.timedelta(days=offset)
        y, m, d = f"{day.year}", f"{day.month:02d}", f"{day.day:02d}"
        try:
            if get_pages_func(y, m, d):
                return y, m, d
        except Exception:
            continue
    return y0, m0, d0


def safe_handler(origin_name: str) -> Callable[[Callable[[Args[PaperInput], int, Optional[str], str, logging.Logger], PaperOutput]], Callable[[Args[PaperInput]], PaperOutput]]:
    """包装 handler，补齐日志和错误处理。"""

    def decorator(func: Callable[[Args[PaperInput], int, Optional[str], str, logging.Logger], PaperOutput]):
        def wrapper(args: Args[PaperInput]) -> PaperOutput:
            logger = getattr(args, "logger", logging.getLogger(__name__))
            inp_obj = getattr(args, "input", None)
            if isinstance(inp_obj, dict):
                max_items = int(inp_obj.get("max_items") or 10)
                date_str = inp_obj.get("date")
            else:
                max_items = int(getattr(inp_obj, "max_items", 10) or 10)
                date_str = getattr(inp_obj, "date", None)
            try:
                return func(args, max_items, date_str, origin_name, logger)
            except Exception as exc:  # pragma: no cover - 捕获运行时异常
                logger.exception("%s handler failed", origin_name)
                return PaperOutput(
                    news_list=None,
                    status="ERROR",
                    err_code="PLUGIN_ERROR",
                    err_info=str(exc),
                )

        return wrapper

    return decorator


def get_page_list(year: str, month: str, day: str) -> List[Tuple[str, str]]:
    """抓取当日版面链接。返回 (页面地址, 页面名称)。"""
    base_url = "http://mrdx.cn/content"
    date_dir = f"{year}{month}{day}"
    root = f"{base_url.rstrip('/')}/{date_dir}/"

    first_html = ""
    first_url = ""
    for fname in ["Page01DK.htm", "Page01.htm", "page01.htm", "Page01A.htm", "Page01B.htm"]:
        url = urljoin(root, fname)
        try:
            html = fetch_url(url)
        except Exception:
            continue
        if "shijuedaohang" in html or "pageto" in html:
            first_html = html
            first_url = url
            break

    if not first_html:
        return []

    soup = BeautifulSoup(first_html, "html.parser")
    nav = soup.find("div", class_="shijuedaohang")
    items: List[Tuple[str, str]] = []

    if nav:
        for a in nav.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.lower().startswith("javascript"):
                continue
            page_url = urljoin(first_url, href)
            name = ""
            h4 = a.find("h4")
            if h4 and h4.get_text(strip=True):
                name = h4.get_text(strip=True)
            else:
                img = a.find("img")
                if img and (img.get("alt") or "").strip():
                    name = img.get("alt").strip()
            name = name or href
            safe_name = "".join(ch for ch in name if ch not in r"\/:*?\"<>|")
            items.append((page_url, safe_name))

    if not items:
        patterns = [
            "Page{idx:02d}DK.htm",
            "Page{idx:02d}.htm",
            "page{idx:02d}.htm",
        ]
        for i in range(1, 33):
            for pat in patterns:
                fname = pat.format(idx=i)
                page_url = urljoin(root, fname)
                try:
                    fetch_url(page_url)
                except Exception:
                    continue
                items.append((page_url, f"Page {i:02d}"))
                break
        seen: Set[str] = set()
        dedup: List[Tuple[str, str]] = []
        for page_url, name in items:
            if page_url not in seen:
                seen.add(page_url)
                dedup.append((page_url, name))
        items = dedup

    return items


def get_title_list(year: str, month: str, day: str, page_url: str) -> List[str]:
    """解析版面，抽取文章链接。"""
    html = fetch_url(page_url)
    links: List[str] = []
    seen: Set[str] = set()

    try:
        for parser in ("lxml", "html5lib", "html.parser"):
            try:
                soup = BeautifulSoup(html, parser)
                break
            except Exception:
                continue
        else:
            soup = BeautifulSoup(html, "html.parser")

        candidates = []
        candidates.extend(soup.find_all("a", href=True))
        candidates.extend(soup.find_all("area", href=True))

        patterns = [
            re.compile(r"(?i)Artic?le.*\\.htm$"),
            re.compile(r"(?i)content.*\\.htm$"),
        ]

        for tag in candidates:
            href = tag.get("href", "").strip()
            if not href or href.lower().startswith("javascript"):
                continue
            if not href.lower().endswith(".htm"):
                continue
            if not any(p.search(href) for p in patterns):
                continue
            abs_url = urljoin(page_url, href)
            if re.search(r"(?i)(^|/)(Page\d+[^/]*\.htm)$", href):
                continue
            if abs_url in seen:
                continue
            seen.add(abs_url)
            links.append(abs_url)
    except Exception:
        pass

    if not links:
        rels = re.findall(r'daoxiang="([^"]+)"', html, flags=re.I)
        for rel in rels:
            rel = rel.strip()
            if not rel.lower().endswith(".htm"):
                continue
            abs_url = urljoin(page_url, rel)
            if abs_url not in seen:
                seen.add(abs_url)
                links.append(abs_url)

        rels2 = re.findall(r'href="([^"]*Artic?el[^"]*\.htm)"', html, flags=re.I)
        for rel in rels2:
            abs_url = urljoin(page_url, rel)
            if abs_url not in seen:
                seen.add(abs_url)
                links.append(abs_url)

    return links


def _looks_like_date_line(line: str) -> bool:
    return bool(re.search(r"（?\s*\d{4}[年\-/]\d{1,2}[月\-/]\d{1,2}\s*）?", line))


def parse_article(html: str) -> Tuple[str, str, str, str, str]:
    """提取文章标题与正文，并返回正文全文作为摘要。"""
    soup = None
    for parser in ("lxml", "html5lib", "html.parser"):
        try:
            soup = BeautifulSoup(html, parser)
            break
        except Exception:
            continue
    if soup is None:
        soup = BeautifulSoup(html, "html.parser")

    title = ""
    for font in soup.find_all("font"):
        style = font.get("style", "")
        if "FONT-SIZE: 23px" in style:
            title = font.get_text(strip=True)
            break
    if not title:
        h2 = soup.find("h2")
        if h2:
            title = h2.get_text(strip=True)
        elif soup.title:
            whole = soup.title.get_text(strip=True)
            title = whole.split("-")[0].strip() if "-" in whole else whole

    safe_title = "".join(ch for ch in title if ch not in r"\/:*?\"<>|")

    body = ""
    content_div = None
    try:
        content_div = (
            soup.find("div", id=re.compile("zoom", re.I))
            or soup.find("div", class_=re.compile("(zoom|content|text|article)", re.I))
        )
    except Exception:
        content_div = None

    if content_div:
        for br in content_div.find_all("br"):
            br.replace_with("\n")
        parts: List[str] = []
        for el in content_div.find_all(["p", "div"]):
            txt = el.get_text("\n", strip=True)
            if txt and len(txt) > 2:
                parts.append(txt)
        if not parts:
            parts = [content_div.get_text("\n", strip=True)]
        body = "\n".join(parts)

    if not body:
        info_table = None
        for table in soup.find_all("table"):
            text = table.get_text()
            if "文章来源" in text and "新华每日电讯" in text:
                info_table = table
                break
        if info_table:
            elements: List[str] = []
            table_found = False
            for element in soup.find_all(["div", "p", "h1", "h2", "h3", "h4", "h5", "h6"]):
                if not table_found:
                    if element == info_table or (hasattr(element, "find") and element.find("table") == info_table):
                        table_found = True
                    continue
                if hasattr(element, "get_text"):
                    for br in element.find_all("br"):
                        br.replace_with("\n")
                    text = element.get_text(strip=True)
                    if text and len(text) > 2 and "文章来源" not in text and "责任编辑" not in text and "编辑" not in text:
                        if not _looks_like_date_line(text):
                            elements.append(text)
            if elements:
                body = "\n\n".join(elements)

    if not body:
        for div in soup.find_all("div"):
            div_text = div.get_text(strip=True)
            if div_text and len(div_text) > 100 and "文章来源" not in div_text and "新华每日电讯" not in div_text:
                for br in div.find_all("br"):
                    br.replace_with("\n")
                body = div.get_text(strip=True)
                break

    if not body:
        paragraphs: List[str] = []
        for p in soup.find_all("p"):
            p_text = p.get_text(strip=True)
            if not p_text or len(p_text) <= 10:
                continue
            if "文章来源" in p_text or "责任编辑" in p_text:
                continue
            if _looks_like_date_line(p_text):
                continue
            paragraphs.append(p_text)
        if paragraphs:
            body = "\n".join(paragraphs)

    body = body.replace("\u3000", " ").replace("\xa0", " ")
    body = re.sub(r"\n{2,}", "\n", body)
    body = body.strip()

    if body:
        lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
        meta_patterns = [
            r"^\s*（\s*\d{4}-\d{2}-\d{2}\s*）",
            r"^\s*文章来源[:：]",
            r"^\s*新华每日电讯(\s+\d{4}年\d{2}月\d{2}日)?",
            r"^\s*第\s*\d+版$",
            r"^\s*编辑[:：]",
            r"^\s*责任编辑[:：]",
            r"^\s*上一篇\s*$",
            r"^\s*下一篇\s*$",
        ]
        cleaned: List[str] = []
        seen_line: Set[str] = set()
        previous = None
        for line in lines:
            if title and line == title:
                continue
            if any(re.search(pattern, line) for pattern in meta_patterns):
                continue
            if line != previous and line not in seen_line:
                cleaned.append(line)
                seen_line.add(line)
                previous = line
        body = "\n".join(cleaned)

    content_full = f"{title}\n{body}" if title and body else (body or title)
    summary = re.sub(r"\s+", " ", body).strip() if body else body
    return content_full or "", safe_title, title or "", body or "", summary or ""


@safe_handler("新华每日电讯")
def handler(args: Args[PaperInput], max_items: int, date_str: Optional[str], origin_name: str, logger: logging.Logger) -> PaperOutput:
    """抓取指定日期的新华每日电讯文章。"""
    y, m, d = find_available_date(get_page_list, date_str)
    news_list: List[News] = []
    seen_urls: Set[str] = set()

    for page_url, _ in get_page_list(y, m, d):
        if len(news_list) >= max_items:
            break
        try:
            title_links = get_title_list(y, m, d, page_url)
        except Exception as exc:
            logger.warning("获取文章列表失败: %s err=%s", page_url, exc)
            continue
        for url in title_links:
            if len(news_list) >= max_items:
                break
            if url in seen_urls:
                continue
            seen_urls.add(url)
            try:
                html = fetch_url(url)
                _, _, title, body, summary = parse_article(html)
                if not title and not body:
                    continue
                news_list.append(
                    News(
                        title=title or "",
                        url=url,
                        origin=origin_name,
                        summary=summary or (body or ""),
                        publish_date=f"{y}-{m}-{d}",
                    )
                )
                time.sleep(0.2 + random.random() * 0.2)
            except Exception as exc:
                logger.warning("解析文章失败: %s err=%s", url, exc)
                continue

    if not news_list:
        return PaperOutput(
            news_list=None,
            status="EMPTY",
            err_code="NO_DATA",
            err_info="No news parsed",
        )

    return PaperOutput(news_list=news_list, status="OK", err_code=None, err_info=None)
