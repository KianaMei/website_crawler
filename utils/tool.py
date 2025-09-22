import requests
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import time
import random
from urllib.parse import urlparse, urljoin
import logging
import re


# 日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# 默认请求头
DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3',
    'Accept-Encoding': 'gzip, deflate',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}


def get_few_days_ago(day_offset) -> List[str]:
    today = datetime.today()
    few_days = [today - timedelta(days=offset) for offset in range(0, day_offset)]
    # 统一日期格式为 YYYY-MM-DD
    return [datetime.strftime(day, r"%Y-%m-%d") for day in few_days]


def join_urls(base_url: str, child_url: str) -> str:
    """
    使用 urljoin 将 base_url 与 child_url 拼接为合法 URL
    例如: https://www.mot.gov.cn/jiaotongyaowen/ + ./202509/t20250918_4176896.html
    """
    return urljoin(base_url, child_url)


def get_html_from_url(
    url: Optional[str],
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 10,
    retries: int = 3,
    delay: float = 1.0,
    no_proxy: bool = True,
    verify_ssl: bool = False,
) -> Optional[str]:
    """
    使用 requests 获取 URL 的 HTML。
    - 默认不使用系统代理 (no_proxy=True)
    - 默认关闭 SSL 证书校验 (verify_ssl=False)
    - 编码优先级: HTML meta -> apparent_encoding -> header -> 常用回退
    """
    if not is_valid_url(url=url):  # type: ignore
        logger.error('请求失败：无效的 URL，未通过校验')
        return None
    else:
        logger.info(f'准备请求 {url}')

    if headers is None:
        headers = DEFAULT_HEADERS.copy()

    for attempt in range(retries):
        try:
            logger.info(f'请求 URL: {url} (第 {attempt + 1}/{retries} 次)')
            session = requests.Session()
            session.headers.update(headers)
            session.trust_env = not no_proxy  # no_proxy=True 时不使用环境代理
            # 默认关闭 SSL 校验，避免部分仅支持 http/自签站点阻塞
            kwargs = {
                'timeout': timeout,
                'verify': verify_ssl,
            }
            if no_proxy:
                kwargs['proxies'] = {'http': None, 'https': None}

            resp = session.get(url, **kwargs)  # type: ignore
            resp.raise_for_status()

            content_type = resp.headers.get('content-type', '') or ''
            ct_lower = content_type.lower()
            if 'text/html' not in ct_lower and 'application/xhtml+xml' not in ct_lower:
                logger.warning(f'响应 Content-Type 非 HTML: {content_type}')

            # ---- 选择编码: HTML meta -> apparent_encoding -> header -> 常用回退 ----
            html_bytes: bytes = resp.content

            def _normalize_charset(cs: str) -> str:
                cs_l = cs.strip().strip('\"\'').lower()
                if cs_l in ('gb2312', 'gb-2312', 'gbk'):
                    return 'gb18030'  # 统一到兼容性更好的编码
                if cs_l in ('utf8', 'utf-8'):
                    return 'utf-8'
                return cs_l or 'utf-8'

            def _encoding_from_header() -> Optional[str]:
                m = re.search(r'charset=([^;\s]+)', content_type, re.IGNORECASE)
                if m:
                    return _normalize_charset(m.group(1))
                if resp.encoding:
                    return _normalize_charset(resp.encoding)
                return None

            def _encoding_from_meta(data: bytes) -> Optional[str]:
                head = data[:4096]
                m = re.search(br'charset\s*=\s*["\']?([a-zA-Z0-9_\-]+)', head, re.IGNORECASE)
                if m:
                    try:
                        return _normalize_charset(m.group(1).decode('ascii', errors='ignore'))
                    except Exception:
                        return None
                return None

            cand: List[str] = []
            meta_enc = _encoding_from_meta(html_bytes)
            if meta_enc:
                cand.append(meta_enc)
            app_enc = resp.apparent_encoding and _normalize_charset(resp.apparent_encoding)
            if app_enc and app_enc not in cand:
                cand.append(app_enc)  # type: ignore[arg-type]
            head_enc = _encoding_from_header()
            if head_enc and head_enc not in cand:
                cand.append(head_enc)
            for fb in ('utf-8', 'gb18030'):
                if fb not in cand:
                    cand.append(fb)

            def _decode_with_best(encodings: List[str]) -> Optional[str]:
                best_txt = None
                best_bad = 10**9
                best_enc = None
                for ec in encodings:
                    try:
                        txt = html_bytes.decode(ec, errors='replace')
                        bad = txt.count('\ufffd')  # replacement char
                        score = (bad, 0 if ec == 'utf-8' else 1)
                        if bad < best_bad or (best_txt is None) or score < (best_bad, 1 if best_enc != 'utf-8' else 0):
                            best_txt = txt
                            best_bad = bad
                            best_enc = ec
                    except Exception:
                        continue
                return best_txt

            html_content = _decode_with_best(cand)
            if html_content is None:
                logger.error('无法解码 HTML，候选编码均失败')
                return None

            enc_used = None
            for ec in cand:
                try:
                    if html_content.encode(ec, errors='ignore'):
                        enc_used = ec
                        break
                except Exception:
                    continue
            logger.info(f'成功获取 HTML，长度: {len(html_content)}，编码: {enc_used or "unknown"}')
            return html_content

        except requests.exceptions.RequestException as e:
            logger.error(f'请求失败 (第 {attempt + 1}/{retries} 次): {e}')
            if attempt < retries - 1:
                sleep_time = delay * (1 + random.random() * 0.5)
                logger.info(f'等待 {sleep_time:.2f}s 重试...')
                time.sleep(sleep_time)
            else:
                logger.error(f'经过 {retries} 次重试仍失败')
                return None

    return None


def is_valid_url(url: str) -> bool:
    """校验 URL 是否有效"""
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except Exception:
        return False


def get_domain_from_url(url: str) -> Optional[str]:
    """从 URL 中提取域名"""
    try:
        parsed_url = urlparse(url)
        return parsed_url.netloc
    except Exception:
        return None


def create_session() -> requests.Session:
    """创建并返回一个 requests 会话，默认关闭 SSL 校验"""
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    session.verify = False  # 默认不要打开 SSL（可按需覆盖）
    return session


def set_random_user_agent(headers: Dict[str, str]) -> Dict[str, str]:
    """随机设置 User-Agent"""
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15'
    ]

    headers = headers.copy()
    headers['User-Agent'] = random.choice(user_agents)
    return headers


# 示例
if __name__ == "__main__":
    test_url = r"https://tv.cctv.com/lm/xwlb/index.shtml"
    html = get_html_from_url(test_url)

    if html:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html.encode('utf-8'), "html5lib")
        ul_element = soup.find('ul', id="content")
        print(f"HTML ul 元素为:{ul_element}")  # type: ignore
    else:
        print("获取 HTML 失败")

